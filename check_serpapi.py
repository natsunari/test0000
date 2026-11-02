"""
SerpApi 檢查腳本

用途：
  1. 驗證你的 API 金鑰能不能用
  2. 看你的方案還剩多少查詢額度（這一步不花額度）
  3. 實際查一次飯店，把回傳格式存下來（這一步會花 1 次額度，會先問你）

執行方式（記得先啟動虛擬環境，看到 (.venv) 才執行）：
    python check_serpapi.py
"""

import json
import sys
from pathlib import Path

import requests

# .env 檔案就放在這支程式旁邊
ENV_PATH = Path(__file__).parent / ".env"
SAMPLE_PATH = Path(__file__).parent / "serpapi_sample.json"


def load_key() -> str:
    """從 .env 讀出金鑰。不使用額外套件，自己解析就好。"""
    if not ENV_PATH.exists():
        sys.exit(
            "找不到 .env 檔案。\n"
            "請先在終端機執行：  cp .env.example .env\n"
            "然後用 VS Code 打開 .env，把金鑰填進去。"
        )

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "SERPAPI_KEY":
            key = value.strip().strip('"').strip("'")
            if not key or key.startswith("把這一整串"):
                sys.exit("`.env` 裡的 SERPAPI_KEY 還沒填，請填入你的金鑰後再執行一次。")
            return key

    sys.exit("`.env` 裡找不到 SERPAPI_KEY 這一行。")


def check_account(key: str) -> None:
    """查詢帳號狀態。這個查詢不計入搜尋額度。"""
    print("\n[1/2] 檢查金鑰與額度…")
    try:
        res = requests.get(
            "https://serpapi.com/account", params={"api_key": key}, timeout=20
        )
    except requests.RequestException as exc:
        sys.exit(f"連線失敗：{exc}\n請確認網路，或公司網路是否擋住 serpapi.com。")

    if res.status_code == 401:
        sys.exit("金鑰無效（401）。請到 https://serpapi.com/manage-api-key 重新複製。")
    if res.status_code != 200:
        sys.exit(f"查詢失敗（HTTP {res.status_code}）：{res.text[:300]}")

    data = res.json()
    print("  ✅ 金鑰有效")
    for label, field in [
        ("方案", "plan_name"),
        ("本月上限", "searches_per_month"),
        ("本月已用", "this_month_usage"),
        ("本期剩餘", "total_searches_left"),
        ("每小時上限", "plan_searches_left"),
    ]:
        if field in data:
            print(f"  {label}：{data[field]}")


def test_hotel_search(key: str) -> None:
    """實際查一次飯店，確認回傳格式。會花掉 1 次查詢額度。"""
    print("\n[2/2] 測試飯店查詢（會用掉 1 次額度）")
    answer = input("  要繼續嗎？輸入 y 後按 Enter（其他任何鍵則跳過）： ").strip().lower()
    if answer != "y":
        print("  已跳過。")
        return

    params = {
        "api_key": key,
        "engine": "google_hotels",
        "q": "Tokyo Big Sight",      # 用東京國際展示場當測試地點
        "check_in_date": "2027-03-10",
        "check_out_date": "2027-03-12",
        "adults": 1,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
    }

    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=60)
    except requests.RequestException as exc:
        sys.exit(f"連線失敗：{exc}")

    if res.status_code == 429:
        sys.exit("額度用完或查詢太頻繁（429）。")
    if res.status_code != 200:
        sys.exit(f"查詢失敗（HTTP {res.status_code}）：{res.text[:500]}")

    data = res.json()
    SAMPLE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✅ 查詢成功，完整結果已存到：{SAMPLE_PATH.name}")

    print("\n--- 最外層有哪些欄位 ---")
    print(", ".join(sorted(data.keys())))

    properties = data.get("properties") or []
    print(f"\n--- 找到 {len(properties)} 筆住宿 ---")
    if not properties:
        print("（沒有結果，可能是日期太遠或地點字串不合適）")
        return

    first = properties[0]
    print("\n--- 第一筆的所有欄位（欄位名 → 型別 → 內容摘要）---")
    for name in sorted(first.keys()):
        value = first[name]
        kind = type(value).__name__
        preview = json.dumps(value, ensure_ascii=False)
        if len(preview) > 90:
            preview = preview[:90] + "…"
        print(f"  {name:<28} {kind:<6} {preview}")

    print("\n--- 我最關心的幾個欄位是否存在 ---")
    for name in [
        "type", "name", "rate_per_night", "total_rate", "prices",
        "amenities", "excluded_amenities", "gps_coordinates",
        "hotel_class", "extracted_hotel_class", "overall_rating",
        "property_token", "link", "nearby_places", "check_in_time",
    ]:
        print(f"  {'✅' if name in first else '❌'}  {name}")


if __name__ == "__main__":
    api_key = load_key()
    check_account(api_key)
    test_hotel_search(api_key)
    print("\n完成。請把上面的輸出整段複製給我。")
