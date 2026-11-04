"""
使用者在網頁上調整的限制值。

為什麼不直接改寫 config.toml：
    那個檔案裡有大量中文說明註解，程式化改寫會把註解全部弄不見。
    所以分成兩層 ——
        config.toml   = 預設值 + 說明文件（會進版控，不會被程式改動）
        settings.json = 你在網頁上改過的值（不進版控，每個人自己的）
    讀取時把後者疊在前者上面。按「還原預設」就是把 settings.json 刪掉。
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"

# 可以在網頁上調整的項目：
#   表單欄位名稱 -> (config 的區塊, 鍵名, 型別, 中文標籤, 單位, 說明)
# 刻意不放進來的項目：走路門檻、道路彎繞倍數、價格緩衝。
# 那些是「怎麼計算」的參數，不是公司規範，放上去只會讓人每次搜尋前猶豫。
# 要調整的話改 config.toml。
EDITABLE = {
    # 顯示順序就是這裡的順序。下限在前、上限在後，讀起來才像一個區間。
    "hotel_min_per_night_usd":
        ("budget", "hotel_min_per_night_usd", float, "住宿每晚下限", "USD",
         "低於當地正常飯店行情的多半是通舖。"),
    "hotel_max_per_night_usd":
        ("budget", "hotel_max_per_night_usd", float, "住宿每晚上限", "USD",
         ""),
    "taxi_max_one_way_usd":
        ("budget", "taxi_max_one_way_usd", float, "單趟交通上限", "USD",
         "飯店到目的地的單程車資上限"),
    "require_availability":
        ("availability", "require", bool, "只列出有空房的", "",
         "沒有可訂價格的飯店直接排除"),
    "assume_air_conditioning":
        ("assume_when_unknown", "air_conditioning", bool, "沒標冷氣時推定為有", "",
         "飯店幾乎都有冷氣，資料沒寫多半只是 Google 沒收錄"),
    "assume_elevator":
        ("assume_when_unknown", "elevator", bool, "沒標電梯時推定為有", "",
         "多數飯店有電梯；明確標示沒有的仍會被淘汰"),
}

# 合理範圍，避免打錯字造成荒謬的結果（例如上限打成 1800）
LIMITS = {
    "hotel_max_per_night_usd": (1, 2000),
    "hotel_min_per_night_usd": (0, 1000),
    "taxi_max_one_way_usd": (1, 500),
}


def load() -> dict:
    """讀取使用者的覆寫值。沒有或壞掉都回傳空的。"""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save(values: dict) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def reset() -> None:
    """還原成 config.toml 的預設值。"""
    SETTINGS_PATH.unlink(missing_ok=True)


def apply(config: dict, overrides: dict | None = None) -> dict:
    """把覆寫值疊到 config 上。config 本身不會被改動。"""
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in config.items()}
    for name, value in (overrides if overrides is not None else load()).items():
        spec = EDITABLE.get(name)
        if not spec:
            continue
        section, key, *_ = spec
        merged.setdefault(section, {})[key] = value
    return merged


def current(config: dict) -> dict:
    """目前生效的值（預設值疊上覆寫），用來填網頁上的輸入框。"""
    merged = apply(config)
    out = {}
    for name, (section, key, kind, *_rest) in EDITABLE.items():
        value = merged.get(section, {}).get(key)
        out[name] = bool(value) if kind is bool else value
    return out


def is_default(config: dict, values: dict) -> bool:
    """這組值是不是就等於 config.toml 的預設值。

    是的話就不要寫 settings.json —— 否則「已自訂」標記會亮著，
    但其實跟預設一模一樣，「還原限制條件」也會變成按了沒事做。
    """
    for name, (section, key, kind, *_rest) in EDITABLE.items():
        default = config.get(section, {}).get(key)
        current = values.get(name)
        if kind is bool:
            if bool(default) != bool(current):
                return False
        elif float(default) != float(current):
            return False
    return True


def parse_form(form) -> tuple[dict, str | None]:
    """
    把網頁表單轉成覆寫值。
    回傳 (值, 錯誤訊息)。任何一個欄位不合理就整批不存，並說明哪裡有問題。
    """
    values = {}
    for name, (_section, _key, kind, label, unit, _desc) in EDITABLE.items():
        if kind is bool:
            values[name] = form.get(name) == "on"
            continue
        raw = (form.get(name) or "").strip()
        if raw == "":
            return {}, f"「{label}」不能空白。"
        try:
            number = float(raw)
        except ValueError:
            return {}, f"「{label}」必須是數字，你填的是「{raw}」。"
        low, high = LIMITS[name]
        if not (low <= number <= high):
            return {}, f"「{label}」要在 {low} 到 {high} {unit} 之間，你填的是 {number}。"
        values[name] = number

    if values["hotel_min_per_night_usd"] >= values["hotel_max_per_night_usd"]:
        return {}, "「住宿每晚下限」必須小於上限，否則不會有任何飯店符合。"
    return values, None
