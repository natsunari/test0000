"""
密碼保護 —— 只有部署到網路上時才會啟用。

為什麼需要：部署出去的網址就是公開網址。沒有密碼的話，任何拿到或猜到
網址的人都能用，而且會花掉你那 250 次／月的 API 額度。

怎麼啟用：在部署平台設一個環境變數 APP_PASSWORD。
沒設的話完全不生效 —— 你在自己電腦上跑的時候不會被問密碼。

用的是瀏覽器內建的帳號密碼視窗（HTTP Basic Auth）。
它很陽春，但剛好夠用：不用寫登入頁、不用存 session，
而且因為部署平台一律走 HTTPS，密碼在傳輸過程中是加密的。

⚠️ 這擋的是「不小心看到網址的人」，不是有心人士。
   不要把真正機密的東西放進這個工具。
"""

from __future__ import annotations

import hmac
import os

from flask import Response, request

ENV_VAR = "APP_PASSWORD"
# 帳號固定，只有密碼要記。多一個欄位要記只會讓人把它寫在便利貼上。
USERNAME = "team"


def required_password() -> str | None:
    """沒設環境變數就回傳 None，代表不啟用密碼。"""
    value = (os.environ.get(ENV_VAR) or "").strip()
    return value or None


def _ok(auth, expected: str) -> bool:
    if not auth or not auth.password:
        return False
    # compare_digest：比對時間固定，不會因為「前幾個字對了」而變慢。
    # 一般比對會提早結束，有心人可以從回應時間一個字一個字試出密碼。
    return (hmac.compare_digest(auth.username or "", USERNAME)
            and hmac.compare_digest(auth.password, expected))


# realm 會原封不動放進 HTTP 標頭，而標頭只能是 latin-1 ——
# 寫中文的話整個回應在編碼階段就炸掉（500），而且只有「密碼錯誤」
# 那條路會炸，密碼對的時候完全正常，很容易就這樣上線了。
_REALM = "Business Trip Hotel Search"

_DENIED_HTML = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>需要密碼</title></head>
<body style="font-family:system-ui,sans-serif;padding:40px;line-height:1.7">
<h1 style="font-size:20px">需要密碼才能使用</h1>
<p>帳號是 <b>team</b>，密碼請跟管理這個網站的人拿。</p>
<p>重新整理這一頁就會再問一次。</p>
</body></html>"""


def _ask() -> Response:
    return Response(
        _DENIED_HTML, 401,
        {"WWW-Authenticate": f'Basic realm="{_REALM}", charset="UTF-8"',
         "Content-Type": "text/html; charset=utf-8"},
    )


def protect(app) -> None:
    """掛上密碼檢查。APP_PASSWORD 沒設定時什麼都不做。"""

    @app.before_request
    def _check():
        expected = required_password()
        if expected is None:
            return None            # 本機使用，不問密碼
        if _ok(request.authorization, expected):
            return None
        return _ask()
