"""
最小可用的「聯網搜尋工具」

這支程式做三件事：
  1. 在你自己的電腦上開一個小型網站（只有你看得到）
  2. 你在網頁上輸入關鍵字
  3. 程式去「網路上」（維基百科）查資料，再把結果顯示回網頁

Mac 和 Windows 的執行方式完全一樣，指令都是：
    python app.py
然後打開瀏覽器到 http://127.0.0.1:5000
"""

import requests
from flask import Flask, jsonify, render_template, request

# 建立這個網站應用程式
app = Flask(__name__)

# 不同的「資料來源」設定。以後要加新的搜尋來源，就在這裡加一筆。
SOURCES = {
    "zh": {
        "name": "中文維基百科",
        "api": "https://zh.wikipedia.org/w/api.php",
        "page": "https://zh.wikipedia.org/wiki/",
    },
    "en": {
        "name": "英文維基百科",
        "api": "https://en.wikipedia.org/w/api.php",
        "page": "https://en.wikipedia.org/wiki/",
    },
}

# 有禮貌地告訴對方我們是誰。很多網站的 API 都要求這一行，否則會拒絕回應。
HEADERS = {"User-Agent": "MyFirstSearchTool/1.0 (learning project)"}


def search_wikipedia(keyword: str, source_key: str) -> list[dict]:
    """
    真正「連上網路」的部分。

    keyword    -- 使用者輸入的關鍵字
    source_key -- "zh" 或 "en"
    回傳       -- 一串搜尋結果，每一筆有 title / snippet / url
    """
    source = SOURCES[source_key]

    # 這些是要交給維基百科 API 的查詢條件
    params = {
        "action": "query",
        "list": "search",
        "srsearch": keyword,
        "srlimit": 10,        # 最多拿 10 筆
        "format": "json",
    }

    # 送出網路請求。timeout 很重要：避免對方沒回應時程式卡死。
    response = requests.get(source["api"], params=params, headers=HEADERS, timeout=10)
    response.raise_for_status()   # 如果對方回傳錯誤（例如 500），這行會丟出例外
    data = response.json()        # 把回來的 JSON 文字轉成 Python 可用的資料

    results = []
    for item in data.get("query", {}).get("search", []):
        results.append({
            "title": item["title"],
            # 維基百科回傳的摘要含有 HTML 標籤，這裡簡單清掉
            "snippet": item.get("snippet", "")
                           .replace('<span class="searchmatch">', "")
                           .replace("</span>", ""),
            "url": source["page"] + item["title"].replace(" ", "_"),
        })
    return results


@app.route("/")
def home():
    """使用者打開 http://127.0.0.1:5000 時，顯示搜尋頁面。"""
    return render_template("index.html", sources=SOURCES)


@app.route("/api/search")
def api_search():
    """網頁在背景呼叫這個網址來取得搜尋結果（回傳 JSON，不是網頁）。"""
    keyword = request.args.get("q", "").strip()
    source_key = request.args.get("source", "zh")

    # 防守性檢查：使用者可能什麼都沒輸入，或亂傳來源名稱
    if not keyword:
        return jsonify({"error": "請輸入關鍵字"}), 400
    if source_key not in SOURCES:
        return jsonify({"error": "不支援的資料來源"}), 400

    try:
        results = search_wikipedia(keyword, source_key)
    except requests.Timeout:
        return jsonify({"error": "連線逾時，請確認網路後再試一次"}), 504
    except requests.RequestException as exc:
        return jsonify({"error": f"連線失敗：{exc}"}), 502

    return jsonify({"keyword": keyword, "count": len(results), "results": results})


if __name__ == "__main__":
    # debug=True 代表：你改了程式存檔後，網站會自動重新載入，方便學習時反覆嘗試
    print("\n  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000")
    print("  要停止的話，回到終端機按 Ctrl + C\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
