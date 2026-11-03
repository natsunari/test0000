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

# 已存地點的格式版本。解析邏輯改動（例如開始排除日常店家）之後要加一，
# 舊的紀錄才會自動重查 —— 否則一個錯誤的地標會永遠卡在使用者的檔案裡。
#   2 → 3：住宿不再當地標（存過的座標可能記著某間飯店的名字）
VENUE_SCHEMA = 3

# 遵守每秒 1 次的限制
_MIN_INTERVAL_SECONDS = 1.1
_last_request_at = 0.0

# 座標輸入一律先正規化再比對。
# 中文輸入法打出來的是全形逗號、全形句點、全形空白，長得像半形但不是同一個字元。
# 使用者看不出差別，程式卻會整串比對失敗，然後把座標當成地名送出去查。
_NORMALISE = str.maketrans({
    "，": ",", "、": ",", "　": " ", "．": ".", "：": ":",
    "－": "-", "—": "-", "–": "-", "−": "-", "ー": "-",
    "’": "'", "＇": "'", "′": "'", "”": '"', "＂": '"', "″": '"',
    "º": "°", "˚": "°", "∘": "°", "Ｎ": "N", "Ｓ": "S", "Ｅ": "E", "Ｗ": "W",
})


def _angle(index: int, letters: str) -> str:
    """一個角度的比對式。度是必要的，分、秒、半球字母都可有可無。"""
    return (
        rf"(?:(?P<h{index}a>[{letters}])\s*)?"      # 半球字母放前面：N35...
        rf"(?P<sign{index}>-)?"                     # 或者用負號
        rf"(?P<deg{index}>\d{{1,3}}(?:\.\d+)?)\s*[°d]?\s*"
        rf"(?:(?P<min{index}>\d{{1,2}}(?:\.\d+)?)\s*['`]\s*"   # 分，可以是小數
        rf"""(?:(?P<sec{index}>\d{{1,2}}(?:\.\d+)?)\s*["]?\s*)?"""  # 秒可省略
        rf")?"
        rf"(?P<h{index}b>[{letters}])?"             # 半球字母放後面：35...N
    )


# 一條式子涵蓋所有寫法，避免每多一種格式就多一條規則、又漏掉其中一種：
#   25.0339, 121.5645          十進位
#   33.87230°S 151.19896°E     十進位＋半球字母
#   N35°37'58" E139°52'50"     度分秒，字母在前
#   35°37'58"N 139°52'50"E     度分秒，字母在後
#   35°37.95'N 139°52.83'E     度＋十進位分
#   35°37'N 139°52'E           度分，沒有秒
_ANGLE_RE = re.compile(
    rf"^\s*{_angle(1, 'NSns')}\s*[,\s]\s*{_angle(2, 'EWew')}\s*$",
    re.VERBOSE,
)


# 短網址裡沒有座標，要連去 Google 展開才看得到。程式不做這件事，
# 但至少要認出來並告訴使用者怎麼拿到完整網址 ——
# 丟去 Nominatim 查只會得到一句「找不到這個地點」，使用者會以為是地點的問題。
_SHORT_MAPS_RE = re.compile(
    r"^https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|g\.co/kgs)/", re.I)

# Plus Code（例如 4RRH46H2+X2）。Google Maps 會顯示這種碼，
# 但要解碼需要另一套演算法，這裡只認出來並給替代做法。
_PLUS_CODE_RE = re.compile(r"^\s*[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,7}\s*$", re.I)


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
    # 「城市, 國家」，查飯店的最後退路
    area: str | None = None
    # 這個地點本身的名字（Taipei 101、Tokyo Big Sight…）。
    # 查飯店時優先用它 —— 不論使用者輸入的是名稱、地址還是座標，
    # 都要先解析成同一個地標，才會找到同一批附近的飯店。
    landmark: str | None = None


def _one_angle(sign, deg, minute, sec, h_before, h_after,
               negative: str) -> float | None:
    """把一個角度的各個部分合成十進位度數。無法判斷正負就回傳 None。"""
    letter = h_before or h_after
    if letter and sign:
        return None        # 同時寫了 -33 和 S，意思互相矛盾，不猜
    if h_before and h_after:
        return None        # N35N，不是正常寫法
    value = float(deg)
    if minute is not None:
        value += float(minute) / 60
    if sec is not None:
        value += float(sec) / 3600
    if sign or (letter and letter.upper() == negative):
        value = -value
    return value


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """
    看看輸入是不是一組座標。是就回傳 (緯度, 經度)，不是就回傳 None。

    接受十進位、十進位加半球字母、度分秒、度分、度加十進位分，
    半球字母放前面或後面都可以，全形標點會先換成半形。

    緯度必須在 -90~90、經度 -180~180，否則視為不是座標 ——
    判斷錯誤的代價很高：座標字串會被當成地名送去查，結果可能差上萬公里。
    """
    text = (text or "").translate(_NORMALISE).strip()
    m = _ANGLE_RE.match(text)
    if not m:
        return None
    g = m.groupdict()
    lat = _one_angle(g["sign1"], g["deg1"], g["min1"], g["sec1"],
                     g["h1a"], g["h1b"], "S")
    lon = _one_angle(g["sign2"], g["deg2"], g["min2"], g["sec2"],
                     g["h2a"], g["h2b"], "W")
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 6), round(lon, 6)


def _area_from_address(address: dict | None) -> str | None:
    """
    把 Nominatim 的地址細節組成適合查飯店的地區字串。

    盡量帶上「區」這一層，不要只給城市 ——
    Google Hotels 一次只回二十筆左右，查「Koto, Japan」會散在整個江東區，
    查「Ariake, Koto, Japan」才會集中在展館周圍。
    實測 13 個展館時，座標那一欄有一半退到城市層級就是這個問題。

    為什麼不用完整地址：Google 吃的是地區，給它門牌號碼反而查不好。
    為什麼不用使用者輸入：那可能是座標，Google 看不懂就會跑到別的地區。
    """
    if not address:
        return None
    local = next((address[k] for k in
                  ("suburb", "neighbourhood", "quarter", "city_district",
                   "borough", "city_block")
                  if address.get(k)), None)
    city = next((address[k] for k in
                 ("city", "town", "village", "municipality", "county")
                 if address.get(k)), None)
    country = address.get("country")

    parts: list[str] = []
    for value in (local, city, country):
        if not value:
            continue
        # 區名和市名有時候一樣（例如新加坡），不要重複
        if any(value.strip().lower() == seen.strip().lower() for seen in parts):
            continue
        parts.append(value)
    return ", ".join(parts) if parts else None


# 判斷「這是不是地標」。
#
# 原本是逐一列舉不要的 type，結果變成打地鼠 —— 紐倫堡展場的座標
# 解析出 "ORTOG"（場內的一家公司），因為那個 type 不在清單上。
# 改成用 OSM 的 class 判斷，範圍才收得住。
#
# class 是大分類（amenity / shop / office / tourism / place …），
# type 是細分類（restaurant / exhibition_centre / village …）。
_LANDMARK_CLASSES = {
    "tourism",      # 景點、飯店、展覽館
    "leisure",      # 公園、體育場、會議中心
    "historic",     # 古蹟
    "building",     # 有名字的建築物
    "aeroway",      # 機場
    "railway",      # 車站
    "amenity",      # 展覽中心、大學、醫院…（底下再用 type 過濾日常店家）
}

# 住宿本身永遠不能當地標。
#
# 為什麼：反查座標時，Nominatim 回的是「離這個點最近的有名字的東西」。
# 市中心的座標常常就落在某間飯店上 —— 例如雪梨 Darling Harbour 的座標
# 反查回來是「Sofitel Sydney Darling Harbour」。拿一間特定飯店的名字去問
# Google Hotels「這附近有哪些飯店」，回來是 0 筆，整頁空白。
#
# 擋掉之後會退回「城市, 國家」。查詢範圍是變大了，但距離仍然是拿
# 使用者給的座標逐間實算，真正在篩的是交通費上限，不是這個查詢字串。
_ACCOMMODATION_TYPES = {
    "hotel", "motel", "hostel", "guest_house", "guesthouse",
    "apartment", "apartments", "chalet", "resort",
    "alpine_hut", "wilderness_hut", "bed_and_breakfast",
    "love_hotel", "capsule_hotel", "holiday_cottage",
    "camp_site", "caravan_site", "camp_pitch",
}

# class=amenity 底下仍然有大量日常店家，要再篩一層
_NOT_A_LANDMARK = _ACCOMMODATION_TYPES | {
    "restaurant", "cafe", "fast_food", "bar", "pub", "bakery", "ice_cream",
    "food_court", "biergarten",
    "bank", "atm", "pharmacy", "clinic", "dentist", "doctors", "veterinary",
    "hairdresser", "beauty", "laundry", "car_repair", "fuel", "car_wash",
    "convenience", "supermarket", "kiosk", "newsagent", "florist",
    "clothes", "shoes", "mobile_phone", "optician", "jewelry",
    "post_office", "police", "fire_station",
    "parking", "toilets", "bench", "waste_basket", "vending_machine",
    "bicycle_parking", "charging_station", "shelter", "drinking_water",
}


def _poi_name(data: dict, address: dict | None) -> str | None:
    """
    從 Nominatim 的回應取出「這個地點本身的名字」。

    正向查詢（文字→座標）與反向查詢（座標→地名）都用這個，
    這樣不論使用者輸入名稱、地址還是座標，都會解析到同一個地標。

    但要擋掉日常店家 —— 查一個街道地址時，Nominatim 常常回傳
    那棟樓裡的某家餐廳或商店，那不是地標，拿去查飯店會跑到別的城市。
    """
    category = str(data.get("class") or "").strip().lower()
    kind = str(data.get("type") or "").strip().lower()
    # class 不在允許清單就不是地標（shop、office、place、highway…）
    if category and category not in _LANDMARK_CLASSES:
        return None
    if kind in _NOT_A_LANDMARK:
        return None

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    for key in ("tourism", "attraction", "building", "amenity",
                "leisure", "historic"):
        value = (address or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def reverse_lookup(lat: float, lon: float
                   ) -> tuple[str | None, str | None, str | None]:
    """
    用座標反查。回傳 (地標名稱, 城市國家, 國碼)，查不到的就是 None。

    地名優先取「這個地點本身的名字」（例如 Taipei 101、Tokyo Big Sight），
    取不到才退成「城市, 國家」。因為 Google Hotels 用地標搜尋會把結果
    集中在附近，用城市搜尋則會散到整座城市，而它只回二十筆左右。

    使用者貼座標時一定要做這一步，否則查飯店會拿座標字串去問 Google，
    而 Google 看不懂座標，會回傳完全無關地區的飯店。
    """
    _throttle()
    try:
        res = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json",
                    # zoom=18 是建築物層級。用 12（城市層級）的話
                    # 反查永遠拿不到地標，只會回傳城市名。
                    "addressdetails": 1, "zoom": 18,
                    "accept-language": "en"},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        if res.status_code != 200:
            return None, None, None
        data = res.json()
    except (requests.RequestException, ValueError):
        return None, None, None
    address = data.get("address") or {}
    return (_poi_name(data, address), _area_from_address(address),
            address.get("country_code"))


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
        "landmark": place.landmark,
        "v": VENUE_SCHEMA,
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
            venues_path: Path | None = None,
            refresh: bool = False) -> Place:
    """
    把使用者輸入的目的地轉成座標。

    順序：座標 → 已存地點 → 連網查詢。
    查不到會丟出 LookupError，呼叫端負責顯示友善訊息。

    refresh=True 時跳過已存地點直接重查。畫面上的「強制重查」要連
    目的地一起重新解析 —— 否則使用者看到的還是上次那筆（可能是錯的）
    解析結果，而「強制」兩個字就名不副實了。
    """
    text = (text or "").strip()
    if not text:
        raise LookupError("請輸入目的地")

    if _SHORT_MAPS_RE.match(text):
        raise NotFound(
            "這是 Google Maps 的短網址，裡面看不到座標。"
            "請在瀏覽器打開它，等網址列變成完整網址之後再複製一次，"
            "或直接貼座標（在地圖上按右鍵就能複製）。")
    if _PLUS_CODE_RE.match(text):
        raise NotFound(
            "這是 Plus Code，程式沒辦法把它換成座標。"
            "請改貼座標，或填展館的英文名稱。")

    # 1. 直接是座標（含度分秒格式），或 Google Maps 連結
    coords = parse_coordinates(text)
    source = "座標輸入"
    if not coords:
        coords = coordinates_from_maps_url(text)
        source = "Maps 連結"
    if coords:
        lat, lon = coords
        landmark, area, country = (reverse_lookup(lat, lon) if allow_network
                                   else (None, None, None))
        label = f"座標 {lat}, {lon}"
        if landmark or area:
            label += f"（{landmark or area}）"
        return Place(lat, lon, label, source, country, area, landmark)

    # 2. 查過並存起來的地點（也滿足 Nominatim「應快取」的要求）
    saved = None if (refresh and allow_network) else \
        load_venues(venues_path).get(text.lower())
    if saved:
        place = Place(saved["latitude"], saved["longitude"],
                      saved["label"], "已存地點", saved.get("country_code"),
                      saved.get("area"), saved.get("landmark"))

        # 舊格式的紀錄要整筆重查。解析規則改過（例如開始排除餐廳、商店），
        # 但存檔裡那個錯誤的地標不會自己消失。
        if saved.get("v") != VENUE_SCHEMA and allow_network:
            try:
                fresh = _query_nominatim(text)
            except LookupError:
                return place        # 重查失敗就照舊用，不要讓搜尋整個失敗
            save_venue(text, fresh, venues_path)
            fresh.source = "已存地點（已更新）"
            return fresh

        # 格式夠新但缺國碼或地名時，反查補上即可
        if (place.country_code and place.area) or not allow_network:
            return place
        landmark, area, country = reverse_lookup(place.latitude, place.longitude)
        if landmark or area or country:
            place.landmark = place.landmark or landmark
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
            place = _query_nominatim(candidate)
            if refresh:
                save_venue(text, place, venues_path)   # 覆蓋掉舊的
                place.source = "OpenStreetMap（已重查）"
            return place
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
                    "addressdetails": 1, "accept-language": "en"},
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
    landmark = _poi_name(top, address)
    label = top.get("display_name", text)

    # Nominatim 的 display_name 會把那個地址上的店家放在最前面。
    # 既然我們已經判定它不是地標，畫面上也不該讓它當開頭 ——
    # 「Harajuku Gyoza, 14, Darling Drive…」看起來就像解析錯了。
    rejected = top.get("name")
    if not landmark and rejected and label.startswith(f"{rejected}, "):
        label = label[len(rejected) + 2:]

    return Place(float(top["lat"]), float(top["lon"]), label, "OpenStreetMap",
                 address.get("country_code"), _area_from_address(address),
                 landmark)
