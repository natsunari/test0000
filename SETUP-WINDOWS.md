# Windows 環境建立指南

預計時間 **20～30 分鐘**。只需要做一次。
請一步一步做，每一步都有「怎麼確認成功了」，確認過再往下走。

> **Windows 有兩個初學者一定會踩的坑**，分別在步驟 1 和步驟 5。
> 那兩步請特別慢慢看，其他都很順。

---

## 步驟 0：認識 PowerShell

這是 Windows 版的「終端機」，你接下來最常用的工具。

1. 按 `Windows 鍵`
2. 輸入 `powershell`
3. 點 **Windows PowerShell**（不用選「以系統管理員身分執行」）

會跳出一個視窗，裡面有一行像這樣，結尾是 `>`：

```
PS C:\Users\你的名字>
```

這叫**提示字元**，意思是「我準備好了，請下指令」。
你打字、按 Enter，它就執行。打錯不會壞掉，重打就好。

> **小技巧**：指令可以直接從這份文件複製（`Ctrl+C`），
> 在 PowerShell 裡**按滑鼠右鍵**就是貼上。

---

## 步驟 1：安裝 Python ⚠️ 這步有坑

1. 用瀏覽器打開 <https://www.python.org/downloads/>
2. 點中間那顆黃色大按鈕 **Download Python 3.x.x**
3. 打開下載的 `.exe` 檔
4. ### ⚠️ 最重要的一步
   安裝畫面**最下面**有一個小小的勾選框：

   ```
   ☐  Add python.exe to PATH
   ```

   **一定要打勾！**
   沒勾的話，PowerShell 會找不到 Python，後面每一步都會失敗，
   而且錯誤訊息完全看不出原因。初學者九成卡在這裡。

5. 勾好之後點 **Install Now**，等它跑完
6. 最後若出現 `Disable path length limit` 的按鈕，**點它**
7. 安裝完成後 **把 PowerShell 關掉再重新開一次**（很重要）

**確認成功**：在 PowerShell 輸入
```powershell
python --version
```
看到類似 `Python 3.13.1` 就成功了。

<details>
<summary>如果跳出 Microsoft Store，或顯示「找不到 python」</summary>

這就是沒勾 PATH 的症狀。修法：

**方法 A（推薦）**：重新執行一次剛才的 `.exe`，選 **Modify**，
確認 `Add python.exe to PATH` 有勾，然後完成。關掉 PowerShell 重開。

**方法 B**：關掉 Windows 的假 Python 捷徑 ——
設定 → 應用程式 → 進階應用程式設定 → 應用程式執行別名 →
把 `python.exe` 和 `python3.exe` 兩個開關**關掉**。
</details>

> **注意**：在 Windows 上指令是 `python`，不是 `python3`。
> 網路上很多教學寫 `python3`（那是 Mac/Linux 的寫法），在 Windows 要去掉 `3`。

---

## 步驟 2：安裝 Git（存檔與同步工具）

1. 打開 <https://git-scm.com/download/win>
2. 它會自動開始下載 **64-bit Git for Windows Setup**
3. 打開 `.exe`，接下來的選項**全部用預設值、一路按 Next 就好**（選項很多，不用看懂）
4. 裝完**關掉 PowerShell 再重開**

**確認成功**：
```powershell
git --version
```
看到 `git version 2.xx.x` 即可。

---

## 步驟 3：安裝 VS Code（寫程式的編輯器）

1. 打開 <https://code.visualstudio.com/>
2. 點 **Download for Windows**
3. 打開 `.exe`，一路 Next
4. 中途有一頁「選擇附加工作」，建議把這兩個勾起來：
   - ☑ 新增「以 Code 開啟」動作至 Windows 檔案總管檔案的內容功能表
   - ☑ 新增至 PATH

**建議安裝的擴充套件**（讓它懂 Python）：
打開 VS Code → 左側點四方格圖示 → 搜尋 `Python` → 找到 Microsoft 發布的那個 → 按 **Install**

---

## 步驟 4：把專案抓到電腦上

```powershell
mkdir $HOME\專案 -Force
cd $HOME\專案
git clone https://github.com/natsunari/test0000.git
cd test0000
```

逐行解釋：
| 指令 | 意思 |
|---|---|
| `mkdir $HOME\專案 -Force` | 建立一個叫「專案」的資料夾（`$HOME` 代表你的使用者資料夾） |
| `cd $HOME\專案` | 走進那個資料夾（cd = change directory） |
| `git clone ...` | 從 GitHub 把整個專案下載下來 |
| `cd test0000` | 走進剛下載的專案資料夾 |

**確認成功**：
```powershell
dir
```
應該會看到 `app.py`、`README.md`、`requirements.txt` 等檔案。

---

## 步驟 5：建立虛擬環境 ⚠️ 這步有坑

```powershell
python -m venv .venv
```

這會產生一個 `.venv` 資料夾。它是**這個專案專用的工具箱**，
之後裝的外掛都關在裡面，不會污染你整台電腦。

接著**啟動**它：

```powershell
.venv\Scripts\Activate.ps1
```

### ⚠️ 如果出現紅字「無法載入檔案…因為這個系統上已停用指令碼執行」

這是 Windows 的預設安全限制，不是你做錯。執行這一行解除（只影響你自己的帳號，安全）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

它會問你確認，輸入 `Y` 按 Enter。然後再執行一次：

```powershell
.venv\Scripts\Activate.ps1
```

**確認成功**：提示字元前面會多出 `(.venv)`，像這樣：
```
(.venv) PS C:\Users\你的名字\專案\test0000>
```

> 這個 `(.venv)` 非常重要。
> **沒看到它，就表示工具箱沒打開，後面一定會出錯。**
> 每次重新開 PowerShell 都要重新執行一次 `.venv\Scripts\Activate.ps1`。

---

## 步驟 6：安裝這個專案需要的外掛

確認你看到 `(.venv)`，然後：

```powershell
pip install -r requirements.txt
```

這會讀 `requirements.txt`，自動裝好裡面列的工具（Flask 負責做網站、requests 負責連網路）。
跑完最後一行會是 `Successfully installed Flask-3.1.0 requests-2.32.3 ...`。

---

## 步驟 7：啟動！

```powershell
python app.py
```

PowerShell 會印出：
```
  網站已啟動，請在瀏覽器打開： http://127.0.0.1:5000
```

第一次執行時，Windows 可能跳出**防火牆警告**，問要不要允許 Python 連線 →
點**允許存取**（勾「私人網路」就夠了）。

打開瀏覽器，到 **http://127.0.0.1:5000**
輸入關鍵字（例如「台灣黑熊」）按搜尋 — 應該會跑出一串結果。

**成功了。你的環境建好了。**

> `127.0.0.1` 的意思是「我自己這台電腦」。
> 這個網站只有你看得到，沒有公開到網路上，可以放心亂試。

要結束的時候，回到 PowerShell 按 `Ctrl + C`。

---

## 常見錯誤

### 輸入 `python` 跳出 Microsoft Store
安裝時沒勾 `Add python.exe to PATH`。看步驟 1 的折疊說明。

### `python : 無法辨識 'python' 詞彙`
同上，Python 沒加到 PATH，或 PowerShell 沒重開。

### `無法載入檔案 .venv\Scripts\Activate.ps1`
執行原則限制。看步驟 5 的紅字區塊。

### `No module named flask`
你沒有啟動虛擬環境。看看提示字元有沒有 `(.venv)`。沒有的話執行：
```powershell
.venv\Scripts\Activate.ps1
```

### `Address already in use` / `Port 5000 is in use`
5000 這個號碼被別的程式佔走了。打開 `app.py`，
把最後一行的 `port=5000` 改成 `port=5001`，
然後瀏覽器改開 http://127.0.0.1:5001

### 瀏覽器顯示「無法連線」
PowerShell 裡的 `python app.py` 還在執行嗎？它必須一直開著，網站才活著。

### 搜尋時出現「連線失敗」或「連線逾時」
- 確認電腦有連上網路
- 第一次執行時防火牆警告有按「允許」嗎？
- 如果在公司或學校網路，可能被擋住，換成手機熱點試試

### 路徑裡的中文造成問題
如果上面的「專案」資料夾造成怪錯誤，改用英文資料夾名稱：
```powershell
mkdir $HOME\projects -Force
cd $HOME\projects
```

---

## 下一步

環境好了之後：
- 想改網頁長相 → 編輯 `templates\index.html`
- 想換搜尋來源 → 編輯 `app.py` 裡的 `SOURCES` 和 `search_wikipedia`
- **開始改之前，先抓 Mac 上的最新版本**：
  ```powershell
  git pull
  ```
- 改完記得存檔並上傳：
  ```powershell
  git add .
  git commit -m "說明我改了什麼"
  git push
  ```
