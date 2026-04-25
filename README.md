# Rotating Banner System

以瀏覽器為前台載體的本地輪播播放系統。系統會在本機播放預先下載好的影片，支援多組播放清單、時段排程、每日播放次數限制、後台 manifest 同步，以及版本檢查與更新封包下載。

## 文件索引

- [安裝說明](docs/INSTALL.md)
- [佈署手冊](docs/DEPLOYMENT.md)
- [操作說明](docs/OPERATION.md)
- [維護手冊](docs/MAINTENANCE.md)
- [使用說明](docs/USER_GUIDE.md)
- [問題排除](docs/TROUBLESHOOTING.md)
- [需求規格](docs/SPECIFICATION.md)
- [API 說明](docs/API.md)
- [系統架構圖](docs/SYSTEM_ARCHITECTURE.md)
- [中央管理端 + 本地 Client 架構草案](docs/CENTRAL_CLIENT_ARCHITECTURE.md)

## 目前實作範圍

- 前台播放器：`/`
- 後台管理頁：`/admin`
- 後端 API：FastAPI
- 本地資料庫：SQLite
- 媒體目錄：`storage/media/`
- 更新封包目錄：`storage/updates/`

## MVP 功能

- 管理後台需登入，client 不直接暴露 admin 介面
- 固定播放已下載到本機的影片
- 可直接上傳多支本機影片到播放器主機
- 建立多組播放清單
- 設定播放時段與優先序
- 設定每日完整播放清單次數上限
- 定時向後台取得 manifest 並下載影片
- 清除不再使用的本地影片
- 檢查版本並下載更新封包

## 離線播放說明

- 前台播放器實際播放的是本機 `storage/media/` 中已下載的影片檔
- 排程、清單與設定保存在本機 `storage/banner.db`
- 因此只要內容已先同步到本機，前台播放時不需要持續連線到後台
- 若 `後台 Manifest URL` 留空，系統即視為本機離線模式
- 需要連線的部分只有：
  - 向後台取得新的 manifest
  - 下載新的影片檔
  - 下載更新封包
- 若後台暫時無法連線，系統仍可繼續播放本機既有內容，但不會取得新內容

## 多影片自動循環

- 後台 `/admin` 可直接多選上傳 `n` 支影片
- 上傳完成後，影片會直接存到本機 `storage/media/`
- 你可以手動建立播放清單，或使用「用全部影片建立循環清單與排程」
- 每個播放清單可設定前台自訂抬頭文字
- 只要排程有效，前台就會依清單順序自動循環播放
- 若排程的 `play_count=0`，表示無限循環

## 前台顯示控制

- 前台預設不顯示程式名稱
- 可在後台設定中切換是否顯示程式名稱
- 可在後台設定 client 載入時是否預設嘗試全螢幕
- 前台可切換全螢幕
- 前台可打開影片清單並直接跳播指定影片

## 快速啟動

本版開始支援兩種執行角色：

- `central`：中央管理端，負責內容維護、manifest 派送、client 註冊與回報
- `client`：本地播放器，負責抓取 manifest、同步媒體、播放本機內容

啟動前可先設定環境變數：

```powershell
$env:BANNER_APP_ROLE = "central"
```

或：

```powershell
$env:BANNER_APP_ROLE = "client"
```

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

若 `uvicorn` 指令找不到，請不要直接打裸命令，改用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Windows 也可以直接執行：

```bat
run.bat
```

或啟動中央管理端：

```bat
run-admin.bat
```

啟動後：

- 前台播放器：[http://127.0.0.1:8080/](http://127.0.0.1:8080/)
- 後台管理：[http://127.0.0.1:8080/admin](http://127.0.0.1:8080/admin)

完整部署、操作、維護與問題排除細節請看 `docs/`。

## 中央端與 Client 對應

- `run-admin.bat` 預設以 `central` 模式啟動
- `run.bat` 預設以 `client` 模式啟動
- `central` 模式新增：
  - `POST /api/clients/register`
  - `POST /api/clients/heartbeat`
  - `GET /api/client-manifest/latest`
  - `GET /api/client-manifest/{version}`
  - `POST /api/client-events/playback`
  - `POST /api/client-events/sync-result`
- `client` 模式會：
  - 依 `central_base_url`、`client_code`、`client_name` 自動註冊
  - 若設定 `client_registration_key`，註冊時會送出 `X-Registration-Key`
  - 比對 `manifest_version` 後再做差異同步
  - 將影片下載到本機 `storage/media/`
  - 中央暫時離線時，播放與同步事件會先進本機 outbox，之後補送
  - 以前台播放器讀取本機檔案播放

## Targeting 規則

- 播放清單與排程都可指定 `global`、`group`、`site`
- `global` 會派送給所有 client
- `group` 會派送給 `client_group_name` 相符的 client
- `site` 會派送給 `client_site_name` 相符的 client
- 若 client 同時有 `site` 與 `group`，manifest 會同時包含：
  - 全域內容
  - 相符群組內容
  - 相符站點內容
