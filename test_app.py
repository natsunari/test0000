"""
表單驗證的測試。

執行方式：
    python test_app.py

不連網。驗證的是「送出去之前就該擋下來」的那些規則。
"""

from datetime import date, timedelta

import app

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


future = (date.today() + timedelta(days=60)).isoformat()
later = (date.today() + timedelta(days=62)).isoformat()


def form(**overrides):
    base = {"destination": "Tokyo Big Sight", "city": "Tokyo",
            "check_in": future, "check_out": later, "mode": app.MODE_CACHE}
    base.update(overrides)
    return base


print("\n--- 目的地：必須是英文 ---")
check(app.validate(form()) is None, "英文名稱通過")
check(app.validate(form(destination="No. 7, Section 5, Xinyi Road, Taipei")) is None,
      "英文地址通過")

for bad in ["台北101", "東京ビッグサイト", "東京都江東区有明", "서울역"]:
    problem = app.validate(form(destination=bad))
    check(problem is not None and "英文" in problem,
          f"「{bad}」被擋下並說明要用英文")

print("\n--- 座標與 Maps 連結不受語言限制 ---")
for ok in [
    "35.6298, 139.7954",
    """35°37'58"N 139°52'50"E""",
    "https://www.google.com/maps/@25.0339,121.5645,15z",
]:
    check(app.validate(form(destination=ok)) is None, f"「{ok[:38]}」通過")

print("\n--- 示範模式（?demo=1）不檢查目的地 ---")
# 示範模式已經從畫面上拿掉，只剩網址參數，留給瀏覽器測試用 ——
# 那是唯一能在不連網、不花額度的情況下驗證結果頁渲染的方式。
check(app.validate(form(destination=""), is_demo=True) is None,
      "示範模式留空也可以（反正會被忽略）")
check(app.validate(form(destination="台北101"), is_demo=True) is None,
      "示範模式填中文也不擋（反正不會拿去查）")
check(app.validate(form(destination="")) is not None,
      "一般模式留空仍然會被擋下")

print("\n--- 必填 ---")
check("目的地" in (app.validate(form(destination="")) or ""), "目的地空白會被擋下")
check("日期" in (app.validate(form(check_in="")) or ""), "入住日期空白會被擋下")
check("日期" in (app.validate(form(check_out="")) or ""), "退房日期空白會被擋下")

print("\n--- 日期先後與範圍 ---")
check("晚於" in (app.validate(form(check_in=later, check_out=future)) or ""),
      "退房早於入住會被擋下")
check("晚於" in (app.validate(form(check_in=future, check_out=future)) or ""),
      "退房與入住同一天也會被擋下（至少要住一晚）")
past = (date.today() - timedelta(days=1)).isoformat()
check("過了" in (app.validate(form(check_in=past, check_out=future)) or ""),
      "入住日期在過去會被擋下")
check("格式" in (app.validate(form(check_in="not-a-date")) or ""),
      "亂填日期格式會被擋下，而不是讓程式當掉")

print("\n--- 三種輸入都要解析到同一個地標 ---")
# 這是重點：不論打名稱、打英文地址、還是貼經緯度，
# 送給 Google Hotels 的都應該是同一個地標，才會找到同一批附近的飯店。
import geocode

taipei101 = geocode.Place(25.0339, 121.5645, "label", "OpenStreetMap",
                          "tw", "Taipei, Taiwan", "Taipei 101")
for label, typed in [
    ("名稱", "Taipei 101"),
    ("英文地址", "No. 7, Section 5, Xinyi Road, Xinyi District, Taipei"),
    ("經緯度", "25.0339, 121.5645"),
    ("度分秒", '25°02\'02"N 121°33\'53"E'),
    ("Maps 網址", "https://www.google.com/maps/@25.0339,121.5645,17z"),
]:
    got = app.hotel_search_query(typed, taipei101)
    check(got == "Taipei 101", f"用{label}查 → 送出「{got}」")

print("\n--- 查詢字串要釘住地理範圍 ---")
# 最後一道保險：地標判斷失誤時，帶上城市就不會跑到別的國家
wrong_landmark = geocode.Place(-33.874, 151.201, "label", "OpenStreetMap",
                               "au", "Sydney, Australia", "Harajuku Gyoza")
got = app.hotel_search_query("14 Darling Dr, Sydney NSW 2000", wrong_landmark)
check(got == "Harajuku Gyoza, Sydney, Australia",
      f"地標誤判成餃子店時仍釘在雪梨 →「{got}」")
check("Sydney" in got,
      "沒有這道保險的話 Google 會看到 Harajuku 跑去搜東京（實際發生過，差 18939 公里）")

check(app.hotel_search_query("Taipei 101", taipei101) == "Taipei 101",
      "名稱裡已經有城市就不重複加")
no_lm_au = geocode.Place(-33.874, 151.201, "l", "s", "au", "Sydney, Australia", None)
check(app.hotel_search_query("Darling Harbour Sydney", no_lm_au)
      == "Darling Harbour Sydney",
      "使用者自己打的字裡有城市也不重複加")
check(app.hotel_search_query("Darling Harbour", no_lm_au)
      == "Darling Harbour, Sydney, Australia",
      "沒有城市就補上")

print("\n--- 解析不到地標時的退路 ---")
no_landmark = geocode.Place(25.03, 121.56, "label", "OpenStreetMap",
                            "tw", "Taipei, Taiwan", None)
check(app.hotel_search_query("Taipei 101", no_landmark) == "Taipei 101",
      "沒有地標時，使用者打的名稱優先於城市")
check(app.hotel_search_query("25.0339, 121.5645", no_landmark) == "Taipei, Taiwan",
      "貼座標又沒有地標時才退回城市")
check(app.hotel_search_query("25.0339, 121.5645",
                             geocode.Place(1, 2, "l", "s")) == "25.0339, 121.5645",
      "什麼都解析不到時回傳原輸入，總比送出空字串好")

print("\n--- 地標名稱是當地語言時要跳過 ---")
cjk = geocode.Place(25.03, 121.56, "label", "OpenStreetMap",
                    "tw", "Taipei, Taiwan", "台北101")
check(app.hotel_search_query("Taipei 101", cjk) == "Taipei 101",
      "Nominatim 回傳中文地標時，改用使用者打的英文")
check(app.hotel_search_query("25.0339, 121.5645", cjk) == "Taipei, Taiwan",
      "沒有英文可用時退回城市，而不是送中文給 Google")

print("\n--- 費率換匯：當地幣別要換成美金 ---")
import fx
import rules

config = rules.load_config()

usd_fare = {"currency": "USD", "base": 3.2, "included_km": 0, "per_km": 2.8}
got, problem = fx.fare_to_usd(usd_fare)
check(problem is None and got["base"] == 3.2, "本來就是美金就原封不動")

# 用假的匯率測台北：1 USD = 31 TWD
class FakeRate:
    value = 31.0

original = fx.get_rate
fx.get_rate = lambda *a, **k: FakeRate()
try:
    taipei = config["taxi_fare_by_country"]["tw"]
    got, problem = fx.fare_to_usd(taipei)
    check(problem is None, "換匯成功")
    check(abs(got["base"] - 85 / 31) < 0.001,
          f"起跳 NT$85 換成 US${got['base']:.2f}")
    check(abs(got["per_km"] - 25 / 31) < 0.001,
          f"每公里 NT$25 換成 US${got['per_km']:.2f}")
    check(got["included_km"] == 1.25, "內含里程不受換匯影響")
    check(got["currency"] == "USD", "換完標記為美金")
finally:
    fx.get_rate = original

# 取不到匯率時必須回報問題，不可以把 85 元當成 85 美金
fx.get_rate = lambda *a, **k: None
try:
    got, problem = fx.fare_to_usd(config["taxi_fare_by_country"]["tw"])
    check(problem is not None and "匯率" in problem,
          "取不到匯率時明確回報問題")
    check(got["base"] == 85,
          "回傳的仍是原始值，由呼叫端決定怎麼辦（絕不默默當成美金）")
finally:
    fx.get_rate = original

print("\n--- 雪梨費率（使用者提供的官方跳錶結構）---")
syd = config["taxi_fare"]["Sydney"]
check(syd["currency"] == "AUD" and syd["base"] == 5.17 and syd["per_km"] == 2.61,
      "照官方公告填：起錶 A$5.17、每公里 A$2.61（白天 06:00–21:59）")

class AudRate:
    value = 1.42      # 實測當時的 US$1 = AUD 1.42

fx.get_rate = lambda *a, **k: AudRate()
try:
    syd_usd, problem = fx.fare_to_usd(syd)
    check(problem is None, "換算成美金成功")
    default_usd, _ = fx.fare_to_usd(config["taxi_fare"]["default"])
    detour = config["distance"]["road_detour_factor"]

    # 保守預設值必須在任何用得到的距離都不低於實際費率，否則不算保守
    for km in (1, 2, 3, 5, 8, 12):
        road = km * detour
        d = rules.estimate_fare(road, default_usd)
        s = rules.estimate_fare(road, syd_usd)
        check(d >= s, f"{km} 公里：保守預設 ${d:.2f} ≥ 雪梨實際 ${s:.2f}")

    # 填入實際費率會讓可接受的範圍明顯放寬 —— 這正是「完全沒結果」的主因
    def radius(fare):
        return (20 - fare["base"]) / fare["per_km"] / detour
    check(radius(syd_usd) > radius(default_usd) * 1.5,
          f"單趟 $20 的直線半徑從 {radius(default_usd):.1f} 公里"
          f"放寬到 {radius(syd_usd):.1f} 公里")
finally:
    fx.get_rate = original

check(rules.resolve_fare(config, "Sydney", "au")[1] == "city",
      "雪梨查得到城市層級費率")
check(rules.resolve_fare(config, None, "tw")[1] == "country",
      "台北走國家層級（費率填在 taxi_fare_by_country.tw）")

print("\n--- 城市下拉的費率標示要看城市與國家兩層 ---")
options = {o["name"]: o["note"] for o in app._city_options(config)}
check(options.get("Sydney") == "已有費率", "雪梨：城市層級有費率")
check(options.get("Taipei") == "依國家費率",
      "台北：城市層級沒有，但國家層級有 —— 不可以顯示成沒費率")
check(options.get("Kaohsiung") == "依國家費率", "高雄同樣走台灣的國家費率")
check(options.get("Vienna") == "",
      "維也納兩層都沒有費率資料（查不到可靠來源），不標示")
covered = sum(1 for v in options.values() if v)
check(covered >= 45,
      f"{covered} / {len(options)} 個城市有費率（城市或國家層級）")
names = [o["name"] for o in app._city_options(config)]
check(names == sorted(names, key=str.casefold), "清單由 A 到 Z 排序")

print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
