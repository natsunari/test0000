"""
出差飯店搜尋 —— 網頁介面

啟動：
    python app.py
然後打開 http://127.0.0.1:5000

流程：
    你輸入目的地（地址或座標）與日期
      → 解析座標（geocode.py）
      → 查飯店，有快取就用快取（search.py）
      → 套用公司與個人限制（rules.py）
      → 分成「完全符合 / 待確認 / 已排除」三區顯示

示範模式：
    勾選「示範模式」就用內建的測試資料跑完整流程，
    不連網、不消耗 API 額度，用來先看看介面長怎樣。
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import Flask, render_template, request

import geocode
import rules
import search

app = Flask(__name__)

# 示範模式固定用東京國際展示場，因為測試資料就是在那裡查的
DEMO_PLACE = geocode.Place(35.6298, 139.7954, "Tokyo Big Sight（示範資料）", "示範模式")
DEMO_CITY = "Tokyo"


def default_dates() -> tuple[str, str]:
    """預設帶一個月後的兩晚，使用者可以改。"""
    start = date.today() + timedelta(days=30)
    return start.isoformat(), (start + timedelta(days=2)).isoformat()


@app.route("/", methods=["GET", "POST"])
def home():
    config = rules.load_config()
    check_in_default, check_out_default = default_dates()

    form = {
        "destination": request.form.get("destination", ""),
        "check_in": request.form.get("check_in") or check_in_default,
        "check_out": request.form.get("check_out") or check_out_default,
        "city": request.form.get("city", ""),
        "demo": request.form.get("demo") == "on",
        "refresh": request.form.get("refresh") == "on",
    }

    context = {
        "form": form,
        "config": config,
        "labels": config.get("labels", {}),
        "known_venues": sorted(geocode.load_venues().keys()),
        "known_cities": [c for c in config["taxi_fare"] if c != "default"],
    }

    if request.method != "POST":
        return render_template("index.html", **context)

    # ---- 1. 目的地轉座標 ----
    try:
        if form["demo"]:
            place = DEMO_PLACE
        else:
            place = geocode.resolve(form["destination"])
    except LookupError as exc:
        return render_template("index.html", error=str(exc), **context)

    # ---- 2. 取得飯店資料 ----
    try:
        if form["demo"]:
            data, source = search.load_fixture(), "示範資料"
        else:
            data, source = search.search_hotels(
                form["destination"], form["check_in"], form["check_out"],
                use_cache=not form["refresh"],
            )
    except (search.MissingKey, search.SearchFailed) as exc:
        return render_template("index.html", error=str(exc), **context)

    # ---- 3. 套用規則 ----
    city = DEMO_CITY if form["demo"] else (form["city"].strip() or None)
    destination = (place.latitude, place.longitude)
    verdicts = [
        rules.evaluate(h, destination, config, city)
        for h in data.get("properties", [])
    ]
    verdicts.sort(key=rules.sort_key)

    # ---- 4. 分成三區 ----
    # 示範模式忽略了使用者的輸入，要明講，不能默默吃掉
    ignored = None
    if form["demo"]:
        parts = [x for x in [form["destination"].strip()] if x]
        ignored = {
            "destination": parts[0] if parts else None,
            "dates": f'{form["check_in"]} ~ {form["check_out"]}',
        }

    context.update(
        place=place,
        source=source,
        ignored=ignored,
        searched=True,
        fetched_at=data.get("_fetched_at"),
        total=len(verdicts),
        clear=[v for v in verdicts if v.passed and not v.to_confirm],
        needs_check=[v for v in verdicts if v.passed and v.to_confirm],
        rejected=[v for v in verdicts if not v.passed],
        fare_used=rules.get_fare(config, city)[0],
        fare_is_default=rules.get_fare(config, city)[1],
        city_used=city,
    )

    # 查成功的地點存起來，下次同一個展館不用再問 OpenStreetMap
    if not form["demo"] and place.source == "OpenStreetMap":
        geocode.save_venue(form["destination"], place)

    return render_template("index.html", **context)


if __name__ == "__main__":
    print("\n  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000")
    print("  要停止的話，回到終端機按 Ctrl + C")
    print("  第一次使用可以先勾「示範模式」，不花 API 額度\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
