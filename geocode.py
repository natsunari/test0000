"""
把「目的地」轉成座標。使用者可以輸入座標，也可以輸入地址或地標名稱。

座標 → 直接使用，不連網。
地址 → 用 OpenStreetMap 的 Nominatim 查詢。

⚠️ Nominatim 使用政策（https://operations.osmfoundation.org/policies/nominatim/）
   這是靠捐贈營運、容量有限的公共服務，本程式據此遵守下列規定：
     * 每秒最多 1 次請求 —— 由 _throttle() 強制
     * 必須送出可識別本應用的 User-Agent —— 缺少會被回 403
     * 禁止批次查詢與輸入即時建議（search-as-you-type）—— 本程式只在使用者
       按下按鈕時查一次
     * 應快取結果 —— 查過的地點存進 venues.json，不重複查
     * 顯示資料時須標註 © OpenStreetMap contributors —— 畫面上有標
   若未來用量變大，官方建議自架 Nominatim 或改用商業服務。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# 必須能識別這個應用程式。請勿改成通用字串，那會被 Nominatim 限流或封鎖。
USER_AGENT = (
    "BusinessTripHotelFilter/0.1 "
    "(personal business-travel tool; contact via github.com/natsunari/test0000)"
)

VENUES_PATH = Path(__file__).parent / "venues.json"

# 遵守每秒 1 次的限制
_MIN_INTERVAL_SECONDS = 1.1
_last_request_at = 0.0

# 「35.6298, 139.7954」「35.6298 139.7954」「35.6298,139.7954」都接受
_COORD_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)


@dataclass
class Place:
    latitude: float
    longitude: float
    label: str          # 顯示給使用者確認用
    source: str         # "座標輸入" / "已存地點" / "OpenStreetMap"


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """
    看看輸入是不是一組座標。是就回傳 (緯度, 經度)，不是就回傳 None。
    緯度必須在 -90~90、經度 -180~180，否則視為不是座標。
    """
    m = _COORD_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def load_venues(path: Path | None = None) -> dict:
    """讀取已存過的地點。檔案不存在或壞掉都回傳空的，不讓程式掛掉。"""
    p = path or VENUES_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_venue(key: str, place: Place, path: Path | None = None) -> None:
    """把確認過的地點存起來，下次同一個展館就不用再查。"""
    p = path or VENUES_PATH
    venues = load_venues(p)
    venues[key.strip().lower()] = {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "label": place.label,
    }
    p.write_text(json.dumps(venues, ensure_ascii=False, indent=2), encoding="utf-8")


def _throttle() -> None:
    """確保距離上次請求至少間隔 1.1 秒，遵守 Nominatim 的每秒 1 次限制。"""
    global _last_request_at
    wait = _MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def resolve(text: str, *, allow_network: bool = True,
            venues_path: Path | None = None) -> Place:
    """
    把使用者輸入的目的地轉成座標。

    順序：座標 → 已存地點 → 連網查詢。
    查不到會丟出 LookupError，呼叫端負責顯示友善訊息。
    """
    text = (text or "").strip()
    if not text:
        raise LookupError("請輸入目的地")

    # 1. 直接是座標
    coords = parse_coordinates(text)
    if coords:
        return Place(coords[0], coords[1],
                     f"座標 {coords[0]}, {coords[1]}", "座標輸入")

    # 2. 查過並存起來的地點（也滿足 Nominatim「應快取」的要求）
    saved = load_venues(venues_path).get(text.lower())
    if saved:
        return Place(saved["latitude"], saved["longitude"],
                     saved["label"], "已存地點")

    if not allow_network:
        raise LookupError(f"「{text}」不在已存地點裡，而目前是離線模式")

    # 3. 問 Nominatim
    _throttle()
    try:
        res = requests.get(
            NOMINATIM_URL,
            params={"q": text, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise LookupError(f"查詢地址時連線失敗：{exc}") from exc

    if res.status_code == 403:
        raise LookupError(
            "OpenStreetMap 拒絕了這次查詢（403）。"
            "通常是 User-Agent 問題，請見 geocode.py 開頭的政策說明。"
        )
    if res.status_code == 429:
        raise LookupError("查詢太頻繁被 OpenStreetMap 限流，請稍等幾秒再試。")
    if res.status_code != 200:
        raise LookupError(f"查詢地址失敗（HTTP {res.status_code}）")

    results = res.json()
    if not results:
        raise LookupError(
            f"找不到「{text}」。試試看更完整的名稱或地址，"
            f"或直接從 Google Maps 複製座標貼進來（例如 35.6298, 139.7954）。"
        )

    top = results[0]
    return Place(float(top["lat"]), float(top["lon"]),
                 top.get("display_name", text), "OpenStreetMap")
