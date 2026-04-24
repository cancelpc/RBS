# API 說明

本文件整理目前系統對外 API。自本版起，API 依執行角色分為 `central` 與 `client`。

## 0. 系統資訊

### `GET /api/system/info`

- 取得目前執行角色與節點資訊
- 回傳欄位包含：
  - `app_role`
  - `client_code`
  - `client_name`
  - `central_base_url`

### 權限與角色

- `/api/media`、`/api/playlists`、`/api/schedules`、`/api/settings`、`/api/sync/*` 需管理登入
- 中央端 API 需 `BANNER_APP_ROLE=central`
- client 匯入 API 需 `BANNER_APP_ROLE=client`
- client 對中央端回報需使用註冊取得的 `X-Client-Token`

## 1. 影片

### `GET /api/media`

- 取得影片清單

### `POST /api/media`

- 新增影片

範例：

```json
{
  "title": "promo-a",
  "source_url": "https://example.com/promo-a.mp4",
  "enabled": true
}
```

### `POST /api/media/upload`

- 直接上傳一支或多支影片檔
- 使用 `multipart/form-data`
- 檔案會保存到本機 `storage/media/`
- 系統會自動建立對應的影片資料

欄位名稱：

- `files`

### `PUT /api/media/{media_id}`

- 更新影片

### `DELETE /api/media/{media_id}`

- 刪除影片

## 2. 播放清單

### `GET /api/playlists`

- 取得播放清單

### `POST /api/playlists`

- 新增播放清單

範例：

```json
{
  "name": "day-shift",
  "description": "白天輪播",
  "target_scope": "group",
  "target_code": "branch-a",
  "enabled": true,
  "items": [
    { "media_id": 1, "position": 1 },
    { "media_id": 2, "position": 2 }
  ]
}
```

### `PUT /api/playlists/{playlist_id}`

- 更新播放清單

### `DELETE /api/playlists/{playlist_id}`

- 刪除播放清單

## 3. 排程

### `GET /api/schedules`

- 取得排程

### `POST /api/schedules`

- 新增排程

範例：

```json
{
  "name": "weekday-morning",
  "playlist_id": 1,
  "target_scope": "site",
  "target_code": "taipei-1",
  "weekdays": [0, 1, 2, 3, 4],
  "start_date": null,
  "end_date": null,
  "start_time": "08:00",
  "end_time": "12:00",
  "play_count": 10,
  "priority": 10,
  "enabled": true
}
```

`start_date` 與 `end_date` 可為 `null`。兩者都為 `null` 代表沒有日期期限；只設定起日代表起日當天開始生效；只設定迄日代表迄日當天仍生效；兩者都設定代表只在起訖期間生效。起訖日都包含當日。

### `PUT /api/schedules/{schedule_id}`

- 更新排程

### `DELETE /api/schedules/{schedule_id}`

- 刪除排程

## 4. 系統設定

### `GET /api/settings`

- 取得設定

### `PUT /api/settings`

- 更新設定

範例：

```json
{
  "timezone": "Asia/Taipei",
  "sync_interval_seconds": 300,
  "central_base_url": "https://central.example.com",
  "client_code": "client-a",
  "client_name": "台北一店播放器",
  "client_site_name": "taipei-1",
  "client_group_name": "branch-a",
  "latest_version": "0.2.0",
  "latest_package_url": "https://example.com/banner-system.zip"
}
```

## 5. 同步

### `POST /api/sync/local`

- 下載目前資料庫中的啟用影片

### `POST /api/sync/upstream`

- `client` 模式下自中央管理端抓取最新 manifest、匯入本機資料並下載影片
- 若尚未註冊，會先用 `client_code` / `client_name` 向中央端註冊

### `GET /api/sync/status`

- 取得同步狀態

回傳欄位包含：

- `running`
- `last_started_at`
- `last_finished_at`
- `last_error`
- `last_summary`

## 6. 前台播放器

### `GET /api/player/current`

- 取得目前應播放的排程與影片清單

若有可播放內容，回傳包含：

- `active`
- `schedule`
- `items`

若沒有可播放內容，回傳：

- `active=false`
- `message`

### `POST /api/player/complete-cycle`

- 回報目前排程已完整播完一輪

範例：

```json
{
  "schedule_id": 1
}
```

## 7. 版本

### `GET /api/version`

- 取得目前版本與最新版本資訊

回傳欄位：

- `current_version`
- `latest_version`
- `latest_package_url`
- `update_available`

## 8. Manifest 格式

系統用於中央派送的 manifest 結構如下：

```json
{
  "manifest_version": "20260424T011500Z",
  "generated_at": "2026-04-24T01:15:00Z",
  "target": {
    "scope": "global",
    "target_code": null
  },
  "ui": {
    "show_player_brand": false,
    "default_fullscreen": true
  },
  "media": [
    {
      "media_code": "morning-promo-1",
      "title": "morning-promo",
      "source_url": "https://example.com/videos/morning.mp4",
      "checksum": "sha256:...",
      "size_bytes": 12345678,
      "enabled": true
    }
  ],
  "playlists": [
    {
      "playlist_code": "day-shift-1",
      "name": "早班清單",
      "description": "白天播放",
      "display_title": "防詐宣導專區",
      "target_scope": "group",
      "target_code": "branch-a",
      "enabled": true,
      "items": [
        { "media_code": "morning-promo-1", "position": 1 }
      ]
    }
  ],
  "schedules": [
    {
      "schedule_code": "weekday-morning-1",
      "name": "平日早班",
      "playlist_code": "day-shift-1",
      "target_scope": "site",
      "target_code": "taipei-1",
      "weekdays": [0, 1, 2, 3, 4],
      "start_time": "08:00",
      "end_time": "12:00",
      "play_count": 10,
      "priority": 10,
      "enabled": true
    }
  ],
  "package": {
    "latest_version": "0.2.0",
    "latest_package_url": "https://example.com/releases/client-0.2.0.zip"
  }
}
```

## 9. 中央端 Client API

### `POST /api/clients/register`

- client 首次註冊
- 成功後回傳：
  - `client_code`
  - `client_token`
  - `latest_version`
  - `latest_package_url`

### `POST /api/clients/heartbeat`

- client 回報存活狀態

### `GET /api/client-manifest/latest?client_code=...`

- 取得最新 manifest metadata
- 中央端會依 `client` 的 `site_name` / `group_name` 自動組出對應 manifest
- `site` client 會同時拿到：
  - `global`
  - 相符 `group`
  - 相符 `site`

### `GET /api/client-manifest/{version}?client_code=...`

- 取得指定版本 manifest

### `POST /api/client-events/playback`

- 回報播放完成事件

### `POST /api/client-events/sync-result`

- 回報同步結果

## 10. Client 本機匯入 API

### `POST /api/client/import-manifest`

- 僅限 `client` 模式
- 將指定 manifest 直接匯入本機資料庫
- 匯入後會同步 manifest 內指定影片到 `storage/media/`

用途：

- 測試 client manifest
- 離線或半離線環境用人工方式匯入內容
