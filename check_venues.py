"""
展館地址解析檢查

對每個展館用三種寫法各查一次：名稱、英文地址、座標，
確認三者都落在同一個點，而且送給 Google 的查飯店字串是合理的。

執行方式：
    python check_venues.py              全部跑一遍
    python check_venues.py taipei       只跑名稱含 taipei 的（不分大小寫）

這支程式只用 OpenStreetMap，**不會消耗 SerpApi 額度**。

⚠️ Nominatim 使用政策提醒
   這支程式一次會發出數十個查詢。官方政策強烈反對「批次查詢」，
   指的是程式定期、自動、大量地查。這支是你手動跑一次的檢查工具，
   而且每次請求間隔 1.1 秒以上、查過的會存進 venues.json 不重複查，
   所以第二次執行幾乎不連網。
   請不要把它排進排程定期執行。
   政策全文：https://operations.osmfoundation.org/policies/nominatim/
"""

from __future__ import annotations

import sys

import app
import geocode
from rules import haversine_km

# (展覽, 展館名稱, 英文地址, 已查證的參考座標或 None)
#
# 參考座標只有少數幾個是查證過的，其餘留 None ——
# 不填比填一個我憑印象寫的數字好，因為錯的參考值會製造假的失敗。
# 沒有參考座標時仍然會比對「名稱 vs 地址」是否一致，那本身就很有鑑別力。
VENUES = [
    ("CES", "Las Vegas Convention Center",
     "3150 Paradise Rd, Las Vegas, NV 89109, USA", None),
    ("MWC / ISE", "Fira Barcelona Gran Via",
     "Av. Joan Carles I, 64, 08908 L'Hospitalet de Llobregat, Spain", None),
    ("IFA", "Messe Berlin",
     "Messedamm 22, 14055 Berlin, Germany", None),
    ("COMPUTEX", "Taipei Nangang Exhibition Center",
     "No. 1, Jingmao 2nd Rd, Nangang District, Taipei, Taiwan", None),
    ("various", "Tokyo Big Sight",
     "3-11-1 Ariake, Koto City, Tokyo, Japan", None),
    ("CEATEC", "Makuhari Messe",
     "2-1 Nakase, Mihama Ward, Chiba, Japan", None),
    ("embedded world", "NurnbergMesse",
     "Messezentrum 1, 90471 Nurnberg, Germany", (49.417409, 11.115364)),
    ("SEMICON West", "Moscone Center",
     "747 Howard St, San Francisco, CA 94103, USA", (37.784173, -122.401557)),
    ("GITEX", "Dubai World Trade Centre",
     "Sheikh Zayed Road, Dubai, United Arab Emirates", None),
    ("Hannover Messe", "Deutsche Messe Hannover",
     "Messegelande, 30521 Hannover, Germany", None),
    ("electronica", "Messe Munchen",
     "Messegelande, 81823 Munchen, Germany", None),
    ("KES", "COEX Seoul",
     "513 Yeongdong-daero, Gangnam-gu, Seoul, South Korea", None),
    ("various", "ICC Sydney",
     "14 Darling Drive, Sydney NSW 2000, Australia", None),
]

TOLERANCE_KM = 3.0      # 同一個展館區，三種寫法的落點差距上限


def describe(label: str, text: str) -> tuple[object | None, str]:
    """解析一個輸入，回傳 (Place, 要顯示的一行字)。"""
    try:
        place = geocode.resolve(text)
    except LookupError as exc:
        first = str(exc).splitlines()[0]
        if len(first) > 100:
            first = first[:100] + "…"
        return None, f"    {label:<6} ❌ {first}"
    query = app.hotel_search_query(text, place)
    landmark = place.landmark or "（無地標）"
    return place, (f"    {label:<6} 解析→ {landmark[:40]:<42}"
                   f"查飯店用→ {query}")


def main() -> int:
    keyword = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    venues = [v for v in VENUES if not keyword
              or keyword in v[1].lower() or keyword in v[0].lower()]
    if not venues:
        print(f"沒有符合「{keyword}」的展館。")
        return 1

    print(f"要檢查 {len(venues)} 個展館，每個查三次，"
          f"每次間隔 1.1 秒，預計約 {len(venues) * 3 * 1.2:.0f} 秒。")
    print("查過的會存起來，第二次執行會快很多。\n")

    passed = failed = 0
    for event, name, address, reference in venues:
        print(f"● {name}（{event}）")

        by_name, line = describe("名稱", name)
        print(line)
        by_addr, line = describe("地址", address)
        print(line)

        # 用名稱查到的座標當第三種輸入，不必由我提供座標
        by_coord = None
        if by_name:
            coord_text = f"{by_name.latitude}, {by_name.longitude}"
            by_coord, line = describe("座標", coord_text)
            print(line)

        problems = []
        if by_name and by_addr:
            gap = haversine_km(by_name.latitude, by_name.longitude,
                               by_addr.latitude, by_addr.longitude)
            mark = "✅" if gap <= TOLERANCE_KM else "❌"
            print(f"    {mark} 名稱與地址相距 {gap:.2f} 公里")
            if gap > TOLERANCE_KM:
                problems.append(f"名稱與地址差 {gap:.1f} 公里")
        else:
            problems.append("名稱或地址查不到")

        if reference and by_name:
            gap = haversine_km(by_name.latitude, by_name.longitude, *reference)
            mark = "✅" if gap <= TOLERANCE_KM else "❌"
            print(f"    {mark} 與查證過的座標相距 {gap:.2f} 公里")
            if gap > TOLERANCE_KM:
                problems.append(f"與查證座標差 {gap:.1f} 公里")

        # 查飯店字串若落在別的國家就是大問題
        if by_name and by_addr:
            qa = app.hotel_search_query(name, by_name)
            qb = app.hotel_search_query(address, by_addr)
            if by_name.country_code != by_addr.country_code:
                problems.append(
                    f"國碼不一致（{by_name.country_code} vs {by_addr.country_code}）")
            print(f"    {'❌' if problems else '✅'} "
                  f"{'有問題：' + '、'.join(problems) if problems else '三種寫法一致'}")

        if problems:
            failed += 1
        else:
            passed += 1
        print()

    print("=" * 62)
    print(f"通過 {passed} 個，有問題 {failed} 個")
    if failed:
        print("\n有問題的請把上面那幾段貼回來，我依實際情況修。")
    print("=" * 62)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
