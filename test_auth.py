"""
密碼保護的測試。

執行：python test_auth.py

為什麼值得一個獨立的測試檔：這是唯一一道擋住「網址外流就被用光額度」的
關卡，而且它有一個特性很危險 —— 密碼正確的那條路很好測、也很容易通過，
出事的是密碼錯誤那條路。實際踩過：realm 寫了中文，HTTP 標頭只能是
latin-1，結果 401 整個變成 500，而密碼對的時候完全正常。
"""

import os

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    print(f"  ✅ {description}")
    passed += 1


def client(password: str | None):
    """用指定的 APP_PASSWORD 重新載入 app，回傳測試用 client。"""
    if password is None:
        os.environ.pop("auth_pw_placeholder", None)
        os.environ.pop("APP_PASSWORD", None)
    else:
        os.environ["APP_PASSWORD"] = password
    import app
    return app.app.test_client()


def basic(user: str, pw: str) -> dict:
    import base64
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


print("--- 沒設 APP_PASSWORD：自己電腦上跑，不該被問密碼 ---")
c = client(None)
check(c.get("/").status_code == 200, "直接打開就看得到畫面")
check(c.get("/?demo=1").status_code == 200, "示範模式也不用密碼")

print("\n--- 設了 APP_PASSWORD：部署到網路上，一律要密碼 ---")
PW = "s3cret-for-test"
c = client(PW)
check(c.get("/").status_code == 401, "沒帶密碼 → 401")
check(c.get("/", headers=basic("team", "wrong")).status_code == 401,
      "密碼錯 → 401")
check(c.get("/", headers=basic("wronguser", PW)).status_code == 401,
      "帳號錯 → 401")
check(c.get("/", headers=basic("team", "")).status_code == 401,
      "空密碼 → 401")
check(c.get("/", headers=basic("team", PW)).status_code == 200,
      "帳號密碼都對 → 200")

print("\n--- POST（真正會花 API 額度的那個）也要擋 ---")
# 只擋 GET 的話，直接送 POST 就能跳過密碼去燒額度
r = c.post("/", data={"destination": "ICC Sydney", "action": "search"})
check(r.status_code == 401, "沒帶密碼的 POST → 401，不會偷跑搜尋")
check(c.get("/?demo=1").status_code == 401, "示範模式網址也擋（避免被當後門）")

print("\n--- 401 的回應本身不可以出錯 ---")
# 實際踩過：realm 寫中文 → 標頭編碼失敗 → 401 變成 500。
r = c.get("/")
header = r.headers.get("WWW-Authenticate", "")
check("Basic" in header, f"有 WWW-Authenticate 標頭（瀏覽器才會跳出輸入框）：{header}")
check(header.isascii(), "標頭全部是 ASCII —— HTTP 標頭只能是 latin-1，寫中文會 500")
check(all(str(v).encode("latin-1", "strict") for v in r.headers.values()),
      "所有標頭都能用 latin-1 編碼")
check("需要密碼" in r.get_data(as_text=True), "畫面上有中文說明（內文可以是 UTF-8）")

print("\n--- 空白或只有空白的密碼視同沒設定 ---")
c = client("   ")
check(c.get("/").status_code == 200, "APP_PASSWORD 只填空白 → 當成沒設定，不會把自己鎖在外面")

os.environ.pop("APP_PASSWORD", None)
print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
