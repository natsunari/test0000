"""
目的地解析的測試。

執行方式：
    python test_geocode.py

完全不連網 —— 只測「座標辨識」和「已存地點」這兩條路徑，
連網查詢那條由你實際使用時驗證。
"""

import json
import tempfile
from pathlib import Path

import geocode

passed = 0


def _swallow(fn):
    """執行並吞掉預期中的例外，用來測「呼叫了幾次」。"""
    try:
        return fn()
    except BaseException:
        return None


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


print("\n--- 座標辨識 ---")
for text, expect in [
    ("35.6298, 139.7954", (35.6298, 139.7954)),
    ("35.6298,139.7954", (35.6298, 139.7954)),
    ("35.6298 139.7954", (35.6298, 139.7954)),
    ("  35.6298 , 139.7954  ", (35.6298, 139.7954)),
    ("-33.8688, 151.2093", (-33.8688, 151.2093)),
    ("35, 139", (35.0, 139.0)),
]:
    check(geocode.parse_coordinates(text) == expect, f"「{text}」辨識為座標 {expect}")

print("\n--- 度分秒格式（Google Maps 複製出來常常是這種）---")
for text, lat, lon in [
    ("""35°37'58"N 139°52'50"E""", 35.6328, 139.8806),   # 東京迪士尼
    ("""25°02'02.0"N 121°33'53.0"E""", 25.0339, 121.5647),  # 台北 101
    ("""33°52'08"S 151°12'33"E""", -33.8689, 151.2092),  # 雪梨歌劇院（南半球、東經）
]:
    got = geocode.parse_coordinates(text)
    ok = got and abs(got[0] - lat) < 0.01 and abs(got[1] - lon) < 0.01
    check(ok, f"「{text}」→ {got}，約等於 ({lat}, {lon})")
check(geocode.parse_coordinates("""91°00'00"N 0°00'00"E""") is None,
      "度分秒超出範圍也會被擋下")

print("\n--- 不是座標的輸入 ---")
for text in [
    "Tokyo Big Sight",
    "東京国際展示場",
    "江東区有明3-11-1",
    "",
    "35.6298",
    "abc, def",
]:
    check(geocode.parse_coordinates(text) is None, f"「{text}」不會被誤判為座標")

print("\n--- 超出範圍的數字不算座標 ---")
check(geocode.parse_coordinates("91, 139") is None, "緯度 91 超過 90 → 不是座標")
check(geocode.parse_coordinates("35, 181") is None, "經度 181 超過 180 → 不是座標")
check(geocode.parse_coordinates("-91, 0") is None, "緯度 -91 → 不是座標")

print("\n--- 輸入座標時不連網 ---")
place = geocode.resolve("35.6298, 139.7954", allow_network=False)
check(place.latitude == 35.6298 and place.longitude == 139.7954, "座標原封不動帶過去")
check(place.source == "座標輸入", "來源標示為座標輸入")

print("\n--- 由地址細節組出查飯店用的地名 ---")
check(geocode._area_from_address(
    {"city": "浦安市", "state": "千葉県", "country": "日本",
     "road": "Parade Route", "postcode": "279-8505"}) == "浦安市, 日本",
    "取城市與國家，捨棄門牌與郵遞區號（Google Hotels 吃的是地區）")
check(geocode._area_from_address(
    {"town": "Urayasu", "country": "Japan"}) == "Urayasu, Japan",
    "沒有 city 時退而用 town")
check(geocode._area_from_address({"country": "Japan"}) == "Japan",
      "只有國家也能用")
check(geocode._area_from_address({}) is None, "完全沒有資料時回傳 None")
check(geocode._area_from_address(None) is None, "address 是 None 也不會當掉")

print("\n--- ⚠️ 貼座標時一定要反查地名 ---")
# 這是實際踩過的 bug：貼東京迪士尼的座標，查飯店卻回傳美國的露營地，
# 因為 Google Hotels 收到的是座標字串而不是地名。
reverse_payload = {"address": {"city": "浦安市", "country": "日本",
                               "country_code": "jp"}}


class ReverseResponse:
    status_code = 200
    @staticmethod
    def json():
        return reverse_payload


original_get = geocode.requests.get
geocode._last_request_at = 0.0
geocode.requests.get = lambda *a, **k: ReverseResponse()
try:
    place = geocode.resolve("""35°37'58"N 139°52'50"E""",
                            venues_path=Path(tempfile.gettempdir()) / "nope.json")
    check(place.area == "浦安市, 日本",
          f"座標會反查成地名「{place.area}」，查飯店時才不會送座標字串給 Google")
    check(place.country_code == "jp", "同時取得國碼，當地貨幣才顯示得出來")
    check("浦安市" in place.label, "畫面上的目的地也會顯示反查到的地名")
finally:
    geocode.requests.get = original_get

print("\n--- 用 OSM 的 class 判斷是不是地標 ---")
# 原本逐一列舉不要的 type，變成打地鼠 —— 紐倫堡展場的座標解析出
# "ORTOG"（場內的一家公司），因為那個 type 不在清單上。
# 改成先看 class，範圍才收得住。
for data, expected, label in [
    ({"name": "ORTOG", "class": "office", "type": "company"}, None, "展場裡的公司"),
    ({"name": "Some Shop", "class": "shop", "type": "convenience"}, None, "商店"),
    ({"name": "Winchester", "class": "place", "type": "town"}, None, "城鎮"),
    ({"name": "Sanchong", "class": "place", "type": "village"}, None, "行政區劃"),
    ({"name": "A Road", "class": "highway", "type": "primary"}, None, "道路"),
    ({"name": "Tokyo Big Sight", "class": "amenity",
      "type": "exhibition_centre"}, "Tokyo Big Sight", "展覽館"),
    ({"name": "ICC Sydney", "class": "leisure",
      "type": "convention_centre"}, "ICC Sydney", "會議中心"),
    ({"name": "Moscone Center", "class": "building", "type": "yes"},
     "Moscone Center", "有名字的建築"),
    ({"name": "Taipei 101", "class": "tourism", "type": "attraction"},
     "Taipei 101", "觀光地標"),
]:
    got = geocode._poi_name(data, {})
    check(got == expected, f"{label}（class={data['class']}）→ {got}")

print("\n--- 反查要用建築物層級 ---")
# zoom=12 是城市層級，反查永遠拿不到地標，只會回傳城市名。
# 實測 13 個展館，座標那一欄全部顯示「（無地標）」就是這個原因。
import inspect
src = inspect.getsource(geocode.reverse_lookup)
check('"zoom": 18' in src, "反查使用 zoom=18（建築物層級）")

print("\n--- 地址上的店家不是地標 ---")
# 實際踩過：查「14 Darling Dr, Sydney」解析出 "Harajuku Gyoza"（一家餃子店），
# 拿去查飯店時 Google 看到 Harajuku 就跑去搜東京原宿，結果在 18939 公里外。
for data, address, expected, label in [
    ({"name": "Harajuku Gyoza", "class": "amenity", "type": "restaurant"},
     {}, None, "餐廳"),
    ({"name": "Starbucks", "class": "amenity", "type": "cafe"}, {}, None, "咖啡店"),
    ({"name": "7-Eleven", "class": "shop", "type": "convenience"},
     {}, None, "便利商店"),
    ({"name": "ANZ", "class": "amenity", "type": "bank"}, {}, None, "銀行"),
    ({"name": "Taipei 101", "class": "tourism", "type": "attraction"},
     {}, "Taipei 101", "觀光地標"),
    ({"name": "Tokyo Big Sight", "class": "amenity",
      "type": "exhibition_centre"}, {}, "Tokyo Big Sight", "展覽館"),
    ({"name": "Sofitel Sydney", "class": "tourism", "type": "hotel"},
     {}, "Sofitel Sydney", "飯店"),
    ({}, {"building": "International Convention Centre"},
     "International Convention Centre", "只有 building 欄位"),
]:
    got = geocode._poi_name(data, address)
    check(got == expected, f"{label} → {got}")

print("\n--- 舊格式的已存地點要整筆重查 ---")
# 解析規則改過之後，使用者檔案裡那個錯誤的地標不會自己消失
with tempfile.TemporaryDirectory() as tmp:
    venues = Path(tmp) / "venues.json"
    venues.write_text(json.dumps({
        "14 darling dr, sydney nsw 2000": {
            "latitude": -33.874, "longitude": 151.201,
            "label": "Harajuku Gyoza, 14, Darling Drive, Sydney",
            "landmark": "Harajuku Gyoza", "area": "Sydney, Australia",
            "country_code": "au",
        }   # 注意：沒有 "v" 欄位，代表是舊格式
    }, ensure_ascii=False), encoding="utf-8")

    class FreshLookup:
        status_code = 200
        @staticmethod
        def json():
            return [{"lat": "-33.874", "lon": "151.201",
                     "display_name": "14, Darling Drive, Haymarket, Sydney",
                     "type": "house",
                     "address": {"city": "Sydney", "country": "Australia",
                                 "country_code": "au"}}]

    _orig = geocode.requests.get
    geocode._last_request_at = 0.0
    geocode.requests.get = lambda *a, **k: FreshLookup()
    try:
        place = geocode.resolve("14 Darling Dr, Sydney NSW 2000",
                                venues_path=venues)
        check(place.landmark is None,
              "重查後不再帶著錯誤的地標「Harajuku Gyoza」")
        check(place.area == "Sydney, Australia", "城市與國家仍然正確")
        check("更新" in place.source, f"來源標示為「{place.source}」")
        saved = json.loads(venues.read_text(encoding="utf-8"))
        entry = saved["14 darling dr, sydney nsw 2000"]
        check(entry.get("v") == geocode.VENUE_SCHEMA, "存檔已升級成新格式")
        check(entry.get("landmark") is None, "存檔裡的錯誤地標也清掉了")
    finally:
        geocode.requests.get = _orig

print("\n--- 強制重查要跳過已存地點 ---")
with tempfile.TemporaryDirectory() as tmp:
    venues = Path(tmp) / "venues.json"
    venues.write_text(json.dumps({
        "14 darling dr, sydney nsw 2000": {
            "latitude": -33.874, "longitude": 151.201,
            "label": "舊的（錯的）解析結果",
            "landmark": "Harajuku Gyoza", "area": "Sydney, Australia",
            "country_code": "au", "v": geocode.VENUE_SCHEMA,
        }
    }, ensure_ascii=False), encoding="utf-8")

    class FreshLookup:
        status_code = 200
        @staticmethod
        def json():
            return [{"lat": "-33.8745", "lon": "151.2015",
                     "display_name": "Harajuku Gyoza, 14, Darling Drive, "
                                     "Haymarket, Sydney, Australia",
                     "name": "Harajuku Gyoza", "type": "restaurant",
                     "address": {"city": "Sydney", "country": "Australia",
                                 "country_code": "au"}}]

    _orig = geocode.requests.get
    geocode._last_request_at = 0.0
    geocode.requests.get = lambda *a, **k: FreshLookup()
    try:
        # 不加 refresh：讀存檔，拿到舊的（錯的）結果
        stale = geocode.resolve("14 Darling Dr, Sydney NSW 2000", venues_path=venues)
        check(stale.landmark == "Harajuku Gyoza" and stale.source == "已存地點",
              "一般搜尋會沿用已存地點（這是刻意的，省下對方的負擔）")

        # 加 refresh：跳過存檔重查
        fresh = geocode.resolve("14 Darling Dr, Sydney NSW 2000",
                                venues_path=venues, refresh=True)
        check("重查" in fresh.source, f"強制重查時來源標示為「{fresh.source}」")
        check(fresh.landmark is None,
              "重查後餐廳不再被當成地標")
        check(not fresh.label.startswith("Harajuku Gyoza"),
              f"顯示文字也不再以店名開頭 →「{fresh.label[:40]}」")
        check(fresh.label.startswith("14, Darling Drive"),
              "開頭改成真正的地址")
        saved = json.loads(venues.read_text(encoding="utf-8"))
        check(saved["14 darling dr, sydney nsw 2000"]["landmark"] is None,
              "重查的結果會覆蓋掉存檔裡的舊值")
    finally:
        geocode.requests.get = _orig

print("\n--- 反查要優先取地標名稱，而不是城市 ---")
# 查飯店時「Taipei 101」比「台北市, 台灣」好用 ——
# Google 會把結果集中在地標附近，用城市搜則散到整座城市。
class NamedReverse:
    status_code = 200
    payload = {"name": "Taipei 101",
               "address": {"city": "臺北市", "country": "臺灣",
                           "country_code": "tw"}}
    @classmethod
    def json(cls):
        return cls.payload


_orig = geocode.requests.get
geocode._last_request_at = 0.0
geocode.requests.get = lambda *a, **k: NamedReverse()
try:
    landmark, area, country = geocode.reverse_lookup(25.0339, 121.5645)
    check(landmark == "Taipei 101", f"取到地標名稱「{landmark}」")
    check(area == "臺北市, 臺灣", f"城市與國家另外保留為「{area}」")
    check(country == "tw", "國碼照樣取得")

    # 沒有 name 欄位時，從 address 裡的 tourism/building 等欄位找
    NamedReverse.payload = {"address": {"tourism": "Tokyo Big Sight",
                                        "city": "Koto", "country": "Japan",
                                        "country_code": "jp"}}
    landmark, area, country = geocode.reverse_lookup(35.63, 139.79)
    check(landmark == "Tokyo Big Sight", "沒有 name 時從 address 的 tourism 取")

    # 兩邊都沒有地標資訊時，landmark 是 None，只剩城市
    NamedReverse.payload = {"address": {"city": "Urayasu", "country": "Japan",
                                        "country_code": "jp"}}
    landmark, area, country = geocode.reverse_lookup(35.63, 139.88)
    check(landmark is None, "完全沒有地標資訊時為 None")
    check(area == "Urayasu, Japan", f"仍然取得城市「{area}」")
finally:
    geocode.requests.get = _orig
    NamedReverse.payload = {"name": "Taipei 101"}

print("\n--- 已存地點 ---")
with tempfile.TemporaryDirectory() as tmp:
    venues = Path(tmp) / "venues.json"

    saved = geocode.Place(35.6298, 139.7954, "Tokyo Big Sight, Koto, Tokyo", "OpenStreetMap")
    geocode.save_venue("Tokyo Big Sight", saved, venues)

    got = geocode.resolve("Tokyo Big Sight", allow_network=False, venues_path=venues)
    check(got.latitude == 35.6298, "存過的地點不連網就查得到")
    check(got.source == "已存地點", "來源標示為已存地點")

    got = geocode.resolve("tokyo big sight", allow_network=False, venues_path=venues)
    check(got.latitude == 35.6298, "大小寫不同也查得到")

    try:
        geocode.resolve("沒存過的地方", allow_network=False, venues_path=venues)
        check(False, "離線查未知地點應該要報錯")
    except LookupError as exc:
        check("離線" in str(exc), "離線查未知地點會給清楚的錯誤訊息")

    try:
        geocode.resolve("", allow_network=False, venues_path=venues)
        check(False, "空字串應該要報錯")
    except LookupError:
        check(True, "空字串會報錯而不是當掉")

print("\n--- 舊版存的地點缺國碼時的處理 ---")
with tempfile.TemporaryDirectory() as tmp:
    venues = Path(tmp) / "venues.json"
    # 模擬加入國碼功能之前存下的紀錄
    venues.write_text(json.dumps({
        "tokyo disneyland": {
            "latitude": 35.6329, "longitude": 139.8804,
            "label": "東京ディズニーランド, 浦安市, 千葉県, 日本",
        }
    }, ensure_ascii=False), encoding="utf-8")

    got = geocode.resolve("Tokyo Disneyland", allow_network=False, venues_path=venues)
    check(got.latitude == 35.6329, "舊紀錄仍然可用，座標正確")
    check(got.country_code is None, "離線時補不到國碼，但不會當掉")

    # 有國碼的新紀錄不該觸發重查
    geocode.save_venue("Big Sight",
                       geocode.Place(35.6298, 139.7954, "Tokyo Big Sight", "OpenStreetMap", "jp"),
                       venues)
    got = geocode.resolve("Big Sight", allow_network=False, venues_path=venues)
    check(got.country_code == "jp", "有國碼的紀錄直接回傳，不需要連網")
    check(got.source == "已存地點", "來源仍標示為已存地點")

print("\n--- 壞掉的 venues.json 不會讓程式掛掉 ---")
with tempfile.TemporaryDirectory() as tmp:
    broken = Path(tmp) / "venues.json"
    broken.write_text("這不是 JSON {{{", encoding="utf-8")
    check(geocode.load_venues(broken) == {}, "檔案壞掉時回傳空的，不丟例外")

print("\n--- 失敗原因必須說實話 ---")
# 用假的回應模擬各種狀況。重點是：連線問題不可以被說成「找不到」，
# 否則使用者會一直換寫法重試，而那永遠不會成功。
import requests as _requests


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = ""

    def json(self):
        return self._payload


def with_fake_get(fake, fn):
    original = geocode.requests.get
    geocode._last_request_at = 0.0      # 不要讓節流拖慢測試
    geocode.requests.get = fake
    try:
        return fn()
    finally:
        geocode.requests.get = original


def expect(fake, kind, description):
    def run():
        try:
            geocode.resolve("Taipei 101", venues_path=Path(tempfile.gettempdir()) / "nonexistent.json")
        except BaseException as exc:
            return exc
        return None
    error = with_fake_get(fake, run)
    check(isinstance(error, kind), f"{description}（實際：{type(error).__name__}）")
    return error


err = expect(lambda *a, **k: FakeResponse(403), geocode.ServiceError,
             "403 被拒 → ServiceError，不是「找不到」")
check("403" in str(err), f"訊息包含 403：{str(err)[:40]}…")

err = expect(lambda *a, **k: FakeResponse(429), geocode.ServiceError,
             "429 限流 → ServiceError")
check("限流" in str(err), "訊息說明是被限流，並建議等一下再試")

err = expect(lambda *a, **k: FakeResponse(503), geocode.ServiceError,
             "503 對方故障 → ServiceError")

def raise_timeout(*a, **k):
    raise _requests.Timeout()
err = expect(raise_timeout, geocode.ServiceError, "逾時 → ServiceError")
check("沒有回應" in str(err), "訊息說明是逾時")

def raise_conn(*a, **k):
    raise _requests.ConnectionError("getaddrinfo failed")
err = expect(raise_conn, geocode.ServiceError, "連不上 → ServiceError")
check("防火牆" in str(err), "訊息提醒可能是公司網路的防火牆")

err = expect(lambda *a, **k: FakeResponse(200, []), geocode.NotFound,
             "真的查無此地 → NotFound")

print("\n--- 查無此地才換寫法重試，服務錯誤不重試 ---")
calls = []
def counting_not_found(*a, **k):
    calls.append(k.get("params", {}).get("q"))
    return FakeResponse(200, [])
with_fake_get(counting_not_found, lambda: _swallow(
    lambda: geocode.resolve("臺北市信義區西村里信義路五段7號89樓",
                            venues_path=Path(tempfile.gettempdir()) / "nonexistent.json")))
check(len(calls) == 3, f"查無此地時會試完 3 個簡化版本（實際試了 {len(calls)} 次）")

calls.clear()
def counting_forbidden(*a, **k):
    calls.append(k.get("params", {}).get("q"))
    return FakeResponse(403)
with_fake_get(counting_forbidden, lambda: _swallow(
    lambda: geocode.resolve("臺北市信義區西村里信義路五段7號89樓",
                            venues_path=Path(tempfile.gettempdir()) / "nonexistent.json")))
check(len(calls) == 1,
      f"被拒絕時只試 1 次就放棄（實際試了 {len(calls)} 次）—— 換寫法也沒用，重試只是浪費時間")

print("\n--- Nominatim 政策遵守檢查 ---")
check("BusinessTripHotelFilter" in geocode.USER_AGENT,
      "User-Agent 可識別本應用（缺少會被回 403）")
check(geocode._MIN_INTERVAL_SECONDS >= 1.0, "請求間隔至少 1 秒，符合每秒 1 次的限制")

print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
