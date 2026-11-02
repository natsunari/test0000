"""
向 SerpApi 查詢飯店，並把結果存在本機。

兩個重點：

1. 金鑰來源有兩種，程式會自動擇一：
     * 作業系統的環境變數 SERPAPI_KEY（部署到主機時用這個）
     * 專案裡的 .env 檔（在自己電腦上開發時用這個）
   所以同一份程式碼在你的 Mac 和在雲端主機上都能跑，不用改任何一行。

2. 查過的結果會存進 cache/，相同條件再查就直接讀檔。
   這很重要 —— 免費方案每月只有 250 次，而調整篩選條件、重看結果
   這些動作都不該再花額度。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
CACHE_DIR = BASE_DIR / "cache"
FIXTURE_PATH = BASE_DIR / "fixtures" / "tokyo_sample.json"

SERPAPI_URL = "https://serpapi.com/search"


class MissingKey(Exception):
    """找不到 API 金鑰。"""


class SearchFailed(Exception):
    """查詢失敗，訊息已經是可以直接顯示給使用者的中文。"""


def load_api_key() -> str:
    """
    先看環境變數，再看 .env 檔。
    兩個都沒有就丟出 MissingKey，由呼叫端決定要怎麼提示。
    """
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if key:
        return key

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "SERPAPI_KEY":
                value = value.strip().strip('"').strip("'")
                if value and not value.startswith("把這一整串"):
                    return value

    raise MissingKey(
        "找不到 SerpApi 金鑰。\n"
        "在自己電腦上：執行 cp .env.example .env，再把金鑰填進 .env。\n"
        "部署到主機時：在主機的環境變數設定裡加入 SERPAPI_KEY。"
    )


def _cache_path(params: dict) -> Path:
    """用查詢條件算出一個固定的檔名，同樣條件就會對到同一個檔。"""
    signature = json.dumps(
        {k: params[k] for k in sorted(params) if k != "api_key"},
        ensure_ascii=False, sort_keys=True,
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def search_hotels(query: str, check_in: str, check_out: str, *,
                  currency: str = "USD", adults: int = 1,
                  use_cache: bool = True,
                  allow_network: bool = True) -> tuple[dict, str]:
    """
    查詢飯店。

    回傳 (資料, 來源)，來源是 "快取" 或 "SerpApi"。
    use_cache=False 可強制重查（例如你想要最新的空房狀況）。
    allow_network=False 則只讀快取，絕不消耗額度。
    """
    params = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults,
        "currency": currency,
        "gl": "us",
        "hl": "en",
    }

    path = _cache_path(params)
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), "快取"
        except json.JSONDecodeError:
            pass  # 快取壞了就當作沒有，重新查

    if not allow_network:
        raise SearchFailed("目前是離線模式，而這組條件沒有快取過。")

    params["api_key"] = load_api_key()
    try:
        res = requests.get(SERPAPI_URL, params=params, timeout=60)
    except requests.RequestException as exc:
        raise SearchFailed(f"連線 SerpApi 失敗：{exc}") from exc

    if res.status_code == 401:
        raise SearchFailed("SerpApi 金鑰無效（401），請確認 .env 裡的金鑰。")
    if res.status_code == 429:
        raise SearchFailed(
            "SerpApi 額度用完或查詢太頻繁（429）。"
            "免費方案每月 250 次、每小時 50 次。"
        )
    if res.status_code != 200:
        raise SearchFailed(f"SerpApi 回應失敗（HTTP {res.status_code}）")

    data = res.json()
    if data.get("error"):
        raise SearchFailed(f"SerpApi 回報錯誤：{data['error']}")

    data["_fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data, "SerpApi"


def load_fixture() -> dict:
    """示範模式用的資料。不連網、不花額度。"""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
