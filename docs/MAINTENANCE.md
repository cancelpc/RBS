# 維護手冊

本文件面向維運人員，整理例行檢查、備份、還原、內容清理與升級流程。

## 1. 例行檢查

每天或每班次建議確認：

- `/` 前台是否正在播放
- `/api/version` 是否正常回傳
- `/api/system/info` 的 `app_role` 是否符合該主機角色
- `/admin` 的同步狀態是否有 `last_error`
- `storage/media/` 是否還有足夠磁碟空間
- client 清單是否有近期心跳

PowerShell 檢查範例：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/version
Invoke-RestMethod http://127.0.0.1:8080/api/system/info
```

## 2. 重要資料位置

- 資料庫：`storage/banner.db`
- 本地播放影片：`storage/media/`
- manifest 快照：`storage/manifests/`
- 更新封包：`storage/updates/`
- 靜態頁面：`static/`
- 啟動腳本：`run.bat`、`run-admin.bat`、`scripts/start.ps1`

## 3. 備份

服務執行時 SQLite 仍可複製，但正式備份建議先停止服務，避免複製到寫入中的檔案。

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = "E:\Backup\RotatingBannerSystem\$stamp"
New-Item -ItemType Directory -Force $backupRoot | Out-Null
Copy-Item storage\banner.db $backupRoot\
Copy-Item storage\media $backupRoot\media -Recurse
Copy-Item storage\manifests $backupRoot\manifests -Recurse -ErrorAction SilentlyContinue
Copy-Item storage\updates $backupRoot\updates -Recurse -ErrorAction SilentlyContinue
```

## 4. 還原

還原前請先停止服務。

```powershell
Copy-Item E:\Backup\RotatingBannerSystem\20260424-090000\banner.db storage\banner.db -Force
Copy-Item E:\Backup\RotatingBannerSystem\20260424-090000\media storage\media -Recurse -Force
```

還原後啟動服務，確認：

- `/api/version`
- `/api/system/info`
- `/admin` 內容數量
- `/` 前台播放

## 5. 內容維護

### 新增內容

中央端或單機離線模式都可在 `/admin` 上傳影片、建立清單與排程。

### 停用內容

若暫時不播放，優先把影片、清單或排程設為停用，不要直接刪檔。確認不再需要後再刪除資料。

### 清理本機檔案

「同步後台並下載」會清除不再被資料庫引用的本地影片。單機離線模式若手動刪除資料，請確認 `storage/media/` 中是否還有不再使用的檔案。

## 6. 同步維護

client 端背景同步條件：

- `app_role=client`
- `central_base_url` 有值
- `sync_interval_seconds` 到達

中央端背景工作會更新 manifest metadata。若 client 不需要中央派送，請讓 `central_base_url` 留空。

## 7. 管理密碼

首次佈署後請立即修改 `admin_password`。

目前 admin session 存在記憶體中，服務重啟後已登入 session 會失效，需要重新登入。這是目前 MVP 行為。

## 8. 升級

系統支援版本檢查與更新封包下載，但不會自動覆蓋程式。

建議流程：

1. 下載更新封包到 `storage/updates/`
2. 停止服務
3. 備份 `storage/`
4. 替換程式
5. 安裝或更新依賴
6. 啟動服務
7. 驗證 `/api/version`、`/api/system/info`、`/admin` 與 `/`

下載封包可使用：

```powershell
.\scripts\update-client.ps1 -ServerBaseUrl http://127.0.0.1:8080
```

## 9. 磁碟空間

影片檔案是主要容量來源。client 同步時會下載到本機 `storage/media/`，請保留足夠空間給：

- 已啟用影片
- 下載暫存檔
- 更新封包
- 備份檔

## 10. 監控建議

正式環境建議至少監控：

- 服務程序是否存在
- `http://127.0.0.1:8080/api/version` 是否成功
- `storage/media/` 所在磁碟剩餘空間
- 中央端 `/api/clients` 顯示的 `last_seen_at`
- client 的 `last_sync_status`
