"""
出差飯店搜尋 —— 網頁介面

啟動：
    python app.py
然後打開 http://127.0.0.1:5000
"""

from __future__ import annotations

from datetime import date

from flask import Flask, render_template, request

import fx
import geocode
import rules
import search

app = Flask(__name__)

# 示範模式固定用東京國際展示場，因為內建測試資料就是在那裡查的
DEMO_PLACE = geocode.Place(
    35.6298, 139.7954, "Tokyo Big Sight（示範資料）", "示範模式", "jp"
)
DEMO_CITY = "Tokyo"

# 三選一的搜尋模式
MODE_DEMO = "demo"
MODE_CACHE = "cache"
MODE_REFRESH = "refresh"


def empty_form() -> dict:
    """每次重新打開頁面時的空白表單 —— 不預填任何值，避免沿用舊的日期。"""
    return {"destination": "", "city": "", "check_in": "", "check_out": "",
            "mode": MODE_CACHE}


def validate(form: dict) -> str | None:
    """檢查必填與日期先後。回傳錯誤訊息，沒問題則回傳 None。"""
    if form["mode"] != MODE_DEMO and not form["destination"].strip():
        return "請填寫目的地（展館名稱、地址，或座標）。"
    if not form["check_in"] or not form["check_out"]:
        return "請選擇入住與退房日期。"
    try:
        start = date.fromisoformat(form["check_in"])
        end = date.fromisoformat(form["check_out"])
    except ValueError:
        return "日期格式不正確，請用日期選擇器重新選一次。"
    if end <= start:
        return "退房日期必須晚於入住日期。"
    if start < date.today():
        return "入住日期已經過了，請選擇未來的日期。"
    return None


@app.route("/", methods=["GET", "POST"])
def home():
    config = rules.load_config()

    context = {
        "config": config,
        "labels": config.get("labels", {}),
        "known_venues": sorted(geocode.load_venues().keys()),
        "known_cities": [c for c in config["taxi_fare"] if c != "default"],
        "MODE_DEMO": MODE_DEMO,
        "MODE_CACHE": MODE_CACHE,
        "MODE_REFRESH": MODE_REFRESH,
    }

    # 直接打開頁面（GET）時一律給空白表單
    if request.method != "POST":
        return render_template("index.html", form=empty_form(), **context)

    form = {
        "destination": request.form.get("destination", ""),
        "city": request.form.get("city", ""),
        "check_in": request.form.get("check_in", ""),
        "check_out": request.form.get("check_out", ""),
        "mode": request.form.get("mode", MODE_CACHE),
    }
    context["form"] = form

    problem = validate(form)
    if problem:
        return render_template("index.html", error=problem, **context)

    is_demo = form["mode"] == MODE_DEMO

    # ---- 1. 目的地轉座標 ----
    try:
        place = DEMO_PLACE if is_demo else geocode.resolve(form["destination"])
    except LookupError as exc:
        return render_template("index.html", error=str(exc), **context)

    # ---- 2. 取得飯店資料 ----
    try:
        if is_demo:
            data, source = search.load_fixture(), "示範資料"
        else:
            data, source = search.search_hotels(
                form["destination"], form["check_in"], form["check_out"],
                use_cache=form["mode"] != MODE_REFRESH,
            )
    except (search.MissingKey, search.SearchFailed) as exc:
        return render_template("index.html", error=str(exc), **context)

    # ---- 3. 套用規則 ----
    city = DEMO_CITY if is_demo else (form["city"].strip() or None)
    verdicts = [
        rules.evaluate(h, (place.latitude, place.longitude), config, city)
        for h in data.get("properties", [])
    ]
    verdicts.sort(key=rules.sort_key)

    # ---- 4. 當地貨幣換算 ----
    local_currency = fx.currency_for_country(
        place.country_code, config.get("currency_by_country", {})
    )
    rate = fx.get_rate(local_currency) if local_currency else None

    # ---- 5. 整理給畫面 ----
    fare_used, fare_is_default = rules.get_fare(config, city)
    context.update(
        place=place,
        source=source,
        searched=True,
        fetched_at=data.get("_fetched_at"),
        total=len(verdicts),
        clear=[v for v in verdicts if v.passed and not v.to_confirm],
        needs_check=[v for v in verdicts if v.passed and v.to_confirm],
        rejected=[v for v in verdicts if not v.passed],
        fare_used=fare_used,
        fare_is_default=fare_is_default,
        city_used=city,
        rate=rate,
        ignored=({"destination": form["destination"].strip() or None,
                  "dates": f'{form["check_in"]} ~ {form["check_out"]}'}
                 if is_demo else None),
    )

    # 查成功的地點存起來，下次同一個展館不用再問 OpenStreetMap
    if not is_demo and place.source == "OpenStreetMap":
        geocode.save_venue(form["destination"], place)

    return render_template("index.html", **context)


if __name__ == "__main__":
    print("\n  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000")
    print("  要停止的話，回到終端機按 Ctrl + C")
    print("  第一次使用可以先選「示範模式」，不花 API 額度\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
