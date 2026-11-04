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
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"

# 設施的狀態
YES = "有"              # 資料明確標示有
NO = "沒有"             # 資料明確標示沒有
UNKNOWN = "不知道"       # 資料沒提到，需要自己確認
ASSUMED = "推定有"       # 資料沒提到，但依 config 的設定推定為有
#
# ASSUMED 存在的理由：Google 的設施資料極度稀疏（20 間只有 2 間標冷氣），
# 但那些飯店實際上都有。把「沒寫」一律當成「要確認」會讓畫面充滿雜訊。
# 不過推定終究不是查證 —— 所以它是獨立的狀態，畫面上顯示「推定有」，
# 絕不混充成「有」。


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
    """
    起跳價 + 超出內含里程的部分 × 每公里單價。

    內含里程很重要：台北起跳 85 元「已經含 1.25 公里」，
    忽略它的話短程會被高估 —— 走 1 公里卻按 1 公里再加一次錢。
    """
    extra = max(distance_km - fare.get("included_km", 0), 0.0)
    return fare["base"] + fare["per_km"] * extra


def resolve_fare(config: dict, city: str | None,
                 country_code: str | None) -> tuple[dict, str]:
    """
    找出該用哪組費率。順序：城市 → 國家 → 預設。

    回傳 (費率, 來源)，來源是 "city" / "country" / "default"。
    來源要讓畫面知道，因為用到 default 時那只是保守估計，必須提醒使用者。
    """
    cities = config.get("taxi_fare", {})
    if city and city in cities:
        return cities[city], "city"
    countries = config.get("taxi_fare_by_country", {})
    code = (country_code or "").lower()
    if code and code in countries:
        return countries[code], "country"
    return cities["default"], "default"


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


def first_image(hotel: dict) -> str | None:
    """
    從飯店資料裡挑一張縮圖。

    SerpApi 的 images 欄位格式不固定（可能是字串陣列，也可能是物件陣列），
    所以這裡把幾種可能都試一遍，試不到就回傳 None，畫面會顯示佔位圖。
    """
    images = hotel.get("images") or []
    for item in images:
        if isinstance(item, str) and item.startswith("http"):
            return item
        if isinstance(item, dict):
            for key in ("thumbnail", "original_image", "image", "url", "link"):
                value = item.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value
    return None


# ------------------------------------------------------------ 評估結果

@dataclass
class Verdict:
    """一間飯店的評估結果。"""
    name: str
    passed: bool                                      # 是否進入候選名單
    rejected_for: list[str] = field(default_factory=list)   # 淘汰原因
    to_confirm: list[str] = field(default_factory=list)     # 需人工確認（含設施）
    # 設施缺資料這件事，卡片上已經用「？電梯」這種標籤表達了，
    # 不需要再寫一行字。notes 只放標籤表達不出來的事（缺價格、缺座標、費率是估的）。
    notes: list[str] = field(default_factory=list)
    price_usd: float | None = None
    price_with_buffer: float | None = None
    distance_km: float | None = None
    fare_one_way: float | None = None
    fare_per_day: float | None = None
    fare_is_default: bool = False
    wrong_type: bool = False          # 不是飯店（民宿、露營地…），畫面整筆不顯示
    looks_like_dorm: bool = False     # 名稱或簡介顯示是通舖型住宿，整筆不顯示
    # 第一個淘汰原因的分類。沒有結果時用來統計「是哪一條規則刷掉的」，
    # 否則使用者只會看到三區全空、完全不知道該調哪個設定。
    reject_category: str | None = None
    walkable: bool = False                            # 走得到，不需搭車
    total_daily_usd: float | None = None              # 房價 + 當日交通費
    has_availability: bool = False                    # 查詢當下有可訂價格
    amenities: dict = field(default_factory=dict)     # 必要條件的三態結果
    bonuses: dict = field(default_factory=dict)       # 加分條件的三態結果
    # 以下純粹給畫面顯示用，不參與任何判斷
    image_url: str | None = None
    link: str | None = None          # 飯店官網（SerpApi 給的）
    compare_url: str | None = None   # Google Hotels 比價頁（程式自己組的）
    rating: float | None = None
    reviews: int | None = None
    stars: int | None = None


# 淘汰原因的分類（畫面上用來統計）
CATEGORIES = {
    "type": "不是飯店",
    "dorm": "通舖或共用衛浴",
    "price_high": "超過房價上限",
    "price_low": "低於房價下限",
    "fare": "交通費超標",
    "sold_out": "查詢當下沒有空房",
    "amenity": "明確缺少必要設施",
}


def evaluate(hotel: dict, destination: tuple[float, float],
             config: dict, fare: dict,
             fare_source: str = "default") -> Verdict:
    """
    把一筆 SerpApi 回傳的飯店資料，對照 config.toml 的規則做判定。

    hotel       -- SerpApi properties 陣列裡的一筆
    destination -- (緯度, 經度)，通常是展館
    fare        -- 已經換算成美金的費率（base / per_km / included_km）
                   換匯要連網，所以在外面做，這支程式保持不連網
    fare_source -- "city" / "country" / "default" / "fx_failed"，
                   用來在畫面上說明費率從哪來、可不可靠
    """
    budget = config["budget"]
    labels = config.get("labels", {})
    v = Verdict(name=hotel.get("name") or "(無名稱)", passed=True)
    v.image_url = first_image(hotel)
    v.link = hotel.get("link")
    v.rating = hotel.get("overall_rating")
    v.reviews = hotel.get("reviews")
    v.stars = hotel.get("extracted_hotel_class")

    def label(key: str) -> str:
        return labels.get(key, key)

    # --- 1. 住宿類型：必須是飯店（這條同時保證了獨立衛浴）---
    kind = (hotel.get("type") or "").strip().lower()
    allowed = [t.lower() for t in config["accommodation"]["allowed_types"]]
    if kind not in allowed:
        v.passed = False
        v.wrong_type = True
        v.reject_category = v.reject_category or "type"
        v.rejected_for.append(f"住宿類型是「{hotel.get('type') or '未知'}」，不是飯店")

    # --- 1b. 名稱看起來就是通舖的，直接排除 ---
    # 有些青年旅館把自己登記成 type="hotel"，上面那道擋不住。
    # 這是看名字猜，不是看資料，所以關鍵字放在 config.toml 讓人隨時調整。
    accommodation = config["accommodation"]
    lowered = (hotel.get("name") or "").lower()
    for word in accommodation.get("exclude_name_keywords", []):
        # 詞首比對：hostel 命中 Hostels / Hostelling，
        # 但名字中間剛好有這串字母的不會中（例如 Dormy Inn 不該被 dorm 誤殺）。
        if re.search(r"\b" + re.escape(word.strip().lower()), lowered):
            v.passed = False
            v.looks_like_dorm = True
            v.reject_category = v.reject_category or "dorm"
            v.rejected_for.append(f"名稱含「{word}」，研判是通舖型住宿")
            break

    # 簡介裡寫明白的比看名字可靠 —— 那是資料，不是從名字推測的
    if not v.looks_like_dorm:
        description = (hotel.get("description") or "").lower()
        for phrase in accommodation.get("exclude_description_keywords", []):
            # 詞首比對：hostel 命中 hostels，但 dorms 不會命中 Dormy
            if re.search(r"\b" + re.escape(phrase.strip().lower()), description):
                v.passed = False
                v.looks_like_dorm = True
                v.reject_category = v.reject_category or "dorm"
                v.rejected_for.append(f"簡介提到「{phrase}」，研判是通舖或共用衛浴")
                break

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
            v.reject_category = v.reject_category or "sold_out"
            v.rejected_for.append(
                "查詢當下沒有可訂價格 —— 可能是這些日期沒空房，"
                "也可能不是真正可訂的飯店"
            )
        else:
            v.to_confirm.append("這筆沒有價格資料，需要自己點開確認")
            v.notes.append("這筆沒有價格資料，需要自己點開確認")
    else:
        pct = config["exchange_rate"]["buffer_percent"]
        buffered = price * (1 + pct / 100)
        v.price_usd = float(price)
        v.price_with_buffer = round(buffered, 2)
        floor = budget.get("hotel_min_per_night_usd", 0) or 0
        if floor and price < floor:
            # 刻意不標成 looks_like_dorm —— 那會讓它整筆消失。
            # 下限是你自己設的數字，設錯時必須看得見才改得回來。
            v.passed = False
            v.reject_category = v.reject_category or "price_low"
            v.rejected_for.append(
                f"每晚 ${price} 低於你設的下限 ${floor:g}"
            )
        cap = budget["hotel_max_per_night_usd"]
        if buffered > cap:
            v.passed = False
            v.reject_category = v.reject_category or "price_high"
            v.rejected_for.append(
                f"每晚 ${price}，加 {pct}% 緩衝後 ${buffered:.2f}，超過上限 ${cap:g}"
            )

    # --- 3. 交通費：距離換算車資，單趟與每日都要在上限內 ---
    gps = hotel.get("gps_coordinates") or {}
    lat, lon = gps.get("latitude"), gps.get("longitude")
    if lat is None or lon is None:
        v.to_confirm.append("這筆沒有座標，無法計算交通費")
        v.notes.append("這筆沒有座標，無法計算交通費")
    else:
        straight = haversine_km(lat, lon, destination[0], destination[1])
        road = straight * config["distance"]["road_detour_factor"]
        # "city" / "country" 代表用的是該地的實際費率；
        # 其餘都是退回保守預設值，但原因不同，訊息要分開寫。
        is_default = fare_source not in ("city", "country")
        one_way = estimate_fare(road, fare)

        v.distance_km = round(road, 2)
        v.fare_one_way = round(one_way, 2)
        v.fare_per_day = round(one_way * 2, 2)
        v.fare_is_default = is_default
        # 走得到就不需要搭車，交通費視為 0，也不受塞車與尖峰加成影響
        v.walkable = road <= config["distance"]["walking_max_km"]

        if one_way > budget["taxi_max_one_way_usd"]:
            v.passed = False
            v.reject_category = v.reject_category or "fare"
            v.rejected_for.append(
                f"距離 {road:.1f} 公里，單趟約 ${one_way:.2f}，"
                f"超過單趟上限 ${budget['taxi_max_one_way_usd']:g}"
            )
        # 費率是估的這件事，是整次搜尋共通的狀況，不是某一間飯店的問題。
        # 以前把它寫進 to_confirm，結果只要某地沒費率，所有飯店都被推進
        # 「待確認」，「完全符合」永遠是 0 筆；每張卡片還重複同一句話。
        # 現在只留 fare_is_default 這個旗標，由畫面在最上面講一次。

    # --- 3b. 每日總花費：房價 + 當日交通費（走得到的話交通費算 0）---
    if v.price_usd is not None:
        transport = 0.0 if v.walkable else (v.fare_per_day or 0.0)
        v.total_daily_usd = round(v.price_usd + transport, 2)

    # --- 4. 必要設施：只有「明確沒有」才淘汰，「不知道」保留 ---
    have = hotel.get("amenities")
    lack = hotel.get("excluded_amenities")
    match_table = config["amenity_match"]

    assume = config.get("assume_when_unknown", {})
    for key, needed in config["required"].items():
        if not needed or key not in match_table:
            continue
        state = check_amenity(have, lack, match_table[key])
        # 沒標示但設定為「推定有」時，不列入待確認，但狀態誠實標示為推定
        if state == UNKNOWN and assume.get(key):
            state = ASSUMED
        v.amenities[key] = state
        if state == NO:
            v.passed = False
            v.reject_category = v.reject_category or "amenity"
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
