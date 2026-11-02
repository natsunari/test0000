"""
表單驗證的測試。

執行方式：
    python test_app.py

不連網。驗證的是「送出去之前就該擋下來」的那些規則。
"""

from datetime import date, timedelta

import app

passed = 0


def check(condition, description):
    global passed
    assert condition, f"❌ 失敗：{description}"
    passed += 1
    print(f"  ✅ {description}")


future = (date.today() + timedelta(days=60)).isoformat()
later = (date.today() + timedelta(days=62)).isoformat()


def form(**overrides):
    base = {"destination": "Tokyo Big Sight", "city": "Tokyo",
            "check_in": future, "check_out": later, "mode": app.MODE_CACHE}
    base.update(overrides)
    return base


print("\n--- 目的地：必須是英文 ---")
check(app.validate(form()) is None, "英文名稱通過")
check(app.validate(form(destination="No. 7, Section 5, Xinyi Road, Taipei")) is None,
      "英文地址通過")

for bad in ["台北101", "東京ビッグサイト", "東京都江東区有明", "서울역"]:
    problem = app.validate(form(destination=bad))
    check(problem is not None and "英文" in problem,
          f"「{bad}」被擋下並說明要用英文")

print("\n--- 座標與 Maps 連結不受語言限制 ---")
for ok in [
    "35.6298, 139.7954",
    """35°37'58"N 139°52'50"E""",
    "https://www.google.com/maps/@25.0339,121.5645,15z",
]:
    check(app.validate(form(destination=ok)) is None, f"「{ok[:38]}」通過")

print("\n--- 示範模式不檢查目的地 ---")
check(app.validate(form(destination="", mode=app.MODE_DEMO)) is None,
      "示範模式留空也可以（反正會被忽略）")
check(app.validate(form(destination="台北101", mode=app.MODE_DEMO)) is None,
      "示範模式填中文也不擋（反正不會拿去查）")

print("\n--- 必填 ---")
check("目的地" in (app.validate(form(destination="")) or ""), "目的地空白會被擋下")
check("日期" in (app.validate(form(check_in="")) or ""), "入住日期空白會被擋下")
check("日期" in (app.validate(form(check_out="")) or ""), "退房日期空白會被擋下")

print("\n--- 日期先後與範圍 ---")
check("晚於" in (app.validate(form(check_in=later, check_out=future)) or ""),
      "退房早於入住會被擋下")
check("晚於" in (app.validate(form(check_in=future, check_out=future)) or ""),
      "退房與入住同一天也會被擋下（至少要住一晚）")
past = (date.today() - timedelta(days=1)).isoformat()
check("過了" in (app.validate(form(check_in=past, check_out=future)) or ""),
      "入住日期在過去會被擋下")
check("格式" in (app.validate(form(check_in="not-a-date")) or ""),
      "亂填日期格式會被擋下，而不是讓程式當掉")

print(f"\n{'=' * 56}")
print(f"OK —— {passed} 項檢查全部通過")
print("=" * 56)
