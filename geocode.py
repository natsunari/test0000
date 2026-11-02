"""
把「目的地」轉成座標。使用者可以輸入座標，也可以輸入地址或地標名稱。

座標 → 直接使用，不連網。
地址 → 用 OpenStreetMap 的 Nominatim 查詢。

⚠️ Nominatim 使用政策（https://operations.osmfoundation.org/policies/nominatim/）
   這是靠捐贈營運、容量有限的公共服務，本程式據此遵守下列規定：
     * 每秒最多 1 次請求 —— 由 _throttle() 強制
     * 必須送出可識別本應用的 User-Agent —— 缺少會被回 403
     * 禁止批次查詢與輸入即時建議（search-as-you-type）—— 本程式只在使用者
       按下按鈕時查一次
     * 應快取結果 —— 查過的地點存進 venues.json，不重複查
     * 顯示資料時須標註 © OpenStreetMap contributors —— 畫面上有標
   若未來用量變大，官方建議自架 Nominatim 或改用商業服務。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# 必須能識別這個應用程式。請勿改成通用字串，那會被 Nominatim 限流或封鎖。
USER_AGENT = (
    "BusinessTripHotelFilter/0.1 "
    "(personal business-travel tool; contact via github.com/natsunari/test0000)"
)

VENUES_PATH = Path(__file__).parent / "venues.json"

# 遵守每秒 1 次的限制
_MIN_INTERVAL_SECONDS = 1.1
_last_request_at = 0.0

# 「35.6298, 139.7954」「35.6298 139.7954」「35.6298,139.7954」都接受
_COORD_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)

# 度分秒格式：35°37'58"N 139°52'50"E
# Google Maps 有時候會用這種寫法顯示座標，使用者直接複製就會是這樣。
_DMS_RE = re.compile(
    r"""^\s*
    (\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*["″]?\s*([NSns])
    \s*[,\s]\s*
    (\d{1,3})\s*[°d]\s*(\d{1,2})\s*['′]\s*([\d.]+)\s*["″]?\s*([EWew])
    \s*$""",
    re.VERBOSE,
)


# Google Maps 連結裡的座標有好幾種寫法，這些是常見的：
#   .../@25.0339,121.5645,17z/...        地圖中心
#   ...!3d25.0339!4d121.5645...          地點本身（比地圖中心準）
#   ...?q=25.0339,121.5645               查詢參數
_MAPS_PATTERNS = [
    re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)"),
    re.compile(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)"),
    re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)"),
]

# 樓層、室號 —— OSM 不會有這層資訊，查詢時是純粹的干擾
_FLOOR_RE = re.compile(r"\s*\d+\s*(?:樓之\d+|樓|F|f|樓層|室|房)\s*$")
# 村里鄰 —— 台灣地址的行政區劃，OSM 幾乎沒有收錄。
# 只拿掉「緊接在區/鄉/鎮/市後面」的里名，而且後面不能再接區/鄉/鎮，
# 否則「新北市萬里區」的「萬里」會被誤刪。
_VILLAGE_RE = re.compile(
    r"(?<=[區鄉鎮市])[\u4e00-\u9fff]{1,3}[里鄰](?![區鄉鎮市])"
)


def coordinates_from_maps_url(text: str) -> tuple[float, float] | None:
    """從 Google Maps 連結裡抓座標。抓不到回傳 None。"""
    if "google." not in text and "goo.gl" not in text:
        return None
    for pattern in _MAPS_PATTERNS:
        m = pattern.search(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


def query_variants(text: str) -> list[str]:
    """
    產生由精確到寬鬆的查詢候選，最多 3 個。

    中文地址對 Nominatim 有三個難點，這裡逐一拆掉：
      1. 樓層（89樓）—— OSM 沒有這層資訊
      2. 村里（西村里）—— 行政區劃，OSM 幾乎沒收錄
      3. 臺 / 台 用字不一致

    最多只試 3 次，而且每次間隔 1 秒以上。這是使用者按一次按鈕的動作，
    不是 Nominatim 政策所禁止的批次查詢。
    """
    variants = [text]

    simplified = _FLOOR_RE.sub("", text).strip()
    simplified = simplified.replace("臺", "台")
    if simplified and simplified not in variants:
        variants.append(simplified)

    without_village = _VILLAGE_RE.sub("", simplified).strip()
    if without_village and without_village not in variants:
        variants.append(without_village)

    return variants[:3]


class NotFound(LookupError):
    """查詢成功送達，但對方說沒有這個地點。換個寫法再試可能有用。"""


class ServiceError(LookupError):
    """根本沒問到 —— 連不上、被拒絕、被限流、或對方出錯。

    這跟「查無此地」是完全不同的事，不可以混為一談：
    把連線失敗說成「找不到台北101」會讓人以為是自己打錯字，
    然後一直換寫法重試，卻永遠不會成功。
    """


@dataclass
class Place:
    latitude: float
    longitude: float
    label: str                      # 顯示給使用者確認用
    source: str                     # "座標輸入" / "已存地點" / "OpenStreetMap"
    country_code: str | None = None  # 'jp'、'sg'…，用來決定當地貨幣
    # 查飯店時要送給 Google 的地名。
    # 不能直接用使用者輸入的字 —— 座標 Google 看不懂，會回傳完全無關的地區。
    area: str | None = None


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """
    看看輸入是不是一組座標。是就回傳 (緯度, 經度)，不是就回傳 None。
    緯度必須在 -90~90、經度 -180~180，否則視為不是座標。
    """
    text = text or ""
    dms = _DMS_RE.match(text)
    if dms:
        d1, m1, s1, ns, d2, m2, s2, ew = dms.groups()
        lat = int(d1) + int(m1) / 60 + float(s1) / 3600
        lon = int(d2) + int(m2) / 60 + float(s2) / 3600
        if ns.upper() == "S":
            lat = -lat
        if ew.upper() == "W":
            lon = -lon
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return round(lat, 6), round(lon, 6)
        return None

    m = _COORD_RE.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _area_from_address(address: dict | None) -> str | None:
    """
    把 Nominatim 的地址細節組成「城市, 國家」這種適合查飯店的字串。

    為什麼不用完整地址：Google Hotels 吃的是地區，給它門牌號碼反而查不好。
    為什麼不用使用者輸入：那可能是座標，Google 看不懂就會回傳無關地區的結果。
    """
    if not address:
        return None
    city = next((address[k] for k in
                 ("city", "town", "village", "municipality", "suburb", "county")
                 if address.get(k)), None)
    country = address.get("country")
    parts = [p for p in (city, country) if p]
    return ", ".join(parts) if parts else None


def reverse_lookup(lat: float, lon: float) -> tuple[str | None, str | None]:
    """
    用座標反查地名與國碼。回傳 (地名, 國碼)，查不到就都是 None。

    使用者貼座標時一定要做這一步，否則查飯店會拿座標字串去問 Google，
    而 Google 看不懂座標，會回傳完全無關地區的飯店。
    """
    _throttle()
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json",
                    "addressdetails": 1, "zoom": 12},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        if res.status_code != 200:
            return None, None
        data = res.json()
    except (requests.RequestException, ValueError):
        return None, None
    address = data.get("address") or {}
    return _area_from_address(address), address.get("country_code")


def load_venues(path: Path | None = None) -> dict:
    """讀取已存過的地點。檔案不存在或壞掉都回傳空的，不讓程式掛掉。"""
    p = path or VENUES_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_venue(key: str, place: Place, path: Path | None = None) -> None:
    """把確認過的地點存起來，下次同一個展館就不用再查。"""
    p = path or VENUES_PATH
    venues = load_venues(p)
    venues[key.strip().lower()] = {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "label": place.label,
        "country_code": place.country_code,
        "area": place.area,
    }
    p.write_text(json.dumps(venues, ensure_ascii=False, indent=2), encoding="utf-8")


def _throttle() -> None:
    """確保距離上次請求至少間隔 1.1 秒，遵守 Nominatim 的每秒 1 次限制。"""
    global _last_request_at
    wait = _MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def resolve(text: str, *, allow_network: bool = True,
            venues_path: Path | None = None) -> Place:
    """
    把使用者輸入的目的地轉成座標。

    順序：座標 → 已存地點 → 連網查詢。
    查不到會丟出 LookupError，呼叫端負責顯示友善訊息。
    """
    text = (text or "").strip()
    if not text:
        raise LookupError("請輸入目的地")

    # 1. 直接是座標（含度分秒格式），或 Google Maps 連結
    coords = parse_coordinates(text)
    source = "座標輸入"
    if not coords:
        coords = coordinates_from_maps_url(text)
        source = "Maps 連結"
    if coords:
        lat, lon = coords
        area, country = (reverse_lookup(lat, lon) if allow_network else (None, None))
        label = f"座標 {lat}, {lon}"
        if area:
            label += f"（{area}）"
        return Place(lat, lon, label, source, country, area)

    # 2. 查過並存起來的地點（也滿足 Nominatim「應快取」的要求）
    saved = load_venues(venues_path).get(text.lower())
    if saved:
        place = Place(saved["latitude"], saved["longitude"],
                      saved["label"], "已存地點", saved.get("country_code"),
                      saved.get("area"))
        # 舊版存的紀錄沒有國碼與地名（當時還沒有這些功能）。
        # 缺了就反查一次補上，否則當地貨幣顯示不出來、查飯店也會用錯字串。
        if (place.country_code and place.area) or not allow_network:
            return place
        area, country = reverse_lookup(place.latitude, place.longitude)
        if area or country:
            place.area = place.area or area
            place.country_code = place.country_code or country
            save_venue(text, place, venues_path)
        return place

    if not allow_network:
        raise LookupError(f"「{text}」不在已存地點裡，而目前是離線模式")

    # 3. 問 Nominatim。中文地址常常要簡化過才查得到，所以依序試幾個版本。
    attempts = query_variants(text)
    for candidate in attempts:
        try:
            return _query_nominatim(candidate)
        except NotFound:
            continue        # 這個寫法查不到，換下一個簡化版本
        except ServiceError:
            raise           # 根本沒問到，換寫法也沒用，立刻把真正原因回報出去
    raise NotFound(
        f"找不到「{text}」，也試過簡化版本（{'、'.join(attempts[1:]) or '無'}）。\n\n"
        f"中文地址常常查不到，最可靠的做法是直接給座標：\n"
        f"　1. 在 Google Maps 上找到那個地點\n"
        f"　2. 對著它按右鍵，選單最上面那行就是座標\n"
        f"　3. 點一下複製，貼進這個欄位\n"
        f"（也可以直接貼 Google Maps 的網址）"
    )


def _query_nominatim(text: str) -> Place:
    """實際向 Nominatim 查詢。查不到會丟出 LookupError。"""
    _throttle()
    try:
        res = requests.get(
            NOMINATIM_URL,
            params={"q": text, "format": "json", "limit": 1,
                    "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
    except requests.Timeout as exc:
        raise ServiceError(
            "OpenStreetMap 在 20 秒內沒有回應。可能是網路太慢，或對方忙碌。"
        ) from exc
    except requests.RequestException as exc:
        raise ServiceError(
            f"連不上 OpenStreetMap：{exc}\n"
            f"如果你在公司或學校網路，可能是防火牆擋住了 "
            f"nominatim.openstreetmap.org。"
        ) from exc

    if res.status_code == 403:
        raise ServiceError(
            "OpenStreetMap 拒絕了這次查詢（403）。"
            "通常是 User-Agent 的問題，請見 geocode.py 開頭的政策說明。"
        )
    if res.status_code == 429:
        raise ServiceError(
            "查詢太頻繁，被 OpenStreetMap 限流（429）。等個十幾秒再試一次。"
        )
    if res.status_code != 200:
        raise ServiceError(
            f"OpenStreetMap 回應異常（HTTP {res.status_code}）。"
            f"通常是對方暫時出問題，稍後再試。"
        )

    try:
        results = res.json()
    except ValueError as exc:
        raise ServiceError("OpenStreetMap 回傳的內容無法解析。") from exc
    if not results:
        raise NotFound(f"OpenStreetMap 裡找不到「{text}」")

    top = results[0]
    address = top.get("address") or {}
    return Place(float(top["lat"]), float(top["lon"]),
                 top.get("display_name", text), "OpenStreetMap",
                 address.get("country_code"), _area_from_address(address))
