"""
規則引擎的測試。

執行方式：
    python test_rules.py

全部通過會印出 OK。任何一條規則被改壞，這裡會立刻報錯並指出哪一條。
測試資料取自 Tokyo Big Sight 那次真實查詢，所以數字是有意義的。
不連網、不花 API 額度，可以隨時重跑。
"""

from copy import deepcopy

from rules import (ASSUMED, NO, UNKNOWN, YES, Verdict, check_amenity, estimate_fare,
                   evaluate, haversine_km, load_config, sort_key)

config = load_config()

# 東京國際展示場（Tokyo Big Sight）的座標，當作出差目的地
BIG_SIGHT = (35.6298, 139.7954)

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


def hotel(**overrides):
    """以真實資料為底，測試時只改要測的欄位。"""
    base = {
        "name": "測試飯店",
        "type": "hotel",
        "rate_per_night": {"extracted_display_price": 121},
        "gps_coordinates": {"latitude": 35.6326198, "longitude": 139.7933536},
        "amenities": ["Free Wi-Fi", "Restaurant"],
    }
    base.update(overrides)
    return base


print("\n--- 距離計算 ---")
d = haversine_km(35.6326198, 139.7933536, *BIG_SIGHT)
check(0.25 < d < 0.55,
      f"Washington Hotel 到 Big Sight 算出 {d:.2f} 公里，"
      f"與 Google 給的「走路 4 分鐘」吻合")
check(haversine_km(35.0, 139.0, 35.0, 139.0) == 0, "同一個點距離為 0")

print("\n--- 車資計算 ---")
tokyo = config["taxi_fare"]["Tokyo"]
check(abs(estimate_fare(0, tokyo) - tokyo["base_usd"]) < 1e-9, "距離 0 時只收起跳價")
check(estimate_fare(10, tokyo) > estimate_fare(1, tokyo), "距離越遠車資越高")
check(estimate_fare(-5, tokyo) == tokyo["base_usd"], "負距離不會算出負車資")

print("\n--- 預設費率必須在任何距離都夠保守 ---")
# 這條測試是因為真的踩過坑：原本的預設值 $3.5 + $2.5/km 起跳比東京高、
# 但每公里比東京低，所以超過 1 公里之後反而「低估」車資，
# 會讓使用者以為沒超標、實際上超了。起跳與每公里兩個數字要一起看。
default_fare = config["taxi_fare"]["default"]
cities = {k: v for k, v in config["taxi_fare"].items() if k != "default"}
for km in (0.5, 1, 2, 5, 10, 15, 20):
    d = estimate_fare(km, default_fare)
    for name, fare in cities.items():
        check(d >= estimate_fare(km, fare) - 1e-9,
              f"{km:>4} km：預設 ${d:.2f} ≥ {name} ${estimate_fare(km, fare):.2f}")

print("\n--- 設施三態判定（本專案最關鍵的邏輯）---")
ac = config["amenity_match"]["air_conditioning"]
lift = config["amenity_match"]["elevator"]
check(check_amenity(["Air conditioning"], [], ac) == YES, "有標冷氣 → 有")
check(check_amenity([], ["No elevator"], lift) == NO, "明確標示沒電梯 → 沒有")
check(check_amenity(["Free Wi-Fi"], [], lift) == UNKNOWN,
      "沒提到電梯 → 不知道（絕不可當成沒有）")
check(check_amenity(None, None, ac) == UNKNOWN, "完全沒有設施資料 → 不知道")
check(check_amenity(["AIR CONDITIONING"], [], ac) == YES, "大小寫不同也比對得到")

print("\n--- 淘汰規則 ---")
v = evaluate(hotel(type="vacation rental"), BIG_SIGHT, config, "Tokyo")
check(not v.passed and any("住宿類型" in x for x in v.rejected_for),
      "民宿／短租公寓被淘汰（你的資料裡真的混進 2 筆）")

v = evaluate(hotel(rate_per_night={"extracted_display_price": 250}),
             BIG_SIGHT, config, "Tokyo")
check(not v.passed, "每晚 $250 超過 $180 上限 → 淘汰")

v = evaluate(hotel(rate_per_night={"extracted_display_price": 176}),
             BIG_SIGHT, config, "Tokyo")
check(not v.passed,
      "每晚 $176 看似安全，加 3% 緩衝後 $181.28 超標 → 淘汰（邊緣案例）")

v = evaluate(hotel(rate_per_night={"extracted_display_price": 170}),
             BIG_SIGHT, config, "Tokyo")
check(v.passed, "每晚 $170 加緩衝後 $175.10 仍在上限內 → 通過")

v = evaluate(hotel(gps_coordinates={"latitude": 35.99, "longitude": 139.79}),
             BIG_SIGHT, config, "Tokyo")
check(not v.passed and any("單趟" in x for x in v.rejected_for),
      "距離太遠、單趟車資超標 → 淘汰")

v = evaluate(hotel(amenities=[], excluded_amenities=["No elevator"]),
             BIG_SIGHT, config, "Tokyo")
check(not v.passed and any("電梯" in x for x in v.rejected_for),
      "明確標示沒有電梯 → 淘汰")

print("\n--- 保留規則：「不知道」絕不可淘汰 ---")
v = evaluate(hotel(), BIG_SIGHT, config, "Tokyo")
check(v.passed, "沒標冷氣與電梯的飯店仍然合格（本專案最重要的一條）")
# 冷氣在 config 裡設為「沒標就推定有」，所以不列入待確認；
# 電梯沒有設推定，維持「不知道」並列入待確認。
check(v.amenities["air_conditioning"] == ASSUMED, "冷氣依設定推定為有")
check(not any("冷氣" in x for x in v.to_confirm), "推定有的項目不列入待確認")
check(v.amenities["elevator"] == UNKNOWN, "電梯不推定，狀態仍是「不知道」")
check(any("電梯" in x for x in v.to_confirm), "並標記電梯待確認")
check(ASSUMED != YES, "「推定有」與「有」是不同狀態，不會混充成已查證")

v = evaluate(hotel(gps_coordinates=None), BIG_SIGHT, config, "Tokyo")
check(v.passed and any("座標" in x for x in v.to_confirm),
      "沒有座標不淘汰，只標記無法計算交通費")

print("\n--- 空房判斷 ---")
v = evaluate(hotel(rate_per_night=None), BIG_SIGHT, config, "Tokyo")
check(not v.passed and any("空房" in x for x in v.rejected_for),
      "沒有價格 → 研判沒空房 → 排除（你的資料有 2 筆缺價格）")
check(not v.has_availability, "has_availability 標記為 False")
check(evaluate(hotel(), BIG_SIGHT, config, "Tokyo").has_availability,
      "有價格的飯店標記為有空房")

relaxed = deepcopy(config)
relaxed["availability"]["require"] = False
v = evaluate(hotel(rate_per_night=None), BIG_SIGHT, relaxed, "Tokyo")
check(v.passed and any("價格" in x for x in v.to_confirm),
      "把 require 設成 false 時，改為保留並標記待確認")

print("\n--- 走路可達與每日總花費 ---")
v = evaluate(hotel(), BIG_SIGHT, config, "Tokyo")
check(config["distance"]["walking_max_km"] == 0.6, "走路門檻固定為 600 公尺")
check(v.walkable, "距離 470 公尺 → 走得到")
# 780 公尺超過 600 門檻，即使只差一點也算要搭車 —— 門檻就是門檻
far = evaluate(hotel(gps_coordinates={"latitude": 35.6323868, "longitude": 139.7895918}),
               BIG_SIGHT, config, "Tokyo")
check(not far.walkable, "距離 780 公尺 → 超過門檻，算要搭車")
check(v.total_daily_usd == v.price_usd,
      f"走得到的話交通費算 0，每日總花費 = 房價 ${v.price_usd:.0f}")

v = evaluate(hotel(gps_coordinates={"latitude": 35.6578741, "longitude": 139.8189755},
                   rate_per_night={"extracted_display_price": 70}),
             BIG_SIGHT, config, "Tokyo")
check(not v.walkable, "距離 4.91 公里 → 走不到")
check(abs(v.total_daily_usd - (70 + v.fare_per_day)) < 0.01,
      f"走不到就要加交通費，每日總花費 ${v.total_daily_usd:.2f}")

print("\n--- 加分條件 ---")
v = evaluate(hotel(amenities=["Free breakfast"]), BIG_SIGHT, config, "Tokyo")
check(v.bonuses["breakfast"] == YES and v.passed, "有早餐會記錄，且不影響合格與否")
v = evaluate(hotel(amenities=[]), BIG_SIGHT, config, "Tokyo")
check(v.bonuses["breakfast"] == UNKNOWN and v.passed,
      "沒早餐資料也不淘汰（實測 20 間沒有任何一間標早餐）")

print("\n--- 費率預設值提醒 ---")
v = evaluate(hotel(), BIG_SIGHT, config, "沒填過的城市")
check(v.fare_is_default and any("費率" in x for x in v.to_confirm),
      "沒填費率的城市會用保守預設值並提醒")
check(not evaluate(hotel(), BIG_SIGHT, config, "Tokyo").fare_is_default,
      "已填費率的城市不會誤報")

print("\n--- 排序（D 方案：走路可達優先，其餘照每日總花費）---")
walk_pricey = Verdict(name="走得到但貴", passed=True, price_usd=160,
                      distance_km=0.4, walkable=True, total_daily_usd=160)
drive_cheap = Verdict(name="要搭車但便宜", passed=True, price_usd=70,
                      distance_km=5, walkable=False, total_daily_usd=104)
drive_cheapest = Verdict(name="要搭車最便宜", passed=True, price_usd=60,
                         distance_km=5, walkable=False, total_daily_usd=94)
order = [v.name for v in sorted([drive_cheap, walk_pricey, drive_cheapest],
                                key=sort_key)]
check(order[0] == "走得到但貴",
      "走路可達的排第一，即使房價較高（交通費 $0 且不受塞車與加成影響）")
check(order[1] == "要搭車最便宜", "其餘照每日總花費由低到高")

print("\n--- 真實資料試算（你的 Tokyo Big Sight 查詢結果）---")
real = [
    ("Tokyo Bay Ariake Washington Hotel", 121, 35.6326198, 139.7933536),
    ("APA Hotel & Resort Tokyo Bay Shiom", 70, 35.6578741, 139.8189755),
    ("Sotetsu Grand Fresa Tokyo-Bay Aria", 133, 35.6323868, 139.78959179999998),
    ("La Vista Tokyo Bay", 100, 35.6466503, 139.78400879999998),
    ("Tokyo East Side Hotel Kaie", 81, 35.6588637, 139.81799569999998),
]
results = [
    evaluate(hotel(name=n, rate_per_night={"extracted_display_price": p},
                   gps_coordinates={"latitude": la, "longitude": lo}),
             BIG_SIGHT, config, "Tokyo")
    for n, p, la, lo in real
]
ordered = sorted(results, key=sort_key)
for v in ordered:
    state = "合格" if v.passed else "淘汰"
    walk = "🚶走得到" if v.walkable else f"🚕每日 ${v.fare_per_day:.2f}"
    print(f"  [{state}] {v.name[:33]:<34}"
          f"房價 ${v.price_usd:<5.0f}{v.distance_km:>6.2f} km  "
          f"{walk:<16} 每日總計 ${v.total_daily_usd:.2f}")
check(all(v.passed for v in results), "這 5 間真實飯店全部通過預算與交通費檢查")
check(ordered[0].name.startswith("Tokyo Bay Ariake"),
      "走路 4 分鐘到展館的 Washington Hotel 排第一（即使不是最便宜）")
check(ordered[-1].name.startswith("Sotetsu"),
      "每日總計最高的 Sotetsu 排最後（780 公尺不算走得到，要加計程車費）")

print(f"\n{'=' * 60}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 60)
