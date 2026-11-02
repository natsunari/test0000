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

print("\n--- 壞掉的 venues.json 不會讓程式掛掉 ---")
with tempfile.TemporaryDirectory() as tmp:
    broken = Path(tmp) / "venues.json"
    broken.write_text("這不是 JSON {{{", encoding="utf-8")
    check(geocode.load_venues(broken) == {}, "檔案壞掉時回傳空的，不丟例外")

print("\n--- Nominatim 政策遵守檢查 ---")
check("BusinessTripHotelFilter" in geocode.USER_AGENT,
      "User-Agent 可識別本應用（缺少會被回 403）")
check(geocode._MIN_INTERVAL_SECONDS >= 1.0, "請求間隔至少 1 秒，符合每秒 1 次的限制")

print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
