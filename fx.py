"""
匯率換算 —— 把美金價格同時標示成當地貨幣。

來源：Frankfurter（https://api.frankfurter.dev），免費、不需申請金鑰，
資料來自歐洲央行等官方來源。

重要特性：匯率一天只更新一次（歐洲時間下午四點左右，週末不更新）。
所以程式每天只查一次並存檔，當天重複搜尋不會再連網。
查不到就沿用上次的值，並把日期顯示出來，絕不讓整個工具掛掉。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import requests

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CACHE_PATH = Path(__file__).parent / "fx_cache.json"


class Rate:
    """一組匯率。as_of 是這筆匯率的日期，不一定是今天（週末不更新）。"""

    def __init__(self, base: str, target: str, value: float, as_of: str, stale: bool):
        self.base = base
        self.target = target
        self.value = value
        self.as_of = as_of
        self.stale = stale        # True 代表這次沒連上，用的是舊資料

    def convert(self, amount: float) -> float:
        return amount * self.value

    def format_rate(self) -> str:
        """
        匯率本身一律顯示小數。
        金額可以四捨五入到整數日圓，但匯率不行 ——
        157.25 被印成 157 會讓人以為程式算錯。
        """
        return f"{self.value:,.2f}"

    def format(self, amount: float) -> str:
        """日圓、韓圓這類不用小數的貨幣就不顯示小數。"""
        converted = self.convert(amount)
        if self.target in {"JPY", "KRW", "VND", "IDR", "TWD"}:
            return f"{converted:,.0f}"
        return f"{converted:,.2f}"


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError:
        pass      # 存不了就算了，下次重查，不該因此讓搜尋失敗


def get_rate(target: str, base: str = "USD", *,
             allow_network: bool = True) -> Rate | None:
    """
    取得 1 單位 base 等於多少 target。
    目標與基準相同、或查不到又沒有舊資料時，回傳 None（呼叫端就不顯示換算）。
    """
    target = (target or "").upper()
    base = base.upper()
    if not target or target == base:
        return None

    key = f"{base}_{target}"
    cache = _load_cache()
    today = date.today().isoformat()
    cached = cache.get(key)

    # 今天已經查過就直接用，不再連網
    if cached and cached.get("checked_on") == today:
        return Rate(base, target, cached["value"], cached["as_of"], stale=False)

    if allow_network:
        try:
            res = requests.get(
                FRANKFURTER_URL,
                params={"base": base, "symbols": target},
                timeout=15,
            )
            if res.status_code == 200:
                data = res.json()
                value = data.get("rates", {}).get(target)
                if value:
                    cache[key] = {
                        "value": float(value),
                        "as_of": data.get("date", today),
                        "checked_on": today,
                    }
                    _save_cache(cache)
                    return Rate(base, target, float(value), cache[key]["as_of"],
                                stale=False)
        except (requests.RequestException, ValueError):
            pass      # 失敗就往下用舊資料

    # 連不上時沿用上次的值，並標記為舊資料
    if cached:
        return Rate(base, target, cached["value"], cached["as_of"], stale=True)
    return None


def fare_to_usd(fare: dict) -> tuple[dict, str | None]:
    """
    把用當地幣別寫的費率換算成美金。

    回傳 (美金費率, 問題說明)。換不成時回傳原值與說明，
    由呼叫端決定要不要改用保守預設值 —— 絕不默默把 85 元當成 85 美金用。
    """
    currency = (fare.get("currency") or "USD").upper()
    usd = {
        "base": float(fare["base"]),
        "per_km": float(fare["per_km"]),
        "included_km": float(fare.get("included_km", 0)),
        "currency": "USD",
    }
    if currency == "USD":
        return usd, None

    rate = get_rate(currency)      # 1 美金 = 多少當地幣
    if not rate or not rate.value:
        return fare, f"取不到 {currency} 匯率，無法把費率換算成美金"
    usd["base"] = round(usd["base"] / rate.value, 4)
    usd["per_km"] = round(usd["per_km"] / rate.value, 4)
    return usd, None


def currency_for_country(country_code: str | None, table: dict) -> str | None:
    """用國碼（Nominatim 回傳的 'jp'、'sg' 等）查當地貨幣。"""
    if not country_code:
        return None
    return table.get(country_code.strip().lower())
