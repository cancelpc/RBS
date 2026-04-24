# 中央管理端 + 本地 Client 架構草案

本文件定義本專案從目前 MVP 單機型態，擴成「1 台中央管理端 + 多台本地播放器 client」的建議架構。

目標情境：

- 中央管理端負責內容維護、排程派送、版本派送
- 各播放點各自有一套本地 client
- client 平時播放本機影片，不依賴中央即時串流
- 規模目標可先以 300 台 client 為設計基準

## 1. 核心原則

### 1.1 控制面與資料面分離

中央端只做：

- 管理後台
- manifest 派送
- 版本資訊派送
- client 狀態回報收集

client 端只做：

- 下載 manifest
- 下載影片到本機
- 使用本機資料庫與本機影片播放
- 回報播放狀態與健康狀態

不要讓 300 台瀏覽器同時向中央直接串流 `/media/...` 影片。

### 1.2 播放以本機為主

每台 client 實際播放來源應為本機：

- 本機 `storage/media/`
- 本機 `storage/banner.db`

中央不可成為影片播放熱點；中央只負責派送與更新。

### 1.3 中央可橫向擴充，client 可離線運作

中央端暫時無法連線時：

- client 仍可照本機排程繼續播放
- 只是不會拿到新的內容與新的版本資訊

這是整體可擴充性的基礎。

## 2. 推薦拓樸

### 2.1 中央管理端

建議職責：

- Web Admin UI
- 中央資料庫
- 內容檔案儲存
- manifest API
- 版本 API
- client 註冊 / 心跳 / 狀態回報 API

建議元件：

- 反向代理：Nginx 或 IIS
- API：FastAPI
- DB：預設可使用免安裝 SQLite；中央端擴大時再改 PostgreSQL
- 物件儲存或檔案服務：NAS、SMB、S3 相容儲存、或 Nginx 靜態檔案目錄

### 2.2 本地 Client

每台 client 建議包含：

- 本地播放器服務
- 本地 SQLite
- 本地媒體目錄
- 背景同步工作
- kiosk 瀏覽器或 WebView 播放器

本地服務提供：

- `/` 前台播放器
- `/admin` 本機維護頁
- 本機同步與診斷頁

### 2.3 網路流向

1. 管理員在中央端維護影片、清單、排程
2. 中央端產生 manifest 與版本資訊
3. client 定時向中央抓 manifest
4. client 只在版本或內容有變化時下載差異檔案
5. client 將影片保存到本機並更新本機 SQLite
6. 前台瀏覽器從本機 `/media/...` 播放影片

## 3. 中央端資料模型

中央端建議成為系統唯一的內容真實來源。

### 3.1 內容主檔

- `media_master`
- `playlists`
- `playlist_items`
- `schedule_rules`
- `app_settings`

### 3.2 裝置主檔

- `clients`
- `client_groups`
- `client_assignments`

建議 `clients` 至少包含：

- `client_code`
- `name`
- `site_name`
- `group_name`
- `last_seen_at`
- `last_manifest_version`
- `last_app_version`
- `last_sync_status`
- `last_player_status`

### 3.3 派送版本

中央端每次內容異動後，應產生：

- `manifest_version`
- `published_at`
- `checksum`

client 只需要比較版本，不要每次全量重抓。

## 4. Manifest 設計

目前 repo 內已有 manifest 概念，但要支援 300 台 client，建議升級為「可版本化、可差異同步、可指派目標」格式。

### 4.1 建議欄位

```json
{
  "manifest_version": "2026-04-23T16:30:00Z",
  "generated_at": "2026-04-23T16:30:00Z",
  "target": {
    "scope": "group",
    "group_code": "branch-a"
  },
  "ui": {
    "show_player_brand": false,
    "default_fullscreen": true
  },
  "media": [
    {
      "media_code": "promo-morning-001",
      "title": "早班宣導",
      "source_url": "https://central.example.com/media/promo-morning-001.mp4",
      "checksum": "sha256:...",
      "size_bytes": 12345678,
      "enabled": true
    }
  ],
  "playlists": [],
  "schedules": [],
  "package": {
    "latest_version": "0.2.0",
    "latest_package_url": "https://central.example.com/releases/client-0.2.0.zip"
  }
}
```

### 4.2 建議原則

- `source_url` 指向中央檔案服務，不是中央 API 動態串流
- 每支影片有穩定識別碼與 checksum
- manifest 需有版本號
- 支援依群組或站點派送不同內容

## 5. Client 同步策略

### 5.1 輕量輪詢

建議：

- 每 1 到 5 分鐘抓一次 manifest metadata
- 若版本沒變，不下載內容
- 若版本變了，再下載 manifest 與缺少的影片

不要每 15 秒向中央查完整排程。

### 5.2 差異同步

client 同步流程建議：

1. 取得最新 manifest version
2. 比對本機 manifest version
3. 找出新增 / 變更 / 刪除的影片
4. 只下載缺少或 checksum 改變的影片
5. 更新本機資料庫
6. 清理不再使用的本機影片

### 5.3 下載與播放解耦

同步下載不可阻塞前台播放。

建議：

- 新影片先下載到暫存檔
- checksum 驗證成功後再原子替換
- 播放器只讀取已完成下載的檔案

## 6. Client 播放策略

### 6.1 排程判斷在本機

client 播放時，不應每 15 秒回中央問「現在該播什麼」。

應改為：

- manifest 下來後，將排程與清單寫入本機 SQLite
- 前台播放器只向本機 API 取目前排程

這樣 300 台 client 只會對中央產生同步壓力，不會產生 300 台同時查播放狀態的壓力。

### 6.2 播放完成回報

目前 `complete-cycle` 是本機計數；若未來要做中央報表，建議新增非同步回報：

- `POST /api/client-events/playback`

內容可包含：

- `client_code`
- `schedule_id`
- `playlist_id`
- `completed_at`
- `manifest_version`

若中央暫時離線，可先寫本機 queue，稍後補送。目前程式已用 SQLite `client_outbox_events` 實作播放完成與同步結果的補送佇列。

## 7. 中央端新增 API 建議

### 7.1 Client 註冊

- `POST /api/clients/register`

用途：

- 首次安裝後註冊 client
- 取得 client token 或 device key

### 7.2 Client 心跳

- `POST /api/clients/heartbeat`

用途：

- 回報 client 存活狀態
- 更新最後連線時間

建議欄位：

- `client_code`
- `app_version`
- `manifest_version`
- `ip`
- `disk_free_bytes`
- `last_sync_status`

### 7.3 取得 manifest metadata

- `GET /api/client-manifest/latest`

用途：

- 僅回傳 manifest version、checksum、下載網址

### 7.4 取得完整 manifest

- `GET /api/client-manifest/{version}`

用途：

- 回傳特定版本 manifest

### 7.5 回報播放事件

- `POST /api/client-events/playback`

### 7.6 回報同步結果

- `POST /api/client-events/sync-result`

## 8. 安全性建議

### 8.1 中央與 client 間驗證

至少要有：

- 每台 client 的裝置金鑰或 token
- 首次註冊的 shared registration key
- 中央 API 的驗證機制
- HTTPS

不要讓任何人只知道 manifest URL 就能任意抓到內部派送內容。

### 8.2 Admin 驗證

目前專案使用記憶體型 admin session，只適合單實例 MVP。

中央端正式化時建議改為：

- DB session 或 JWT
- RBAC 權限控管
- 審計紀錄

## 9. 擴充與容量考量

### 9.1 300 台 client 時中央壓力來源

合理設計下，中央主要承受的是：

- manifest metadata 查詢
- 差異內容下載
- 心跳與狀態回報

中央不應承受：

- 300 路即時影片播放流量
- 300 台前台每 15 秒查播放狀態

### 9.2 大致容量估算

若 300 台 client 每 5 分鐘抓一次 metadata：

- 每分鐘約 60 次 metadata 請求
- 這對一般 API 服務很輕

若同時間有大量新影片派送：

- 壓力主要在中央檔案服務與頻寬
- 因此影片檔案服務應與 API 分離

### 9.3 推薦部署

中央端：

- `Nginx/IIS + FastAPI + PostgreSQL`
- 檔案服務獨立於 API

目前實作預設使用免安裝 SQLite，適合 MVP 與本機 client；中央端擴大時可再改接 PostgreSQL。SQL Server 不列入優先支援。

Client 端：

- `FastAPI + SQLite + 本機 storage/media`
- Windows 開機自動啟動

## 10. 對目前 repo 的改造順序

### 階段 1：明確分中央與 client 模式

新增兩種執行角色：

- `central`
- `client`

差異：

- `central` 提供內容維護、manifest 派送、client 管理
- `client` 提供本機播放、同步、裝置回報

### 階段 2：補 client 身分與心跳

新增：

- `client_code`
- `client_name`
- `client_token`
- heartbeat API

### 階段 3：manifest 版本化

新增：

- `manifest_version`
- `checksum`
- target scope

### 階段 4：中央媒體服務獨立

將影片下載位址切到：

- Nginx/IIS 靜態檔案服務
- NAS 或物件儲存

不要讓 FastAPI 本體承擔大量影片分發。

### 階段 5：中央報表與監控

新增：

- client 在線狀態
- 最後同步時間
- 最後播放回報
- 錯誤告警

## 11. 結論

本專案若要支援 300 台 client，正確方向不是「300 台瀏覽器同時連同一台播放器服務看影片」，而是：

- 中央端只做控制面
- 每台 client 自己下載影片到本機
- 每台 client 以本機服務播放本機影片
- 中央只負責派送、版本、監控與回報

這樣才能同時滿足：

- 規模擴充
- 離線播放
- 頻寬可控
- 維運可觀測
- 日後多站點、多群組派送
