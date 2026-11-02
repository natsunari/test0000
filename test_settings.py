"""
限制設定的測試。

執行方式：
    python test_settings.py

不連網。會用暫存資料夾，不會動到你真正的 settings.json。
"""

import tempfile
from pathlib import Path

import rules
import settings

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


def good_form(**overrides):
    """一組合法的表單值，測試時只改要測的欄位。"""
    form = {
        "hotel_max_per_night_usd": "180",
        "taxi_max_one_way_usd": "20",
        "taxi_max_per_day_usd": "40",
        "walking_max_km": "1.0",
        "road_detour_factor": "1.3",
        "buffer_percent": "3",
        "require_availability": "on",
        "assume_air_conditioning": "on",
    }
    form.update(overrides)
    return form


config = rules.load_config()

print("\n--- 表單解析：合法的值 ---")
values, problem = settings.parse_form(good_form())
check(problem is None, "合法的表單不報錯")
check(values["hotel_max_per_night_usd"] == 180.0, "數字正確轉成 float")
check(values["require_availability"] is True, "勾選的開關為 True")
check(values["assume_elevator"] is False, "沒勾的開關為 False")

print("\n--- 表單解析：擋下不合理的值 ---")
for field, bad, keyword in [
    ("hotel_max_per_night_usd", "abc", "必須是數字"),
    ("hotel_max_per_night_usd", "", "不能空白"),
    ("hotel_max_per_night_usd", "99999", "之間"),
    ("hotel_max_per_night_usd", "0", "之間"),
    ("walking_max_km", "50", "之間"),
    ("road_detour_factor", "0.5", "之間"),
    ("buffer_percent", "-5", "之間"),
]:
    _, problem = settings.parse_form(good_form(**{field: bad}))
    check(problem and keyword in problem,
          f"{field} = {bad!r} 被擋下：{problem}")

_, problem = settings.parse_form(
    good_form(taxi_max_one_way_usd="50", taxi_max_per_day_usd="40"))
check(problem and "每日" in problem, f"每日上限小於單趟上限被擋下：{problem}")

print("\n--- 覆寫會疊在預設值上 ---")
merged = settings.apply(config, {"hotel_max_per_night_usd": 100.0})
check(merged["budget"]["hotel_max_per_night_usd"] == 100.0, "覆寫生效")
check(config["budget"]["hotel_max_per_night_usd"] == 180.0,
      "原本的 config 不會被改動（避免一處改動影響到別處）")
check(merged["budget"]["taxi_max_one_way_usd"]
      == config["budget"]["taxi_max_one_way_usd"], "沒覆寫的值維持預設")

print("\n--- 存檔、讀取、還原 ---")
with tempfile.TemporaryDirectory() as tmp:
    original = settings.SETTINGS_PATH
    settings.SETTINGS_PATH = Path(tmp) / "settings.json"
    try:
        check(settings.load() == {}, "還沒存過時讀出空的")

        settings.save({"hotel_max_per_night_usd": 150.0})
        check(settings.load()["hotel_max_per_night_usd"] == 150.0, "存檔後讀得回來")
        check(settings.current(config)["hotel_max_per_night_usd"] == 150.0,
              "current() 回傳疊加後的值")
        check(settings.current(config)["taxi_max_one_way_usd"] == 20.0,
              "沒覆寫的項目回傳預設值")

        settings.reset()
        check(settings.load() == {}, "還原後回到空的")
        check(settings.current(config)["hotel_max_per_night_usd"] == 180.0,
              "還原後回到 config.toml 的預設值")

        settings.SETTINGS_PATH.write_text("這不是 JSON {{{", encoding="utf-8")
        check(settings.load() == {}, "檔案壞掉時回傳空的，不丟例外")
    finally:
        settings.SETTINGS_PATH = original

print("\n--- 改了限制真的會影響判定 ---")
hotel = {"name": "測試", "type": "hotel",
         "rate_per_night": {"extracted_display_price": 150},
         "gps_coordinates": {"latitude": 35.6326, "longitude": 139.7934}}
dest = (35.6298, 139.7954)
check(rules.evaluate(hotel, dest, config, "Tokyo").passed,
      "每晚 $150 在預設上限 $180 之下 → 通過")
tight = settings.apply(config, {"hotel_max_per_night_usd": 100.0})
check(not rules.evaluate(hotel, dest, tight, "Tokyo").passed,
      "上限改成 $100 之後，同一間就被淘汰")

print("\n--- 「推定有」的設定 ---")
bare = {"name": "測試", "type": "hotel",
        "rate_per_night": {"extracted_display_price": 100},
        "gps_coordinates": {"latitude": 35.6326, "longitude": 139.7934},
        "amenities": ["Free Wi-Fi"]}
v = rules.evaluate(bare, dest, config, "Tokyo")
check(v.amenities["air_conditioning"] == rules.ASSUMED,
      "沒標冷氣時推定為有（預設開啟）")
check(not any("冷氣" in x for x in v.to_confirm), "推定有的項目不列入待確認")
check(v.amenities["elevator"] == rules.UNKNOWN,
      "電梯預設不推定，仍是「不知道」")
check(any("電梯" in x for x in v.to_confirm), "電梯仍列入待確認")

off = settings.apply(config, {"assume_air_conditioning": False})
v = rules.evaluate(bare, dest, off, "Tokyo")
check(v.amenities["air_conditioning"] == rules.UNKNOWN,
      "關掉推定之後，冷氣回到「不知道」")
check(any("冷氣" in x for x in v.to_confirm), "並重新列入待確認")

print(f"\n{'=' * 60}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 60)
