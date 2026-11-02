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
EDITABLE = {
    "hotel_max_per_night_usd":
        ("budget", "hotel_max_per_night_usd", float, "住宿每晚上限", "USD",
         "公司規範的房價上限"),
    "taxi_max_one_way_usd":
        ("budget", "taxi_max_one_way_usd", float, "單趟交通上限", "USD",
         "飯店到目的地的單程車資上限"),
    "taxi_max_per_day_usd":
        ("budget", "taxi_max_per_day_usd", float, "每日交通上限", "USD",
         "通常是單趟的兩倍"),
    "walking_max_km":
        ("distance", "walking_max_km", float, "走路可達門檻", "公里",
         "這個距離內視為不需搭車，交通費算 0"),
    "road_detour_factor":
        ("distance", "road_detour_factor", float, "道路彎繞倍數", "倍",
         "直線距離換算實際路程，一般市區 1.3"),
    "buffer_percent":
        ("exchange_rate", "buffer_percent", float, "價格緩衝", "%",
         "吸收刷卡手續費與匯率波動，寧可保守"),
    "require_availability":
        ("availability", "require", bool, "只列出有空房的", "",
         "沒有可訂價格的飯店直接排除"),
    "assume_air_conditioning":
        ("assume_when_unknown", "air_conditioning", bool, "沒標冷氣時推定為有", "",
         "飯店幾乎都有冷氣，資料沒寫多半只是 Google 沒收錄"),
    "assume_elevator":
        ("assume_when_unknown", "elevator", bool, "沒標電梯時推定為有", "",
         "小型飯店確實可能沒有，建議保持關閉以便自己確認"),
}

# 合理範圍，避免打錯字造成荒謬的結果（例如上限打成 1800）
LIMITS = {
    "hotel_max_per_night_usd": (1, 2000),
    "taxi_max_one_way_usd": (1, 500),
    "taxi_max_per_day_usd": (1, 1000),
    "walking_max_km": (0.1, 10),
    "road_detour_factor": (1.0, 3.0),
    "buffer_percent": (0, 50),
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

    if values["taxi_max_per_day_usd"] < values["taxi_max_one_way_usd"]:
        return {}, "「每日交通上限」不能小於「單趟交通上限」。"
    return values, None
