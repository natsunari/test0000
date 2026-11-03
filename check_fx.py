"""
匯率來源檢查

逐一測試 config.toml 用得到的每一種幣別，看兩個來源各自能不能取得匯率。

執行方式：
    python check_fx.py

為什麼需要這支：
  主來源 Frankfurter 的資料來自歐洲央行，只涵蓋約 30 種參考匯率。
  台幣（TWD）、越南盾（VND）、阿聯迪拉姆（AED）都不在裡面 ——
  而那三個正好是你會去的地方。所以加了一個備援來源。
  但備援來源的回應格式我在開發環境裡驗證不了（CDN 連不出去），
  所以需要你跑這支確認它真的能用。

這支只連匯率服務，不碰 SerpApi，不消耗任何額度。
"""

from __future__ import annotations

import sys

import fx
import rules

# 歐洲央行公布的參考匯率幣別。不在這裡的一定要靠備援來源。
ECB = {
    "USD", "JPY", "BGN", "CZK", "DKK", "GBP", "HUF", "PLN", "RON", "SEK",
    "CHF", "ISK", "NOK", "TRY", "AUD", "BRL", "CAD", "CNY", "HKD", "IDR",
    "ILS", "INR", "KRW", "MXN", "MYR", "NZD", "PHP", "SGD", "THB", "ZAR",
    "EUR",
}


def main() -> int:
    config = rules.load_config()
    wanted = sorted(set(config.get("currency_by_country", {}).values()))
    # 費率設定檔裡用到的幣別也要測
    for table in ("taxi_fare", "taxi_fare_by_country"):
        for entry in config.get(table, {}).values():
            cur = (entry.get("currency") or "").upper()
            if cur and cur != "USD" and cur not in wanted:
                wanted.append(cur)
    wanted = sorted(set(wanted))

    print(f"要測試 {len(wanted)} 種幣別，每種最多試兩個來源。\n")
    print(f"  {'幣別':<6}{'歐洲央行':<10}{'主來源':<12}{'備援來源':<12}結果")
    print("  " + "-" * 56)

    ok = missing = 0
    for code in wanted:
        in_ecb = "有" if code in ECB else "—"
        try:
            primary, _ = fx._from_frankfurter("USD", code)
        except Exception:
            primary = None
        try:
            backup, _ = fx._from_fallback("USD", code)
        except Exception:
            backup = None

        p_txt = f"{primary:.4f}" if primary else "✗"
        b_txt = f"{backup:.4f}" if backup else "✗"
        if primary or backup:
            verdict = "✅ 可用"
            ok += 1
        else:
            verdict = "❌ 兩邊都取不到"
            missing += 1
        print(f"  {code:<6}{in_ecb:<10}{p_txt:<12}{b_txt:<12}{verdict}")

    print()
    print(f"可用 {ok} 種，取不到 {missing} 種。")
    if missing:
        print("\n取不到的幣別，程式會改用保守預設車資並在畫面上標示。")
        print("請把上面整張表貼回來，我看情況換來源或改做法。")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
