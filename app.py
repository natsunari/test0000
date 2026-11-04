"""
出差飯店搜尋 —— 網頁介面

啟動：
    python app.py
然後打開 http://127.0.0.1:5000
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from urllib.parse import quote_plus

from flask import Flask, render_template, request

import auth
import fx
import geocode
import rules
import search
import settings

app = Flask(__name__)

# 部署到網路上時才會生效（靠環境變數 APP_PASSWORD 開關）。
# 自己電腦上跑不會被問密碼。
auth.protect(app)

# 示範模式固定用東京國際展示場，因為內建測試資料就是在那裡查的
DEMO_PLACE = geocode.Place(
    35.6298, 139.7954, "Tokyo Big Sight（示範資料）", "示範模式", "jp",
    "Koto, Japan",
)
DEMO_CITY = "Tokyo"

# 搜尋方式
MODE_CACHE = "cache"        # 有存檔就用存檔
MODE_REFRESH = "refresh"    # 目的地與飯店全部重查

# 示範模式不在畫面上，改用網址參數 ?demo=1 開啟。
# 留著是因為瀏覽器測試需要它 —— 那是唯一能在不連網、不花額度的情況下
# 驗證結果頁渲染的方式。一般使用者不會碰到。
MODE_DEMO = "demo"


def _city_options(config: dict) -> list[dict]:
    """
    城市下拉選單的內容，A 到 Z 排序。

    費率標示要同時看城市與國家兩層 —— 台北的費率填在國家層級（tw），
    只看城市層級的話它會顯示成「沒有費率」，看起來像資料沒填進去。
    """
    city_fares = {c for c in config.get("taxi_fare", {}) if c != "default"}
    country_fares = set(config.get("taxi_fare_by_country", {}))
    city_country = config.get("ui", {}).get("cities", {})

    names = city_fares | set(city_country)
    options = []
    for name in sorted(names, key=str.casefold):
        country = city_country.get(name)
        if name in city_fares:
            note = "已有費率"
        elif country and country in country_fares:
            note = "依國家費率"
        else:
            note = ""
        options.append({"name": name, "note": note})
    return options


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
    """
    每次重新打開頁面時的空白表單 —— 不預填任何值，避免沿用舊的日期。

    預設是「重查」而不是「搜尋」：存檔沒有有效期限，一個月前查的房價
    和空房會原封不動拿出來。預設讀存檔的話，使用者不會意識到自己看的
    是舊資料。要省額度的人會自己改選「搜尋」。
    """
    return {"destination": "", "city": "", "check_in": "", "check_out": "",
            "mode": MODE_REFRESH}


# 中日韓文字。目的地用這些字查，OpenStreetMap 與 Google Hotels 的命中率
# 都明顯比英文差（實測：台北的中文地址查不到、日文地名容易對到別的地方）。
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def city_mismatch_warning(config: dict, city: str | None,
                          country_code: str | None) -> str | None:
    """
    城市欄位和目的地是不是在講不同的國家。

    實際踩過：目的地貼了東京的座標、城市欄位填 Beijing，
    程式就拿北京的計程車費率去算東京的距離，而畫面上一切看起來正常。
    這種矛盾一定要講出來，而且寧可忽略城市欄位，不要用錯的費率。

    城市不在對照表裡（使用者自己打的）時無從比對，回傳 None。
    """
    city_country = config.get("ui", {}).get("cities", {}).get(city or "")
    if not city_country or not country_code:
        return None
    if city_country == country_code:
        return None
    return (f"城市欄位填的是「{city}」（{city_country.upper()}），"
            f"但目的地解析出來在 {country_code.upper()}。"
            f"兩者不一致，已忽略城市欄位改用國家費率 —— "
            f"請確認目的地或城市是不是填錯了。")


def hotel_search_query(destination: str, place, city: str | None = None
                       ) -> str | None:
    """
    決定要送給 Google Hotels 的查詢字串。查不出可用的字串時回傳 None。

    目標：不論使用者輸入「Taipei 101」、英文地址，還是經緯度，
    都要解析到同一個地標，才會找到同一批附近的飯店。

    優先序：
      1. 解析出來的地標名稱 —— 三種輸入都會走到同一個答案
      2. 使用者打的文字 —— 他打的本來就是名稱時最準
      3. 「區, 城市, 國家」 —— 反查到的地區
      4. 城市欄位 —— 連地區都反查不到時，至少還有使用者自己填的城市

    兩條硬規則：
      * 座標字串和網址永遠不能送出去。Google 看到座標會憑字面亂猜 ——
        實際踩過一次，結果出現在 12000 公里外的美國露營地。
        寧可回 None 讓畫面講清楚，也不要送出去拿回一堆錯的東西。
      * 含中日韓文字的候選先跳過。Google Hotels 用英文查命中率明顯較好，
        而 Nominatim 常常回傳當地語言的名稱（例如「台北101」）。
        全部候選都是中日韓文字時才退而求其次用它 —— 總比沒有好。
    """
    destination = (destination or "").strip()
    city = (city or "").strip()
    typed_a_name = not _unusable_as_query(destination)

    def with_area(candidate: str) -> str:
        """
        補上「城市, 國家」把查詢釘在正確的地理範圍。

        這是最後一道保險。地標判斷失誤時（例如把地址上的餃子店
        "Harajuku Gyoza" 當成地標），Google 會憑字面跑到東京去，
        結果出現在 18939 公里外。帶上城市就不會離開目的地所在的地區。
        """
        area = place.area
        if not area or area.lower() in candidate.lower():
            return candidate
        # 使用者自己打的字裡已經有城市名就不重複加
        if any(part.strip().lower() in candidate.lower()
               for part in area.split(",") if part.strip()):
            return candidate
        return f"{candidate}, {area}"

    candidates = [place.landmark,
                  destination if typed_a_name else None,
                  place.area,
                  city or None]
    # 先挑沒有中日韓文字的
    for candidate in candidates:
        if candidate and not _unusable_as_query(candidate) \
                and not _CJK_RE.search(candidate):
            return with_area(candidate)
    # 全部都含中日韓文字時，用有東西的那個
    for candidate in candidates:
        if candidate and not _unusable_as_query(candidate):
            return with_area(candidate)
    return None


def _unusable_as_query(text: str) -> bool:
    """
    這串字不能當成查詢送給 Google Hotels。

    座標和網址都是「給程式看的」，Google 只會憑字面猜，猜出來的東西
    跟使用者的目的地沒有關係，而且畫面上看起來一切正常。
    """
    text = (text or "").strip()
    if not text:
        return True
    if geocode.parse_coordinates(text) or geocode.coordinates_from_maps_url(text):
        return True
    lowered = text.lower()
    return lowered.startswith(("http://", "https://", "www.")) or "://" in lowered


def validate(form: dict, is_demo: bool = False) -> str | None:
    """檢查必填與日期先後。回傳錯誤訊息，沒問題則回傳 None。"""
    destination = form["destination"].strip()
    if not is_demo:
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
    # 示範模式只能從網址參數開啟，畫面上沒有這個選項
    is_demo = request.args.get("demo") == "1"

    def left_fields() -> dict:
        """左邊那些搜尋欄位，使用者剛才填的內容。"""
        return {
            "destination": request.form.get("destination", ""),
            "city": request.form.get("city", ""),
            "check_in": request.form.get("check_in", ""),
            "check_out": request.form.get("check_out", ""),
            "mode": request.form.get("mode", MODE_REFRESH),
        }

    def page(**extra):
        """組出畫面需要的全部資料。"""
        config = extra.pop("config", None) or settings.apply(base_config)
        context = {
            "config": config,
            "labels": config.get("labels", {}),
            "short": config.get("short_labels", {}),
            # 下拉建議：先列已有費率的（標示出來），再列其他常見展覽城市。
            # 清單只是方便選取，使用者照樣可以自己打。
            "city_options": _city_options(config),
            "settings_fields": settings_fields(base_config,
                                               extra.pop("submitted", None)),
            "using_custom": bool(settings.load()),
            "MODE_CACHE": MODE_CACHE, "MODE_REFRESH": MODE_REFRESH,
            "demo": is_demo,
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

    problem = validate(form, is_demo)
    if problem:
        return page(form=form, error=problem, config=config)

    # ---- 1. 目的地轉座標 ----
    try:
        place = DEMO_PLACE if is_demo else geocode.resolve(
            form["destination"], refresh=form["mode"] == MODE_REFRESH)
    except LookupError as exc:
        return page(form=form, error=str(exc), config=config)

    # ---- 2. 取得飯店資料 ----
    retried_from = None          # 第一次查 0 筆、改用城市重查時，記下原本的字串
    try:
        if is_demo:
            data, source = search.load_fixture(), "示範資料"
            hotel_query = "Tokyo Big Sight"
        else:
            hotel_query = hotel_search_query(form["destination"], place,
                                             form["city"])
            if not hotel_query:
                # 唯一會走到這裡的情況：輸入是座標或網址，而且反查不到
                # 任何地名、城市欄位也空白。送座標去 Google 只會拿回
                # 離題幾千公里的結果，所以寧可停在這裡把話講清楚。
                return page(
                    form=form, config=config,
                    error="這組座標反查不到任何地名，所以沒辦法去查飯店。"
                          "請在「城市」欄填上英文城市名，"
                          "或把目的地改成展館名稱（例如 ICC Sydney）。")

            def run(query):
                return search.search_hotels(
                    query, form["check_in"], form["check_out"],
                    use_cache=form["mode"] != MODE_REFRESH,
                    # 上限先送給 Google，超標的就不會占掉那 20 個名額
                    max_price=config["budget"]["hotel_max_per_night_usd"],
                    pages=config.get("search", {}).get("pages", 2),
                )

            data, source = run(hotel_query)

            # 查到 0 筆就退一步用「城市, 國家」再查一次。
            #
            # 會發生在查詢字串指到某一間特定飯店的時候 —— 問 Google Hotels
            # 「Sofitel Sydney Darling Harbour 附近有哪些飯店」，它回 0 筆。
            # 研討會本來就常常辦在飯店裡，使用者直接打飯店名是很合理的輸入，
            # 不該換來一片空白。多花一次額度，但只在完全查不到的時候才花。
            if (not data.get("properties") and place.area
                    and hotel_query != place.area):
                retry_data, retry_source = run(place.area)
                if retry_data.get("properties"):
                    retried_from = hotel_query
                    data, source = retry_data, retry_source
                    hotel_query = place.area
    except (search.MissingKey, search.SearchFailed) as exc:
        return page(form=form, error=str(exc), config=config)

    # ---- 3. 決定費率：城市 → 國家 → 預設，並換算成美金 ----
    city = DEMO_CITY if is_demo else (form["city"].strip() or None)

    # 城市欄位和目的地可能講的是不同國家（例如目的地貼了東京的座標，
    # 城市卻填 Beijing）。那時候用北京的費率去算東京的距離完全沒有意義，
    # 而且不講的話畫面看起來一切正常。寧可忽略城市、退回國家費率。
    city_mismatch = city_mismatch_warning(config, city, place.country_code)
    if city_mismatch:
        city = None

    raw_fare, fare_source = rules.resolve_fare(config, city, place.country_code)
    fare_used, fare_problem = fx.fare_to_usd(raw_fare)
    if fare_problem:
        # 換不成美金就退回保守預設值。
        # 絕不能把 85 元當成 85 美金 —— 那會高估到荒謬，整頁都變成超標。
        raw_fare = config["taxi_fare"]["default"]
        fare_used, _ = fx.fare_to_usd(raw_fare)
        # 標成 fx_failed 而不是 default —— 這個地區其實有費率，
        # 只是換不了匯。說成「還沒填費率」會讓人跑去填已經填過的東西。
        fare_source = "fx_failed"

    # ---- 4. 套用規則 ----
    all_verdicts = [
        rules.evaluate(h, (place.latitude, place.longitude), config,
                       fare_used, fare_source)
        for h in data.get("properties", [])
    ]
    # 不是飯店、或名稱／簡介研判是通舖的，整筆不顯示 ——
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

    # 統計淘汰原因，並記下實際的價格區間。
    # 沒有任何結果時，光說「沒有符合的」毫無幫助 ——
    # 要讓人看得出來是哪一條規則刷掉的、該調哪個數字。
    breakdown = Counter(
        rules.CATEGORIES.get(v.reject_category, "其他")
        for v in all_verdicts if not v.passed and v.reject_category
    )
    prices = sorted(v.price_usd for v in all_verdicts if v.price_usd is not None)
    price_range = ((prices[0], prices[len(prices) // 2], prices[-1])
                   if prices else None)

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
    # 匯率失敗會同時影響「當地貨幣」和「計程車費率」。
    # 以前這兩件事各講一次、費率那邊還講兩次，同一個原因被重複三遍。
    if not rate and fare_source == "fx_failed" and local_currency:
        fx_warning = (
            f"取不到 {local_currency} 匯率，所以當地貨幣沒有顯示，"
            f"計程車費率也改用保守估計。可以跑 python check_fx.py 檢查哪個來源有問題。")
        currency_note = None
    else:
        fx_warning = None

    if rate or fx_warning:
        currency_note = None
    elif not place.country_code:
        currency_note = "無法判斷目的地的國家，所以只顯示美金"
    elif not local_currency:
        currency_note = (f"國碼「{place.country_code}」不在 config.toml 的"
                         f" currency_by_country 對照表裡，所以只顯示美金")
    else:
        currency_note = (f"取不到 {local_currency} 匯率，只顯示美金。"
                         f"可以跑 python check_fx.py 檢查。")

    # 查成功的地點存起來，下次同一個展館不用再問 OpenStreetMap
    if not is_demo and place.source == "OpenStreetMap":
        geocode.save_venue(form["destination"], place)

    return page(
        form=form, config=config, place=place, source=source, searched=True,
        fetched_at=data.get("_fetched_at"), total=len(all_verdicts),
        pages_fetched=data.get("_pages_fetched"),
        hidden_types=hidden_types, hidden_dorms=hidden_dorms,
        breakdown=breakdown.most_common(), price_range=price_range, hotel_query=hotel_query,
        retried_from=retried_from,
        far_warning=far_warning, city_mismatch=city_mismatch,
        clear=[v for v in verdicts if v.passed and not v.to_confirm],
        needs_check=[v for v in verdicts if v.passed and v.to_confirm],
        rejected=[v for v in verdicts if not v.passed],
        fare_used=fare_used, fare_raw=raw_fare, fare_source=fare_source,
        fare_problem=fare_problem, city_used=city,
        rate=rate, currency_note=currency_note, fx_warning=fx_warning,
        ignored=({"destination": form["destination"].strip() or None,
                  "dates": f'{form["check_in"]} ~ {form["check_out"]}'}
                 if is_demo else None),
    )


if __name__ == "__main__":
    print("\n  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000")
    print("  要停止的話，回到終端機按 Ctrl + C")
    print("  第一次使用可以先選「示範模式」，不花 API 額度\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
