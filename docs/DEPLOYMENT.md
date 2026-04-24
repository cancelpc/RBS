# 佈署手冊

本文件面向系統管理員，說明如何把 RBS 佈署成中央管理端與本地 client。若只是開發或單機測試，先看 [安裝與佈署手冊](INSTALL.md)。

## 1. 佈署模式

### 單機離線模式

適用於只有一台播放主機、由現場直接上傳影片與設定排程的情境。

- `BANNER_APP_ROLE=client`
- `central_base_url` 留空
- `storage/media/` 保存實際播放影片
- `storage/banner.db` 保存清單、排程與設定
- 不使用「同步後台並下載」

### 中央端 + 多 client 模式

適用於總部派送內容到多個播放點。

- 中央端：`BANNER_APP_ROLE=central`
- client 端：`BANNER_APP_ROLE=client`
- client 設定 `central_base_url`
- client 設定唯一的 `client_code` 與可辨識的 `client_name`
- 中央端提供 manifest 與版本資訊，client 下載影片到本機播放

## 2. 中央端佈署

### 建議啟動

```powershell
cd D:\MYPRJS\RBS
$env:BANNER_APP_ROLE = "central"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

或使用：

```bat
run-admin.bat
```

### 中央端首次設定

登入 `/admin` 後至少設定：

- `admin_password`
- `timezone`
- `latest_version`
- `latest_package_url`
- `show_player_brand`
- `default_fullscreen`

中央端負責維護影片、播放清單與排程；若要派送到特定 client，請設定 target：

- `global`：所有 client
- `group`：符合 `client_group_name` 的 client
- `site`：符合 `client_site_name` 的 client

## 3. Client 端佈署

### 建議啟動

```powershell
cd D:\MYPRJS\RBS
$env:BANNER_APP_ROLE = "client"
$env:BANNER_CENTRAL_BASE_URL = "http://central-server:8080"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

或使用：

```bat
run.bat
```

### Client 首次設定

登入 client 本機 `/admin` 後設定：

- `central_base_url`：中央端網址，例如 `http://central-server:8080`
- `public_base_url`：中央端可被 client 存取的公開 URL；若中央與 client 不在同一台，建議填寫
- `client_code`：唯一代碼，例如 `branch-a-player-01`
- `client_name`：顯示名稱，例如 `台北一店播放器 01`
- `client_site_name`：站點名稱，用於 `site` target
- `client_group_name`：群組名稱，用於 `group` target
- `client_registration_key`：client 首次註冊金鑰；中央端與 client 端需設定相同值，留空則不檢查
- `sync_interval_seconds`：同步間隔，最低 30 秒；正式環境建議 300 秒以上

第一次按「同步後台並下載」時，client 會向中央端註冊並取得 `client_token`，之後 manifest、心跳與事件回報會帶 token。
若中央暫時離線，播放完成與同步結果會先寫入 client 本機 outbox，下一次同步成功時補送。

## 4. 連線與防火牆

中央端需允許 client 連入：

- `GET /api/client-manifest/latest`
- `GET /api/client-manifest/{version}`
- `POST /api/clients/register`
- `POST /api/clients/heartbeat`
- `POST /api/client-events/playback`
- `POST /api/client-events/sync-result`
- 影片檔案下載 URL

client 前台只需要本機瀏覽器連到本機服務：

- `http://127.0.0.1:8080/`

## 5. Windows 常駐建議

正式環境建議用其中一種方式常駐：

- Windows 工作排程器：開機後執行啟動腳本
- NSSM：把 uvicorn 包成 Windows Service
- 企業既有服務管理工具

服務啟動命令請使用 `.venv\Scripts\python.exe -m uvicorn ...`，不要依賴裸 `uvicorn` 命令。

## 6. 瀏覽器 Kiosk 建議

client 播放機可設定開機後啟動 Edge：

```powershell
msedge.exe --kiosk http://127.0.0.1:8080/ --edge-kiosk-type=fullscreen --no-first-run
```

若影片需要聲音自動播放，瀏覽器可能需要額外企業政策或啟動參數。這屬瀏覽器安全限制，不是後端服務錯誤。

## 7. 備份與升級佈署

升級前請備份：

- `storage/banner.db`
- `storage/media/`
- `storage/manifests/`
- `storage/updates/`

升級基本流程：

1. 停止服務
2. 備份 `storage/`
3. 替換程式檔
4. 保留既有 `.venv` 或重新安裝 `requirements.txt`
5. 啟動服務
6. 開啟 `/api/version`、`/api/system/info`、`/` 驗證

版本封包下載目前只做到下載到 `storage/updates/`，不會自動覆蓋程式或重啟。

## 8. 規模邊界

目前程式可作為 MVP 與本地播放器基礎。若要支援約 300 台 client，請遵守：

- client 播放本機 `storage/media/`，不要讓 300 台直接從中央 FastAPI 串流影片
- 中央端只承擔控制面：manifest、版本、client 狀態與事件回報
- 影片檔案服務建議獨立為 Nginx/IIS/NAS/S3 相容儲存
- 預設資料庫仍是免安裝 SQLite；中央資料庫正式化時可改為 PostgreSQL。SQL Server 不列入優先支援

完整架構請看 [中央管理端 + 本地 Client 架構草案](CENTRAL_CLIENT_ARCHITECTURE.md)。
