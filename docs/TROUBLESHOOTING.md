# 問題排除

本文件整理常見問題、原因與檢查指令。若問題與日常操作有關，請先看 [操作說明](OPERATION.md)。

## 1. `uvicorn is not recognized`

原因通常是尚未啟用 `.venv`，或 shell PATH 沒包含虛擬環境。

請改用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

若 `.venv` 不存在，先安裝：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. PowerShell 不允許執行 `.ps1`

執行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

或改用 `run.bat` / `run-admin.bat`。

## 3. `/admin` 進不去

現象：

- 被導到 `/admin-login`
- 顯示管理密碼錯誤

檢查：

- 預設密碼是 `admin`
- 若已修改 `admin_password`，請用新密碼
- 服務重啟後原本登入狀態會失效，需重新登入

若忘記密碼，目前需直接修正 SQLite `app_settings` 內的 `admin_password`，或還原備份資料庫。

## 4. 前台顯示「目前沒有可播放內容」

請依序檢查：

1. 是否有啟用排程
2. 目前星期是否包含在排程內
3. 目前時間是否落在開始/結束時間內
4. 排程對應清單是否啟用
5. 清單內影片是否啟用
6. 影片是否存在於 `storage/media/`
7. 排程是否已達每日完整清單播放次數上限

快速檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/player/current
```

## 5. 上傳影片後仍不播放

確認：

- 上傳是否成功建立影片資料
- 影片是否已加入播放清單
- 播放清單是否已被排程引用
- 排程是否符合目前時間
- 影片是否為瀏覽器可播放格式

上傳影片會直接寫入 `storage/media/`，不需要再按「同步後台並下載」。

## 6. 「同步後台並下載」顯示未設定中央管理端 URL

原因：

- `central_base_url` 為空
- 單機離線模式不需要中央同步

處理：

- 若是單機離線播放：保持空白，不要按「同步後台並下載」
- 若是 client：到 `/admin` 設定 `central_base_url`、`client_code`、`client_name`

## 7. Client 註冊或同步失敗

檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/system/info
```

client 主機需顯示：

- `app_role` 為 `client`
- `central_base_url` 有值
- `client_code` 有值
- `client_name` 有值

中央端需顯示：

- `app_role` 為 `central`

也請確認 client 可連到中央端：

```powershell
Invoke-RestMethod http://central-server:8080/api/version
```

## 8. API 回傳 `This endpoint requires central role`

原因是目前服務以 `client` 模式啟動，但你呼叫的是中央端 API。

處理：

- 中央端請用 `run-admin.bat`
- 或啟動前設定 `$env:BANNER_APP_ROLE = "central"`

## 9. API 回傳 `This endpoint requires client role`

原因是目前服務以 `central` 模式啟動，但你呼叫的是 client 端 API。

處理：

- client 端請用 `run.bat`
- 或啟動前設定 `$env:BANNER_APP_ROLE = "client"`

## 10. 影片下載失敗

檢查：

- `source_url` 是否可由該主機連線
- URL 是否需要登入或授權
- 防火牆是否阻擋
- `storage/media/` 是否有寫入權限
- 磁碟空間是否足夠

PowerShell 測試：

```powershell
Invoke-WebRequest "https://example.com/video.mp4" -OutFile "$env:TEMP\video-test.mp4"
```

## 11. 版本顯示有更新但下載失敗

檢查：

- `latest_package_url` 是否正確
- 主機是否可連到該 URL
- `storage/updates/` 是否有寫入權限
- 防毒或代理是否封鎖 ZIP 下載

執行：

```powershell
.\scripts\update-client.ps1 -ServerBaseUrl http://127.0.0.1:8080
```

## 12. Port 8080 被占用

檢查：

```powershell
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
```

改用其他 port：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8081
```

## 13. Favicon 404

目前程式已提供 `/favicon.ico` route，檔案應位於：

- `static/favicon.ico`

若仍 404，請確認部署檔案是否缺漏。
