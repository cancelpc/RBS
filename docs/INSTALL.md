# 安裝與佈署手冊

本文件說明單機安裝、中央端與 client 端啟動方式。正式上線的程序、服務化與備份請另看 [佈署手冊](DEPLOYMENT.md) 與 [維護手冊](MAINTENANCE.md)。

## 1. 適用環境

- 作業系統：Windows 10 / 11
- Python：3.11 以上
- 瀏覽器：Edge 或 Chrome
- 網路：若只做本機離線播放，可不連外；若需中央派送與線上更新，client 需可連到中央管理端與影片下載來源

## 2. 專案目錄

```text
RBS/
|- app/                  後端程式
|- static/               前台與後台頁面
|- scripts/              啟動與更新腳本
|- storage/
|  |- media/             本地影片
|  |- updates/           更新封包
|  |- manifests/         中央派送 manifest 快照
|  \- banner.db          SQLite 資料庫
\- requirements.txt
```

## 3. 安裝步驟

在專案根目錄執行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 阻擋執行腳本，可先在目前使用者層級允許：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 4. 選擇執行角色

本系統目前支援兩種角色：

- `central`：中央管理端，負責內容維護、client 註冊、manifest 派送、狀態回報收集
- `client`：本地播放器，負責同步中央 manifest、下載影片到本機、以瀏覽器播放本機內容

角色由環境變數 `BANNER_APP_ROLE` 決定，預設為 `client`。

```powershell
$env:BANNER_APP_ROLE = "central"
```

或：

```powershell
$env:BANNER_APP_ROLE = "client"
```

若 client 要在第一次啟動時帶入中央端 URL，可設定：

```powershell
$env:BANNER_CENTRAL_BASE_URL = "http://central-server:8080"
```

也可以啟動後到 `/admin` 的設定區填寫 `central_base_url`。

## 5. 啟動系統

開發模式：

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

正式執行：

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

或使用內建提示腳本：

```powershell
.\scripts\start.ps1 -Port 8080
```

若看到 `uvicorn is not recognized`，通常代表：

- 尚未啟用 `.venv`
- `.venv` 內尚未安裝依賴
- 直接打了 `uvicorn ...`，但目前 shell PATH 沒包含虛擬環境

此時請優先改用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Windows 快速啟動：

```bat
run.bat
```

- 以 `client` 模式啟動
- 開啟 [http://127.0.0.1:8080/](http://127.0.0.1:8080/)

```bat
run-admin.bat
```

- 以 `central` 模式啟動
- 開啟 [http://127.0.0.1:8080/admin](http://127.0.0.1:8080/admin)

## 6. 驗證安裝

啟動後確認：

- 開啟 [http://127.0.0.1:8080/](http://127.0.0.1:8080/) 可看到前台播放器
- 開啟 [http://127.0.0.1:8080/admin](http://127.0.0.1:8080/admin) 會先進入管理登入頁
- 開啟 [http://127.0.0.1:8080/api/version](http://127.0.0.1:8080/api/version) 可回傳 JSON
- 開啟 [http://127.0.0.1:8080/api/system/info](http://127.0.0.1:8080/api/system/info) 可確認 `app_role`

## 7. 建議正式部署

- 讓 `uvicorn` 以常駐程序方式執行
- 用 Windows 工作排程器、NSSM 或 Windows Service 包裝 Python 服務
- 前台瀏覽器使用 kiosk/fullscreen 模式固定開啟 `/`
- 若需要聲音自動播放，需配合瀏覽器啟動參數或企業政策設定
- 中央端正式環境建議放在 IIS 或 Nginx 反向代理後方，並使用 HTTPS

## 8. 首次建議設定

首次啟動後建議先到 `/admin` 設定：

- `timezone`
- `sync_interval_seconds`
- `central_base_url`
- `latest_version`
- `latest_package_url`
- `admin_password`
- `show_player_brand`
- `default_fullscreen`
- `client_code`
- `client_name`
- `client_site_name`
- `client_group_name`

若暫時沒有中央後台：

- `central_base_url` 與 `upstream_manifest_url` 可直接留空
- 這代表系統以本機離線模式運作
- 可直接手動上傳影片、建立清單與排程
- 不需要按「同步後台並下載」

## 9. 管理後台登入

- `/admin` 需先登入
- 預設管理密碼為 `admin`
- 建議首次登入後到設定頁修改 `admin_password`

## 10. 下一步文件

- 正式服務化、中央端/client 端拓樸、備份與升級：請看 [佈署手冊](DEPLOYMENT.md)
- 日常內容操作：請看 [操作說明](OPERATION.md)
- 例行維護與備份還原：請看 [維護手冊](MAINTENANCE.md)
- 錯誤訊息與檢查指令：請看 [問題排除](TROUBLESHOOTING.md)
