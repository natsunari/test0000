"""
規則引擎的測試。

執行方式：
    python test_rules.py

全部通過會印出 OK。任何一條規則被改壞，這裡會立刻報錯並指出哪一條。
測試資料取自 Tokyo Big Sight 那次真實查詢，所以數字是有意義的。
不連網、不花 API 額度，可以隨時重跑。
"""

from copy import deepcopy

from rules import (ASSUMED, NO, UNKNOWN, YES, resolve_fare, Verdict, check_amenity, estimate_fare,
                   evaluate, haversine_km, load_config, sort_key)

config = load_config()
import rules as _rules
rules_categories = _rules.CATEGORIES

# 東京國際展示場（Tokyo Big Sight）的座標，當作出差目的地
BIG_SIGHT = (35.6298, 139.7954)

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


# 測試邏輯用固定的費率，不要讀 config.toml 的實際數字 ——
# 否則每次更新某個城市的費率，一堆不相干的測試就會跟著壞掉。
TEST_FARE = {"currency": "USD", "base": 3.2, "included_km": 0, "per_km": 2.8}


def ev(h, cfg=None, fare=None, source="city"):
    """
    測試用的簡寫。

    evaluate() 收的是「已經換算成美金的費率」—— 換匯要連網，
    所以由呼叫端準備好再傳進來。
    """
    return evaluate(h, BIG_SIGHT, cfg or config, fare or TEST_FARE, source)


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
check(abs(estimate_fare(0, tokyo) - tokyo["base"]) < 1e-9, "距離 0 時只收起跳價")
check(estimate_fare(10, tokyo) > estimate_fare(1, tokyo), "距離越遠車資越高")
check(estimate_fare(-5, tokyo) == tokyo["base"], "負距離不會算出負車資")

# 起跳價內含里程：台北起跳 85 元已經含 1.25 公里，不可以重複計費
taipei = config["taxi_fare_by_country"]["tw"]
check(estimate_fare(1.0, taipei) == 85, "台北 1 公里 = NT$85（還在內含里程內）")
check(estimate_fare(1.25, taipei) == 85, "台北 1.25 公里 = NT$85（剛好用完內含里程）")
check(abs(estimate_fare(2.0, taipei) - (85 + 25 * 0.75)) < 1e-9,
      "台北 2 公里 = 85 + 0.75 公里 × 25 = NT$103.75")
check(estimate_fare(5.0, taipei) > estimate_fare(2.0, taipei), "超過之後才開始累加")

print("\n--- 費率查詢順序：城市 → 國家 → 預設 ---")
check(resolve_fare(config, "Tokyo", "jp")[1] == "city", "有城市資料時用城市")
check(resolve_fare(config, None, "tw")[1] == "country", "沒有城市就找國家")
check(resolve_fare(config, "Taipei", "tw")[1] == "country",
      "城市沒登記但國家有，就用國家（台北市不在城市表裡）")
check(resolve_fare(config, None, "zz")[1] == "default",
      "國家也沒有費率資料時用保守預設值")
check(resolve_fare(config, None, None)[1] == "default", "完全不知道在哪也有預設值")
check(resolve_fare(config, "Tokyo", "tw")[1] == "city", "城市優先於國家")

print("\n--- 預設費率不可以低於已知城市（1 公里以上）---")
# 這條測試是因為真的踩過坑：原本的預設值起跳比東京高、但每公里比東京低，
# 超過 1 公里之後反而「低估」車資，會讓人以為沒超標、實際上超了。
#
# 只從 1 公里開始比對。拉斯維加斯起錶 $5.50 比預設值高，所以 0.5 公里時
# 預設值確實比較低 —— 但那個距離的車資只有六塊多，離 $20 上限還很遠，
# 而且 600 公尺以內本來就算走得到、根本不搭車。真正會卡到上限的是長程，
# 那一段由每公里費率主導。
default_fare = config["taxi_fare"]["default"]
usd_cities = {k: v for k, v in config["taxi_fare"].items()
              if k != "default" and v.get("currency") == "USD"}
check(len(usd_cities) >= 5, f"有 {len(usd_cities)} 個用美金計價的城市可以直接比對")
for km in (1, 2, 5, 10, 15, 20):
    d = estimate_fare(km, default_fare)
    for name, fare in usd_cities.items():
        check(d >= estimate_fare(km, fare) - 1e-9,
              f"{km:>4} km：預設 ${d:.2f} ≥ {name} ${estimate_fare(km, fare):.2f}")
check(default_fare["per_km"] >= max(f["per_km"] for f in usd_cities.values()),
      "預設的每公里費率不低於任何已知城市 —— 長程由這一項主導")

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
v = ev(hotel(type="vacation rental"))
check(not v.passed and any("住宿類型" in x for x in v.rejected_for),
      "民宿／短租公寓被淘汰（你的資料裡真的混進 2 筆）")
check(v.wrong_type, "並標記 wrong_type，讓畫面整筆隱藏而不是放進「已排除」")
check(not ev(hotel()).wrong_type,
      "正常飯店不會被誤標")

v = ev(hotel(rate_per_night={"extracted_display_price": 250}))
check(not v.passed, "每晚 $250 超過 $180 上限 → 淘汰")

v = ev(hotel(rate_per_night={"extracted_display_price": 176}))
check(not v.passed,
      "每晚 $176 看似安全，加 3% 緩衝後 $181.28 超標 → 淘汰（邊緣案例）")

v = ev(hotel(rate_per_night={"extracted_display_price": 170}))
check(v.passed, "每晚 $170 加緩衝後 $175.10 仍在上限內 → 通過")

v = ev(hotel(gps_coordinates={"latitude": 35.99, "longitude": 139.79}))
check(not v.passed and any("單趟" in x for x in v.rejected_for),
      "距離太遠、單趟車資超標 → 淘汰")

v = ev(hotel(amenities=[], excluded_amenities=["No elevator"]))
check(not v.passed and any("電梯" in x for x in v.rejected_for),
      "明確標示沒有電梯 → 淘汰")

print("\n--- 通舖型住宿：有些青年旅館把自己登記成 hotel ---")
for name in ["Sydney Harbour YHA", "Wake Up! Bondi Beach Hostel",
             "Base Backpackers Sydney", "Hostelling International Sydney",
             "Capsule Hotel Anshin Oyado", "The Bunkhouse Inn"]:
    v = ev(hotel(name=name))
    check(v.looks_like_dorm and not v.passed, f"擋下「{name}」")

print("\n--- 簡介裡寫明白的，比看名字可靠 ---")
# 以下全部是 2026-11-02 一次真實的雪梨查詢回傳的資料，不是編出來的。
# 雪梨那批 amenities 完全沒有共用衛浴的訊號，但 description 有。

real_sydney = [
    ("Sydney Central Inn",
     "Simple hostel with low-key dorms & private rooms, plus free Wi-Fi, "
     "a kitchen & a TV lounge.", True,
     "名稱完全看不出來，但簡介自己寫了 hostel 與 dorms"),
    ("The Lansdowne Hotel",
     "Long-running pub with American diner eats upstairs and weekly trivia "
     "and live rock bands downstairs.", False,
     "酒吧樓上的房間，簡介沒提共用衛浴 —— 這種只能靠價格擋"),
    ("Sydney Airport Suites",
     "Relaxed apartment hotel offering simply furnished units, as well as "
     "complimentary Wi-Fi.", False,
     "公寓式飯店，不是通舖 —— 它的問題是價格異常（US$11）"),
]
for name, desc, should_block, why in real_sydney:
    v = ev(hotel(name=name, description=desc))
    check(v.looks_like_dorm == should_block,
          f"{'擋下' if should_block else '放行'}「{name}」—— {why}")

check(any("dorms" in x for x in ev(hotel(
    name="Sydney Central Inn",
    description="Simple hostel with low-key dorms & private rooms.")).rejected_for),
    "淘汰原因指出是簡介裡的哪個字")

# 真實用字是複數的 dorms，不是 dormitory —— 這是看了資料才知道的
check(ev(hotel(name="X", description="low-key dorms & private rooms")).looks_like_dorm,
      "「dorms」（複數）要命中")
check(ev(hotel(name="X", description="hostels and guesthouses nearby")).looks_like_dorm,
      "「hostels」（複數）要命中")

print("\n--- 但簡介比對不可以誤殺 ---")
check(not ev(hotel(name="Dormy Inn Premium Sapporo",
                   description="Dormy Inn Premium offers hot spring baths "
                               "and private rooms.")).looks_like_dorm,
      "Dormy Inn 的簡介裡有自己的名字，仍然不可以被 dorms 誤殺")
check(not ev(hotel(name="Sofitel Sydney",
                   description="Upscale hotel with an indoor pool and a spa.")
             ).looks_like_dorm, "正常飯店的簡介不會誤判")
check(not ev(hotel(name="Sofitel Sydney")).looks_like_dorm,
      "沒有 description 欄位時不會當掉，也不會誤判")

print("\n--- 但不可以誤殺正常飯店 ---")
for name in ["Dormy Inn Premium Sapporo", "Park Hyatt Sydney",
             "Hotel Dorsett", "Mercure Sydney", "Capsicum Boutique Hotel"]:
    v = ev(hotel(name=name))
    check(not v.looks_like_dorm, f"放行「{name}」")
check(not ev(hotel(name="Dormy Inn Premium Sapporo")).looks_like_dorm,
      "Dormy Inn 是正常商務飯店連鎖，有獨立房間與衛浴，不可因為含 dorm 就擋下")

print("\n--- 淘汰原因要分類，沒有結果時才說得出是哪條規則擋的 ---")
cases = [
    (hotel(type="vacation rental"), "type"),
    (hotel(name="Sydney YHA"), "dorm"),
    (hotel(rate_per_night={"extracted_display_price": 400}), "price_high"),
    (hotel(rate_per_night=None), "sold_out"),
    (hotel(gps_coordinates={"latitude": 35.99, "longitude": 139.79}), "fare"),
    (hotel(amenities=[], excluded_amenities=["No elevator"]), "amenity"),
]
for h, expected in cases:
    v = ev(h)
    check(v.reject_category == expected,
          f"分類為「{rules_categories.get(expected, expected)}」（{expected}）")

floored = deepcopy(config)
floored["budget"]["hotel_min_per_night_usd"] = 150
v = ev(hotel(rate_per_night={"extracted_display_price": 100}), cfg=floored)
check(v.reject_category == "price_low", "低於下限分類為 price_low")
check(not v.looks_like_dorm,
      "價格下限刷掉的不可標成通舖 —— 那會整筆消失，設錯時就看不見也改不回來")
check(any("你設的下限" in x for x in v.rejected_for),
      "淘汰原因明說是「你設的」下限，不是固定規則")

print("\n--- 保留規則：「不知道」絕不可淘汰 ---")
v = ev(hotel())
check(v.passed, "沒標冷氣與電梯的飯店仍然合格（本專案最重要的一條）")
# 冷氣在 config 裡設為「沒標就推定有」，所以不列入待確認；
# 電梯沒有設推定，維持「不知道」並列入待確認。
check(v.amenities["air_conditioning"] == ASSUMED, "冷氣依設定推定為有")
check(v.amenities["elevator"] == ASSUMED, "電梯依設定推定為有")
check(not v.to_confirm, "兩項都推定時，待確認清單是空的")
check(ASSUMED != YES, "「推定有」與「有」是不同狀態，不會混充成已查證")
# 推定只影響「沒寫」的情況。明確寫「沒有」仍然要淘汰，否則推定就變成忽視資料了。
no_lift = ev(hotel(amenities=[], excluded_amenities=["No elevator"]))
check(not no_lift.passed,
      "即使設定成推定有，明確標示「沒有電梯」的仍然被淘汰")
# 關掉推定就回到待確認
import copy as _copy
strict = _copy.deepcopy(config)
strict["assume_when_unknown"]["elevator"] = False
v2 = ev(hotel(), cfg=strict)
check(v2.amenities["elevator"] == UNKNOWN, "關掉推定後電梯回到「不知道」")
check(any("電梯" in x for x in v2.to_confirm), "並重新列入待確認")

v = ev(hotel(gps_coordinates=None))
check(v.passed and any("座標" in x for x in v.to_confirm),
      "沒有座標不淘汰，只標記無法計算交通費")

print("\n--- 空房判斷 ---")
v = ev(hotel(rate_per_night=None))
check(not v.passed and any("空房" in x for x in v.rejected_for),
      "沒有價格 → 研判沒空房 → 排除（你的資料有 2 筆缺價格）")
check(not v.has_availability, "has_availability 標記為 False")
check(ev(hotel()).has_availability,
      "有價格的飯店標記為有空房")

relaxed = deepcopy(config)
relaxed["availability"]["require"] = False
v = ev(hotel(rate_per_night=None), relaxed)
check(v.passed and any("價格" in x for x in v.to_confirm),
      "把 require 設成 false 時，改為保留並標記待確認")

print("\n--- 走路可達與每日總花費 ---")
v = ev(hotel())
check(config["distance"]["walking_max_km"] == 0.6, "走路門檻固定為 600 公尺")
check(v.walkable, "距離 470 公尺 → 走得到")
# 780 公尺超過 600 門檻，即使只差一點也算要搭車 —— 門檻就是門檻
far = ev(hotel(gps_coordinates={"latitude": 35.6323868, "longitude": 139.7895918}))
check(not far.walkable, "距離 780 公尺 → 超過門檻，算要搭車")
check(v.total_daily_usd == v.price_usd,
      f"走得到的話交通費算 0，每日總花費 = 房價 ${v.price_usd:.0f}")

v = ev(hotel(gps_coordinates={"latitude": 35.6578741, "longitude": 139.8189755},
                   rate_per_night={"extracted_display_price": 70}))
check(not v.walkable, "距離 4.91 公里 → 走不到")
check(abs(v.total_daily_usd - (70 + v.fare_per_day)) < 0.01,
      f"走不到就要加交通費，每日總花費 ${v.total_daily_usd:.2f}")

print("\n--- 加分條件 ---")
v = ev(hotel(amenities=["Free breakfast"]))
check(v.bonuses["breakfast"] == YES and v.passed, "有早餐會記錄，且不影響合格與否")
v = ev(hotel(amenities=[]))
check(v.bonuses["breakfast"] == UNKNOWN and v.passed,
      "沒早餐資料也不淘汰（實測 20 間沒有任何一間標早餐）")

print("\n--- 費率是估的，不該算在個別飯店頭上 ---")
# 以前只要某地沒費率，每間飯店都會被加一條待確認，
# 結果「完全符合」永遠是 0 筆，而且每張卡片重複同一句話。
# 那是整次搜尋共通的狀況，應該在畫面最上面講一次就好。
for source in ("city", "country", "default", "fx_failed"):
    v = ev(hotel(), source=source)
    check(not v.notes, f"來源 {source}：卡片上沒有費率相關的提醒")
    check(not any("費率" in x or "匯率" in x for x in v.to_confirm),
          f"來源 {source}：也不會被推進「待確認」")
check(ev(hotel(), source="default").fare_is_default,
      "但仍然記錄 fare_is_default，畫面才知道要在上面提醒")
check(not ev(hotel(), source="city").fare_is_default,
      "用實際費率時不會誤標")
check(ev(hotel(), source="fx_failed").fare_is_default,
      "換匯失敗退回預設值時也算 is_default")

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
    ev(hotel(name=n, rate_per_night={"extracted_display_price": p},
                   gps_coordinates={"latitude": la, "longitude": lo}))
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
