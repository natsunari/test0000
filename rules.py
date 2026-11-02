"""
規則引擎 —— 把 config.toml 的限制套用到一間飯店上，判斷合格與否。

這支程式完全不連網，純粹是運算與比對，所以可以反覆執行、也容易測試。
抓資料是另一支程式的工作。

設計原則（本專案最重要的一條）：
    設施資料有三種狀態 —— 有 / 沒有 / 不知道。

    實測 20 間東京飯店，只有 2 間標了冷氣、1 間標了電梯，
    但那些飯店實際上幾乎都有。「沒寫」只代表 Google 沒這筆資料。
    若把「不知道」當成「沒有」來淘汰，20 間會被刷掉 18 間，工具就廢了。

    所以：只有「明確標示沒有」才淘汰，「不知道」一律保留並標記待確認。
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"

# 設施的三種狀態
YES = "有"
NO = "沒有"
UNKNOWN = "不知道"


def load_config(path: Path | None = None) -> dict:
    """讀取 config.toml。Python 3.11 以上內建 tomllib，不需額外套件。"""
    with open(path or CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


# ------------------------------------------------------------ 距離與車資

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine 公式：地球表面兩點間的直線距離（公里）。
    這是「鳥飛的距離」，不是開車的距離 —— 路程要再乘 road_detour_factor。
    """
    earth_radius_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def estimate_fare(distance_km: float, fare: dict) -> float:
    """起跳價 + 每公里 × 距離。負距離視為 0，避免算出負車資。"""
    return fare["base_usd"] + fare["per_km_usd"] * max(distance_km, 0.0)


def get_fare(config: dict, city: str | None) -> tuple[dict, bool]:
    """
    找該城市的計程車費率，找不到就用預設值。
    回傳 (費率, 是否為預設值)。第二個值用來在畫面上提醒費率只是估計。
    """
    table = config["taxi_fare"]
    if city and city in table:
        return table[city], False
    return table["default"], True


# ------------------------------------------------------------ 設施三態判定

def check_amenity(amenities: list[str] | None,
                  excluded: list[str] | None,
                  match: dict) -> str:
    """
    回傳 YES / NO / UNKNOWN 三者之一。

    先看明確的否定（excluded_amenities），那是可靠的負面訊號；
    再看肯定；兩邊都沒命中就是 UNKNOWN。
    """
    have = {s.strip().lower() for s in (amenities or [])}
    lack = {s.strip().lower() for s in (excluded or [])}

    for word in match.get("means_no", []):
        w = word.strip().lower()
        if w in lack or w in have:
            return NO
    for word in match.get("means_yes", []):
        if word.strip().lower() in have:
            return YES
    return UNKNOWN


# ------------------------------------------------------------ 評估結果

@dataclass
class Verdict:
    """一間飯店的評估結果。"""
    name: str
    passed: bool                                      # 是否進入候選名單
    rejected_for: list[str] = field(default_factory=list)   # 淘汰原因
    to_confirm: list[str] = field(default_factory=list)     # 需人工確認
    price_usd: float | None = None
    price_with_buffer: float | None = None
    distance_km: float | None = None
    fare_one_way: float | None = None
    fare_per_day: float | None = None
    fare_is_default: bool = False
    walkable: bool = False                            # 走得到，不需搭車
    total_daily_usd: float | None = None              # 房價 + 當日交通費
    has_availability: bool = False                    # 查詢當下有可訂價格
    amenities: dict = field(default_factory=dict)     # 必要條件的三態結果
    bonuses: dict = field(default_factory=dict)       # 加分條件的三態結果


def evaluate(hotel: dict, destination: tuple[float, float],
             config: dict, city: str | None = None) -> Verdict:
    """
    把一筆 SerpApi 回傳的飯店資料，對照 config.toml 的規則做判定。

    hotel       -- SerpApi properties 陣列裡的一筆
    destination -- (緯度, 經度)，通常是展館
    city        -- 用來查計程車費率，可省略
    """
    budget = config["budget"]
    labels = config.get("labels", {})
    v = Verdict(name=hotel.get("name") or "(無名稱)", passed=True)

    def label(key: str) -> str:
        return labels.get(key, key)

    # --- 1. 住宿類型：必須是飯店（這條同時保證了獨立衛浴）---
    kind = (hotel.get("type") or "").strip().lower()
    allowed = [t.lower() for t in config["accommodation"]["allowed_types"]]
    if kind not in allowed:
        v.passed = False
        v.rejected_for.append(f"住宿類型是「{hotel.get('type') or '未知'}」，不是飯店")

    # --- 2. 房價：加上緩衝後仍需在上限內 ---
    price = (hotel.get("rate_per_night") or {}).get("extracted_display_price")
    v.has_availability = price is not None
    if price is None:
        # Google 是帶著入住日期去查的，拿不到可訂價格就代表訂不了。
        #
        # 實測發現這有兩種成因，兩種都該排除：
        #   1. 這些日期沒空房
        #   2. 根本不是可訂的飯店 —— 實測 20 筆中的 2 筆，
        #      一筆是產後護理之家，一筆是飯店附設餐廳，
        #      兩筆的 type 都被 Google 標成 "hotel"
        # 所以這道過濾同時也補上了 type 欄位不可靠的漏洞。
        if config.get("availability", {}).get("require", True):
            v.passed = False
            v.rejected_for.append(
                "查詢當下沒有可訂價格 —— 可能是這些日期沒空房，"
                "也可能不是真正可訂的飯店"
            )
        else:
            v.to_confirm.append("這筆沒有價格資料，需要自己點開確認")
    else:
        pct = config["exchange_rate"]["buffer_percent"]
        buffered = price * (1 + pct / 100)
        v.price_usd = float(price)
        v.price_with_buffer = round(buffered, 2)
        cap = budget["hotel_max_per_night_usd"]
        if buffered > cap:
            v.passed = False
            v.rejected_for.append(
                f"每晚 ${price}，加 {pct}% 緩衝後 ${buffered:.2f}，超過上限 ${cap}"
            )

    # --- 3. 交通費：距離換算車資，單趟與每日都要在上限內 ---
    gps = hotel.get("gps_coordinates") or {}
    lat, lon = gps.get("latitude"), gps.get("longitude")
    if lat is None or lon is None:
        v.to_confirm.append("這筆沒有座標，無法計算交通費")
    else:
        straight = haversine_km(lat, lon, destination[0], destination[1])
        road = straight * config["distance"]["road_detour_factor"]
        fare, is_default = get_fare(config, city)
        one_way = estimate_fare(road, fare)

        v.distance_km = round(road, 2)
        v.fare_one_way = round(one_way, 2)
        v.fare_per_day = round(one_way * 2, 2)
        v.fare_is_default = is_default
        # 走得到就不需要搭車，交通費視為 0，也不受塞車與尖峰加成影響
        v.walkable = road <= config["distance"]["walking_max_km"]

        if one_way > budget["taxi_max_one_way_usd"]:
            v.passed = False
            v.rejected_for.append(
                f"距離 {road:.1f} 公里，單趟約 ${one_way:.2f}，"
                f"超過單趟上限 ${budget['taxi_max_one_way_usd']}"
            )
        elif v.fare_per_day > budget["taxi_max_per_day_usd"]:
            v.passed = False
            v.rejected_for.append(
                f"來回約 ${v.fare_per_day:.2f}，"
                f"超過每日上限 ${budget['taxi_max_per_day_usd']}"
            )
        if is_default:
            v.to_confirm.append("這個城市還沒填計程車費率，用的是保守預設值")

    # --- 3b. 每日總花費：房價 + 當日交通費（走得到的話交通費算 0）---
    if v.price_usd is not None:
        transport = 0.0 if v.walkable else (v.fare_per_day or 0.0)
        v.total_daily_usd = round(v.price_usd + transport, 2)

    # --- 4. 必要設施：只有「明確沒有」才淘汰，「不知道」保留 ---
    have = hotel.get("amenities")
    lack = hotel.get("excluded_amenities")
    match_table = config["amenity_match"]

    for key, needed in config["required"].items():
        if not needed or key not in match_table:
            continue
        state = check_amenity(have, lack, match_table[key])
        v.amenities[key] = state
        if state == NO:
            v.passed = False
            v.rejected_for.append(f"明確標示沒有{label(key)}")
        elif state == UNKNOWN:
            v.to_confirm.append(f"{label(key)}：資料未標示，需要自己確認")

    # --- 5. 加分條件：不影響合格與否，只影響排序 ---
    for key, wanted in config["preferred"].items():
        if wanted and key in match_table:
            v.bonuses[key] = check_amenity(have, lack, match_table[key])

    return v


def sort_key(v: Verdict) -> tuple:
    """
    排序用，數字越小越前面。

    規則（使用者選擇的 D 方案）：
      1. 走路可達的優先 —— 交通費 $0，而且不會因為塞車、尖峰加成
         或臨時多跑一趟而超出公司上限，風險最低
      2. 其餘照「每日總花費」（房價 + 交通費）由低到高
      3. 同分時，待確認項目少的排前面
    """
    return (
        0 if v.walkable else 1,
        v.total_daily_usd if v.total_daily_usd is not None else 9e9,
        len(v.to_confirm),
    )
