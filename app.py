"""
出差飯店搜尋 —— 網頁介面

啟動：
    python app.py
然後打開 http://127.0.0.1:5000
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote_plus

from flask import Flask, render_template, request

import fx
import geocode
import rules
import search
import settings

app = Flask(__name__)

# 示範模式固定用東京國際展示場，因為內建測試資料就是在那裡查的
DEMO_PLACE = geocode.Place(
    35.6298, 139.7954, "Tokyo Big Sight（示範資料）", "示範模式", "jp",
    "Koto, Japan",
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
        default = config.get(_sec, {}).get(_key)
        fields.append({
            "name": name, "label": label, "unit": unit, "desc": desc,
            "is_bool": kind is bool, "value": value,
            # config.toml 的原始預設值。畫面拿它判斷「還原限制條件」要不要啟用 ——
            # 目前的值就是預設值時，那顆按鈕按了也沒事做。
            "default": bool(default) if kind is bool else tidy(default),
        })
    return fields


def empty_form() -> dict:
    """每次重新打開頁面時的空白表單 —— 不預填任何值，避免沿用舊的日期。"""
    return {"destination": "", "city": "", "check_in": "", "check_out": "",
            "mode": MODE_CACHE}


# 中日韓文字。目的地用這些字查，OpenStreetMap 與 Google Hotels 的命中率
# 都明顯比英文差（實測：台北的中文地址查不到、日文地名容易對到別的地方）。
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def validate(form: dict) -> str | None:
    """檢查必填與日期先後。回傳錯誤訊息，沒問題則回傳 None。"""
    destination = form["destination"].strip()
    if form["mode"] != MODE_DEMO:
        if not destination:
            return "請填寫目的地（英文名稱、英文地址，或座標）。"
        # 座標與 Google Maps 連結不受限制，那些本來就不是文字描述
        is_coords = (geocode.parse_coordinates(destination)
                     or geocode.coordinates_from_maps_url(destination))
        if not is_coords and _CJK_RE.search(destination):
            return (
                "目的地請改用英文名稱或英文地址。\n"
                "例如「台北101」請寫 Taipei 101、「東京ビッグサイト」請寫 "
                "Tokyo Big Sight。\n"
                "中日文地名在地圖資料裡的命中率明顯較差，容易查不到或對到別的地方。\n"
                "也可以直接貼 Google Maps 的座標或網址，那不受這個限制。"
            )
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

    def left_fields() -> dict:
        """左邊那些搜尋欄位，使用者剛才填的內容。"""
        return {
            "destination": request.form.get("destination", ""),
            "city": request.form.get("city", ""),
            "check_in": request.form.get("check_in", ""),
            "check_out": request.form.get("check_out", ""),
            "mode": request.form.get("mode", MODE_CACHE),
        }

    def page(**extra):
        """組出畫面需要的全部資料。"""
        config = extra.pop("config", None) or settings.apply(base_config)
        context = {
            "config": config,
            "labels": config.get("labels", {}),
            "short": config.get("short_labels", {}),
            "known_venues": sorted(geocode.load_venues().keys()),
            "known_cities": [c for c in config["taxi_fare"] if c != "default"],
            "settings_fields": settings_fields(base_config,
                                               extra.pop("submitted", None)),
            "using_custom": bool(settings.load()),
            "MODE_DEMO": MODE_DEMO, "MODE_CACHE": MODE_CACHE,
            "MODE_REFRESH": MODE_REFRESH,
        }
        context.update(extra)
        return render_template("index.html", **context)

    # 直接打開頁面：空白表單
    if request.method != "POST":
        return page(form=empty_form())

    # 還原限制條件 —— 只碰右邊，左邊填好的東西要留著
    if action == "reset_settings":
        settings.reset()
        return page(form=left_fields(),
                    saved_note="限制條件已還原成預設值。左邊的搜尋欄位沒有動。")

    form = left_fields()

    # 限制條件跟著搜尋一起送出，不需要另外儲存
    values, problem = settings.parse_form(request.form)
    if problem:
        return page(form=form, settings_error=problem, submitted=request.form)
    # 跟預設一樣就不要留下覆寫檔，免得「已自訂」標記名不副實
    if settings.is_default(base_config, values):
        settings.reset()
    else:
        settings.save(values)
    config = settings.apply(base_config, values)

    problem = validate(form)
    if problem:
        return page(form=form, error=problem, config=config)

    is_demo = form["mode"] == MODE_DEMO

    # ---- 1. 目的地轉座標 ----
    try:
        place = DEMO_PLACE if is_demo else geocode.resolve(form["destination"])
    except LookupError as exc:
        return page(form=form, error=str(exc), config=config)

    # ---- 2. 取得飯店資料 ----
    try:
        if is_demo:
            data, source = search.load_fixture(), "示範資料"
            hotel_query = "Tokyo Big Sight"
        else:
            # 查飯店用「地標名稱」最好 —— Google 懂「Taipei 101 附近的飯店」，
            # 結果會集中在目的地周圍；用城市搜則散到整座城市，
            # 而它只回二十筆左右，近的反而可能被擠掉。
            #
            # 使用者打的是名稱就直接用；打的是座標就用反查到的地標名稱，
            # 絕不能把座標字串丟給 Google，它看不懂
            # （實際踩過：貼東京迪士尼的座標，查出來是美國的露營地）。
            typed_a_name = not (geocode.parse_coordinates(form["destination"])
                                or geocode.coordinates_from_maps_url(form["destination"]))
            hotel_query = (form["destination"].strip() if typed_a_name
                           else (place.area or form["destination"]))
            data, source = search.search_hotels(
                hotel_query, form["check_in"], form["check_out"],
                use_cache=form["mode"] != MODE_REFRESH,
            )
    except (search.MissingKey, search.SearchFailed) as exc:
        return page(form=form, error=str(exc), config=config)

    # ---- 3. 決定費率：城市 → 國家 → 預設，並換算成美金 ----
    city = DEMO_CITY if is_demo else (form["city"].strip() or None)
    raw_fare, fare_source = rules.resolve_fare(config, city, place.country_code)
    fare_used, fare_problem = fx.fare_to_usd(raw_fare)
    if fare_problem:
        # 換不成美金就退回保守預設值。
        # 絕不能把 85 元當成 85 美金 —— 那會高估到荒謬，整頁都變成超標。
        raw_fare = config["taxi_fare"]["default"]
        fare_used, _ = fx.fare_to_usd(raw_fare)
        fare_source = "default"

    # ---- 4. 套用規則 ----
    all_verdicts = [
        rules.evaluate(h, (place.latitude, place.longitude), config,
                       fare_used, fare_source)
        for h in data.get("properties", [])
    ]
    # 不是飯店、或名稱看起來是通舖的，整筆不顯示 ——
    # 連「已排除」都不用出現，那些本來就不是你的選項
    hidden_types = sum(1 for v in all_verdicts if v.wrong_type)
    hidden_dorms = sum(1 for v in all_verdicts if v.looks_like_dorm)
    verdicts = [v for v in all_verdicts
                if not v.wrong_type and not v.looks_like_dorm]
    verdicts.sort(key=rules.sort_key)

    # 比價連結：SerpApi 給的 link 是飯店官網，看不到各家報價與設施清單。
    # 這裡自己組一個 Google Hotels 的查詢網址補上。
    # ⚠️ 日期沒辦法帶進去 —— Google 把日期編碼在一個無法自行組出的參數裡，
    #    所以點進去之後要自己選一次日期。
    area_hint = place.area or ""
    for v in verdicts:
        query = f"{v.name} {area_hint}".strip()
        v.compare_url = ("https://www.google.com/travel/search?q="
                         + quote_plus(query))

    # 防呆：連最近的一間都在幾十公里外，幾乎可以確定是查飯店的字串沒對到目的地
    distances = [v.distance_km for v in verdicts if v.distance_km is not None]
    far_warning = None
    if distances and min(distances) > 50:
        far_warning = (
            f"⚠️ 最近的一間也在 {min(distances):.0f} 公里外，"
            f"這通常表示查飯店用的地名「{hotel_query}」沒有對到你的目的地。"
            f"請換個寫法，或直接輸入展館名稱。"
        )

    # ---- 5. 當地貨幣 ----
    local_currency = fx.currency_for_country(
        place.country_code, config.get("currency_by_country", {}))
    rate = fx.get_rate(local_currency) if local_currency else None
    if rate:
        currency_note = None
    elif not place.country_code:
        currency_note = "無法判斷目的地的國家，所以只顯示美金"
    elif not local_currency:
        currency_note = (f"國碼「{place.country_code}」不在 config.toml 的"
                         f" currency_by_country 對照表裡，所以只顯示美金")
    else:
        currency_note = f"取不到 {local_currency} 匯率（網路或對方服務問題），只顯示美金"

    # 查成功的地點存起來，下次同一個展館不用再問 OpenStreetMap
    if not is_demo and place.source == "OpenStreetMap":
        geocode.save_venue(form["destination"], place)

    return page(
        form=form, config=config, place=place, source=source, searched=True,
        fetched_at=data.get("_fetched_at"), total=len(all_verdicts),
        hidden_types=hidden_types, hidden_dorms=hidden_dorms, hotel_query=hotel_query,
        far_warning=far_warning,
        clear=[v for v in verdicts if v.passed and not v.to_confirm],
        needs_check=[v for v in verdicts if v.passed and v.to_confirm],
        rejected=[v for v in verdicts if not v.passed],
        fare_used=fare_used, fare_raw=raw_fare, fare_source=fare_source,
        fare_problem=fare_problem, city_used=city,
        rate=rate, currency_note=currency_note,
        ignored=({"destination": form["destination"].strip() or None,
                  "dates": f'{form["check_in"]} ~ {form["check_out"]}'}
                 if is_demo else None),
    )


if __name__ == "__main__":
    print("\n  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000")
    print("  要停止的話，回到終端機按 Ctrl + C")
    print("  第一次使用可以先選「示範模式」，不花 API 額度\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
