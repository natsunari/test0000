# Mac 環境建立指南

預計時間 **20～30 分鐘**。只需要做一次。
請一步一步做，每一步都有「怎麼確認成功了」，確認過再往下走。

---

## 步驟 0：認識終端機

這是你接下來最常用的工具。

1. 按 `Command (⌘)` + `空白鍵`
2. 輸入 `終端機`（或 `Terminal`）
3. 按 `Enter`

會跳出一個視窗，裡面有一行像這樣的文字，結尾是 `$` 或 `%`：

```
yourname@MacBook ~ %
```

這叫**提示字元**，意思是「我準備好了，請下指令」。
你打字、按 Enter，它就執行。打錯不會壞掉，重打就好。

> **小技巧**：指令可以直接從這份文件複製貼上（`⌘C` / `⌘V`），不用自己打。
> 貼上密碼時畫面不會有任何變化，這是正常的安全設計，直接按 Enter。

---

## 步驟 1：安裝 Python（程式語言本體）

macOS 內建的 Python 版本舊又容易出問題，**請自己裝一份新的**。

1. 用瀏覽器打開 <https://www.python.org/downloads/>
2. 點中間那顆黃色大按鈕 **Download Python 3.x.x**
3. 下載完打開 `.pkg` 檔，一路按「繼續 → 同意 → 安裝」，中途要輸入 Mac 的開機密碼
4. 安裝完成後 **把終端機關掉再重新開一次**（很重要，否則它不知道有新東西）

**確認成功**：在終端機輸入
```bash
python3 --version
```
看到類似 `Python 3.13.1` 就成功了。

<details>
<summary>如果顯示 command not found 或版本是 3.8 以下</summary>

表示安裝沒生效。檢查：
- 終端機有重開嗎？
- 下載的是 macOS 版本嗎（不是 Windows 版）？
- 重新執行一次 `.pkg` 安裝檔。
</details>

---

## 步驟 2：安裝 Git（存檔與同步工具）

Mac 通常裝好 Xcode 工具就有了。在終端機輸入：

```bash
git --version
```

- 看到 `git version 2.xx.x` → **已經有了，跳到步驟 3**
- 跳出一個視窗問你要不要安裝「命令列開發者工具」→ 點**安裝**，等它跑完（約 5～10 分鐘），然後再輸入一次上面的指令確認

---

## 步驟 3：安裝 VS Code（寫程式的編輯器）

程式碼可以用純文字編輯，但編輯器會幫你標示顏色、抓錯字，差別很大。

1. 打開 <https://code.visualstudio.com/>
2. 點 **Download for macOS**
3. 下載的是 `.zip`，解壓縮後會得到 `Visual Studio Code` 這個 App
4. **把它拖到「應用程式」資料夾**（這步不要忘，不然每次更新會出問題）
5. 第一次打開會問「確定要打開嗎」→ 點**打開**

**建議安裝的擴充套件**（讓它懂 Python）：
在 VS Code 左側點那個四方格圖示 → 搜尋 `Python` → 找到 Microsoft 發布的那個 → 按 **Install**

---

## 步驟 4：把專案抓到電腦上

決定一個放專案的地方。這裡用家目錄下的 `專案` 資料夾：

```bash
mkdir -p ~/專案
cd ~/專案
git clone https://github.com/natsunari/test0000.git
cd test0000
```

逐行解釋：
| 指令 | 意思 |
|---|---|
| `mkdir -p ~/專案` | 建立一個叫「專案」的資料夾（`~` 代表你的家目錄） |
| `cd ~/專案` | 走進那個資料夾（cd = change directory） |
| `git clone ...` | 從 GitHub 把整個專案下載下來 |
| `cd test0000` | 走進剛下載的專案資料夾 |

**確認成功**：
```bash
ls
```
應該會看到 `app.py`、`README.md`、`requirements.txt` 等檔案。

---

## 步驟 5：建立虛擬環境（專案專屬工具箱）

```bash
python3 -m venv .venv
```

這會產生一個 `.venv` 資料夾。它是**這個專案專用的工具箱**，
之後裝的外掛都關在裡面，不會污染你整台電腦。

接著**啟動**它：

```bash
source .venv/bin/activate
```

**確認成功**：提示字元前面會多出 `(.venv)`，像這樣：
```
(.venv) yourname@MacBook test0000 %
```

> 這個 `(.venv)` 非常重要。
> **沒看到它，就表示工具箱沒打開，後面一定會出錯。**
> 每次重新開終端機都要重新執行一次 `source .venv/bin/activate`。

---

## 步驟 6：安裝這個專案需要的外掛

確認你看到 `(.venv)`，然後：

```bash
pip install -r requirements.txt
```

這會讀 `requirements.txt`，自動裝好裡面列的工具（Flask 負責做網站、requests 負責連網路）。
跑完最後一行會是 `Successfully installed Flask-3.1.0 requests-2.32.3 ...`。

---

## 步驟 7：啟動！

```bash
python app.py
```

終端機會印出：
```
  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000
```

打開瀏覽器，到 **http://127.0.0.1:5000**
輸入關鍵字（例如「台灣黑熊」）按搜尋 — 應該會跑出一串結果。

**成功了。你的環境建好了。**

> `127.0.0.1` 的意思是「我自己這台電腦」。
> 這個網站只有你看得到，沒有公開到網路上，可以放心亂試。

要結束的時候，回到終端機按 `Ctrl + C`。

---

## 常見錯誤

### `command not found: python3`
Python 沒裝成功，或終端機沒重開。回到步驟 1。

### `No module named flask`
你沒有啟動虛擬環境。看看提示字元有沒有 `(.venv)`。沒有的話執行：
```bash
source .venv/bin/activate
```

### `Address already in use` / `Port 5000 is in use`
5000 這個號碼被別的程式佔走了（Mac 的 AirPlay 常會佔用）。兩個解法：
- **關掉 AirPlay 接收器**：系統設定 → 一般 → 隔空播放與接續 → 關閉「AirPlay 接收器」
- **或換一個號碼**：打開 `app.py`，把最後一行的 `port=5000` 改成 `port=5001`，然後瀏覽器改開 http://127.0.0.1:5001

### 瀏覽器顯示「無法連線」
終端機裡的 `python app.py` 還在執行嗎？它必須一直開著，網站才活著。

### 搜尋時出現「連線失敗」或「連線逾時」
- 確認電腦有連上網路
- 如果在公司或學校網路，可能被防火牆擋住，換成手機熱點試試

### `zsh: permission denied`
通常是指令開頭多打了東西。確認你複製的指令開頭**沒有** `$` 或 `%` 符號。

---

## 下一步

環境好了之後：
- 想改網頁長相 → 編輯 `templates/index.html`
- 想換搜尋來源 → 編輯 `app.py` 裡的 `SOURCES` 和 `search_wikipedia`
- 改完記得存檔並上傳，這樣回家用 Windows 才看得到：
  ```bash
  git add .
  git commit -m "說明我改了什麼"
  git push
  ```
