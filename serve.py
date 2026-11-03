"""
正式伺服器的啟動檔，部署平台用的。

為什麼不用 python app.py：那個用的是 Flask 內建的開發伺服器，
就是你看過的那句 "WARNING: This is a development server"。
它一次只服務一個人、也沒有針對外部流量做任何防護。

waitress 是純 Python 寫的正式伺服器，Mac、Windows、Linux 都能跑
（gunicorn 不支援 Windows，所以沒有選它）。

自己電腦上測試正式模式：
    python serve.py
部署平台上不用管，啟動指令寫在 render.yaml 裡。
"""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    # 部署平台會用 PORT 這個環境變數告訴你要聽哪個埠號
    port = int(os.environ.get("PORT", "5000"))
    # 0.0.0.0 = 接受來自外面的連線。本機開發的 127.0.0.1 只接受自己。
    print(f"  正式伺服器啟動，監聽 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=4)
