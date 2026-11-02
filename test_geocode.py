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
