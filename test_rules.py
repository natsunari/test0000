"""
規則引擎的測試。

執行方式：
    python test_rules.py

全部通過會印出 OK。任何一條規則被改壞，這裡會立刻報錯並指出哪一條。
測試資料取自 Tokyo Big Sight 那次真實查詢，所以數字是有意義的。
不連網、不花 API 額度，可以隨時重跑。
"""

from rules import (NO, UNKNOWN, YES, Verdict, check_amenity, estimate_fare,
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
check(any("冷氣" in x for x in v.to_confirm), "但會標記冷氣待確認")
check(any("電梯" in x for x in v.to_confirm), "也會標記電梯待確認")
check(v.amenities["air_conditioning"] == UNKNOWN, "狀態記錄為「不知道」")

v = evaluate(hotel(rate_per_night=None), BIG_SIGHT, config, "Tokyo")
check(v.passed and any("價格" in x for x in v.to_confirm),
      "沒有價格資料不淘汰，只標記待確認（你的資料有 2 筆缺價格）")

v = evaluate(hotel(gps_coordinates=None), BIG_SIGHT, config, "Tokyo")
check(v.passed and any("座標" in x for x in v.to_confirm),
      "沒有座標不淘汰，只標記無法計算交通費")

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

print("\n--- 排序 ---")
cheap_far = Verdict(name="便宜但遠", passed=True, price_usd=80, distance_km=9)
pricey_near = Verdict(name="貴但近", passed=True, price_usd=170, distance_km=1)
needs_check = Verdict(name="待確認多", passed=True, price_usd=60,
                      distance_km=1, to_confirm=["冷氣", "電梯"])
order = [v.name for v in sorted([needs_check, pricey_near, cheap_far], key=sort_key)]
check(order[-1] == "待確認多", "待確認項目多的排最後")
check(order[0] == "便宜但遠", "同樣零待確認時，便宜的排前面")

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
for v in sorted(results, key=sort_key):
    state = "合格" if v.passed else "淘汰"
    print(f"  [{state}] {v.name[:34]:<35}"
          f"每晚 ${v.price_usd:<5.0f}{v.distance_km:>6.2f} km   "
          f"單趟 ${v.fare_one_way:<6.2f} 每日 ${v.fare_per_day:.2f}")
check(all(v.passed for v in results), "這 5 間真實飯店全部通過預算與交通費檢查")

print(f"\n{'=' * 60}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 60)
