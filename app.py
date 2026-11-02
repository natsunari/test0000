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
import settings

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


def settings_fields(config: dict, submitted=None) -> list[dict]:
    """
    整理成畫面好填的格式：目前生效的值 + 標籤 + 說明。

    submitted 有值時（儲存失敗的情況）改用使用者剛才填的內容，
    否則他要重打一次才能修正打錯的那一欄。
    """
    live = settings.current(config)

    def tidy(value):
        """
        180.0 顯示成 180。

        config.toml 存的是整數 180，settings.json 存的是浮點數 180.0，
        兩邊印出來不一樣會讓人以為自己改過東西。
        """
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    fields = []
    for name, (_sec, _key, kind, label, unit, desc) in settings.EDITABLE.items():
        if submitted is not None:
            value = (submitted.get(name) == "on" if kind is bool
                     else submitted.get(name, live[name]))
        else:
            value = live[name]
        if kind is not bool:
            value = tidy(value)
        fields.append({
            "name": name, "label": label, "unit": unit, "desc": desc,
            "is_bool": kind is bool, "value": value,
        })
    return fields


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
    base_config = rules.load_config()
    action = request.form.get("action", "search")

    # 儲存／還原限制設定
    saved_note = None
    if request.method == "POST" and action == "reset_settings":
        settings.reset()
        saved_note = "已還原成 config.toml 的預設值。"
        action = "show"
    elif request.method == "POST" and action == "save_settings":
        values, problem = settings.parse_form(request.form)
        if problem:
            config = settings.apply(base_config)
            kept = {
                "destination": request.form.get("destination", ""),
                "city": request.form.get("city", ""),
                "check_in": request.form.get("check_in", ""),
                "check_out": request.form.get("check_out", ""),
                "mode": request.form.get("mode", MODE_CACHE),
            }
            return render_template(
                "index.html", form=kept, settings_error=problem,
                config=config, labels=config.get("labels", {}),
                short=config.get("short_labels", {}),
                known_venues=sorted(geocode.load_venues().keys()),
                known_cities=[c for c in config["taxi_fare"] if c != "default"],
                settings_fields=settings_fields(base_config, request.form),
                using_custom=bool(settings.load()),
                MODE_DEMO=MODE_DEMO, MODE_CACHE=MODE_CACHE, MODE_REFRESH=MODE_REFRESH,
            )
        settings.save(values)
        saved_note = "限制已更新。下次搜尋就會套用新的值。"
        action = "show"

    config = settings.apply(base_config)

    context = {
        "config": config,
        "settings_fields": settings_fields(base_config),
        "saved_note": saved_note,
        "using_custom": bool(settings.load()),
        "labels": config.get("labels", {}),
        "short": config.get("short_labels", {}),
        "known_venues": sorted(geocode.load_venues().keys()),
        "known_cities": [c for c in config["taxi_fare"] if c != "default"],
        "MODE_DEMO": MODE_DEMO,
        "MODE_CACHE": MODE_CACHE,
        "MODE_REFRESH": MODE_REFRESH,
    }

    # 直接打開頁面（GET）、或剛存完設定時，一律給空白表單
    if request.method != "POST" or action == "show":
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

    # 匯率顯示不出來時要說明原因，否則使用者只會覺得「怎麼沒有」
    if rate:
        currency_note = None
    elif not place.country_code:
        currency_note = "無法判斷目的地的國家，所以只顯示美金"
    elif not local_currency:
        currency_note = (f"國碼「{place.country_code}」不在 config.toml 的"
                         f" currency_by_country 對照表裡，所以只顯示美金")
    else:
        currency_note = f"取不到 {local_currency} 匯率（網路或對方服務問題），只顯示美金"

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
        currency_note=currency_note,
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
