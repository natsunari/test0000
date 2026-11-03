"""
飯店查詢與分頁的測試。

執行方式：
    python test_search.py

不連網：所有查詢都用假的回應。
"""

import tempfile
from pathlib import Path

import search

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


def hotels(*tokens):
    return [{"property_token": tk, "name": f"Hotel {tk}"} for tk in tokens]


print("\n--- 找出下一頁要帶的參數 ---")
check(search._next_page_params(
    {"serpapi_pagination": {"next_page_token": "ABC"}})
    == {"next_page_token": "ABC"}, "分頁物件裡的 token")
check(search._next_page_params({"next_page_token": "XYZ"})
      == {"next_page_token": "XYZ"}, "最外層的 token")

from_url = search._next_page_params({"serpapi_pagination": {
    "next": "https://serpapi.com/search?engine=google_hotels&q=Sydney"
            "&next_page_token=TOK&api_key=SECRET"}})
check(from_url and from_url.get("next_page_token") == "TOK",
      "從網址拆出 token")
check("api_key" not in (from_url or {}),
      "網址裡夾帶的金鑰會被丟掉，不會被當成一般參數再送出去")

check(search._next_page_params({}) is None, "沒有下一頁時回傳 None")
check(search._next_page_params({"serpapi_pagination": {}}) is None,
      "分頁物件是空的也回傳 None")
check(search._next_page_params({"next": "不是網址"}) is None,
      "欄位內容不是網址時不會誤判")


print("\n--- 抓多頁並合併 ---")
with tempfile.TemporaryDirectory() as tmp:
    search.CACHE_DIR = Path(tmp)
    search.load_api_key = lambda: "TEST_KEY"

    calls = []

    def two_pages(params):
        calls.append(params)
        if "next_page_token" in params:
            return {"properties": hotels("c", "d")}
        return {"properties": hotels("a", "b"),
                "serpapi_pagination": {"next_page_token": "PAGE2"}}

    search._fetch_page = two_pages
    data, source = search.search_hotels("Sydney", "2027-03-10", "2027-03-12",
                                        use_cache=False, pages=2)
    check(len(calls) == 2, f"抓了 {len(calls)} 頁")
    check(len(data["properties"]) == 4, "兩頁的結果合併成 4 筆")
    check(data["_pages_fetched"] == 2, "有記錄抓了幾頁（畫面要顯示花了幾次額度）")
    check(source == "SerpApi", "來源標示正確")

    print("\n--- 重複的飯店只留一筆 ---")
    calls.clear()

    def overlapping(params):
        calls.append(params)
        if "next_page_token" in params:
            return {"properties": hotels("b", "c")}      # b 重複
        return {"properties": hotels("a", "b"),
                "serpapi_pagination": {"next_page_token": "PAGE2"}}

    search._fetch_page = overlapping
    data, _ = search.search_hotels("Melbourne", "2027-03-10", "2027-03-12",
                                   use_cache=False, pages=2)
    tokens = [h["property_token"] for h in data["properties"]]
    check(tokens == ["a", "b", "c"], f"去重後剩 {tokens}")

    print("\n--- 沒有下一頁就停 ---")
    calls.clear()
    search._fetch_page = lambda params: (calls.append(params)
                                         or {"properties": hotels("a")})
    data, _ = search.search_hotels("Perth", "2027-03-10", "2027-03-12",
                                   use_cache=False, pages=3)
    check(len(calls) == 1, "第一頁就沒有下一頁，只查了 1 次（不浪費額度）")
    check(data["_pages_fetched"] == 1, "記錄的頁數也是 1")

    print("\n--- pages=1 時只抓一頁 ---")
    calls.clear()
    search._fetch_page = two_pages
    search.search_hotels("Brisbane", "2027-03-10", "2027-03-12",
                         use_cache=False, pages=1)
    check(len(calls) == 1, "設定 1 頁就只查 1 次，即使還有下一頁")

    print("\n--- 房價上限要送給 Google ---")
    calls.clear()
    search._fetch_page = lambda params: (calls.append(params)
                                         or {"properties": hotels("a")})
    search.search_hotels("Sydney", "2027-03-10", "2027-03-12",
                         use_cache=False, pages=1, max_price=180)
    check(calls[0].get("max_price") == 180,
          "max_price 有送出 —— 超標的飯店就不會占掉那 20 個名額")
    calls.clear()
    search.search_hotels("Sydney", "2027-03-10", "2027-03-12",
                         use_cache=False, pages=1, max_price=None)
    check("max_price" not in calls[0], "沒設上限時不送這個參數")

    print("\n--- 快取要認得價格上限 ---")
    a = search._cache_path({"q": "Sydney", "max_price": 180})
    b = search._cache_path({"q": "Sydney", "max_price": 100})
    c = search._cache_path({"q": "Sydney", "max_price": 180})
    check(a != b, "上限不同就是不同的快取（結果本來就不一樣）")
    check(a == c, "條件相同就命中同一個快取")
    check(search._cache_path({"q": "X", "api_key": "K1"})
          == search._cache_path({"q": "X", "api_key": "K2"}),
          "金鑰不影響快取檔名")

print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
