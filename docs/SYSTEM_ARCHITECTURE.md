# 系統架構圖

本文件整理 RBS 在中央管理端與本地 client 模式下的整體架構。預設以免安裝 SQLite 運作；中央端擴大時可再改接 PostgreSQL。SQL Server 不列入優先支援。

## 圖片檔

![系統整體架構](assets/system-architecture.svg)

- SVG：`docs/assets/system-architecture.svg`
- PNG：`docs/assets/system-architecture.png`

## 1. 整體拓樸

```mermaid
flowchart LR
    Admin["管理員瀏覽器"]

    subgraph Central["中央管理端 BANNER_APP_ROLE=central"]
        CentralAdmin["/admin 管理後台"]
        CentralAPI["FastAPI API"]
        CentralDB[("中央 SQLite / 可擴充 PostgreSQL")]
        ManifestStore["storage/manifests"]
        CentralMedia["storage/media 或獨立檔案服務"]
        Updates["storage/updates"]
    end

    subgraph ClientA["本地 Client A BANNER_APP_ROLE=client"]
        BrowserA["Kiosk 瀏覽器 / Player"]
        LocalAPIA["本機 FastAPI"]
        LocalDBA[("本機 SQLite")]
        LocalMediaA["本機 storage/media"]
        SyncA["背景同步工作"]
        OutboxA["client_outbox_events"]
    end

    subgraph ClientB["本地 Client B"]
        BrowserB["Kiosk 瀏覽器 / Player"]
        LocalAPIB["本機 FastAPI"]
        LocalDBB[("本機 SQLite")]
        LocalMediaB["本機 storage/media"]
        SyncB["背景同步工作"]
        OutboxB["client_outbox_events"]
    end

    Admin -->|維護影片 / 清單 / 排程 / 設定| CentralAdmin
    CentralAdmin --> CentralAPI
    CentralAPI --> CentralDB
    CentralAPI --> ManifestStore
    CentralAPI --> CentralMedia
    CentralAPI --> Updates

    SyncA -->|註冊 / metadata / manifest / 回報| CentralAPI
    SyncA -->|下載影片| CentralMedia
    SyncA --> LocalDBA
    SyncA --> LocalMediaA
    SyncA --> OutboxA
    BrowserA -->|每 15 秒查本機目前排程| LocalAPIA
    LocalAPIA --> LocalDBA
    BrowserA -->|播放本機影片| LocalMediaA
    OutboxA -->|中央恢復後補送| CentralAPI

    SyncB -->|註冊 / metadata / manifest / 回報| CentralAPI
    SyncB -->|下載影片| CentralMedia
    SyncB --> LocalDBB
    SyncB --> LocalMediaB
    SyncB --> OutboxB
    BrowserB -->|查本機目前排程| LocalAPIB
    LocalAPIB --> LocalDBB
    BrowserB -->|播放本機影片| LocalMediaB
    OutboxB -->|中央恢復後補送| CentralAPI
```

## 2. 中央端內部模組

```mermaid
flowchart TB
    AdminUI["/admin"]
    Auth["admin session"]
    MediaAPI["/api/media"]
    PlaylistAPI["/api/playlists"]
    ScheduleAPI["/api/schedules"]
    SettingsAPI["/api/settings"]
    ClientAPI["/api/clients/*"]
    ManifestAPI["/api/client-manifest/*"]
    EventAPI["/api/client-events/*"]
    VersionAPI["/api/version"]

    DB[("banner.db")]
    MediaFiles["storage/media"]
    ManifestFiles["storage/manifests"]
    UpdateFiles["storage/updates"]

    AdminUI --> Auth
    Auth --> MediaAPI
    Auth --> PlaylistAPI
    Auth --> ScheduleAPI
    Auth --> SettingsAPI

    MediaAPI --> DB
    PlaylistAPI --> DB
    ScheduleAPI --> DB
    SettingsAPI --> DB
    ClientAPI --> DB
    EventAPI --> DB
    ManifestAPI --> DB
    VersionAPI --> DB

    MediaAPI --> MediaFiles
    ManifestAPI --> ManifestFiles
    VersionAPI --> UpdateFiles

    DB -->|"media_items / playlists / schedule_rules"| ManifestAPI
    DB -->|"clients / client_events"| ClientAPI
```

## 3. Client 端內部模組

```mermaid
flowchart TB
    Player["前台 player.html"]
    Admin["本機 /admin"]
    LocalAPI["本機 FastAPI"]
    Scheduler["排程判斷"]
    SyncLoop["背景 sync loop"]
    Downloader["媒體下載器"]
    Outbox["事件 outbox"]

    LocalDB[("本機 banner.db")]
    LocalMedia["本機 storage/media"]

    Player -->|GET /api/player/current| LocalAPI
    Player -->|POST /api/player/complete-cycle| LocalAPI
    Player -->|讀取 /media/...| LocalMedia

    Admin --> LocalAPI
    LocalAPI --> Scheduler
    Scheduler --> LocalDB
    LocalAPI --> Outbox

    SyncLoop -->|GET latest metadata| CentralManifest["中央 /api/client-manifest/latest"]
    SyncLoop -->|GET manifest by version| CentralManifestVersion["中央 /api/client-manifest/{version}"]
    SyncLoop --> LocalDB
    SyncLoop --> Downloader
    Downloader --> LocalMedia
    SyncLoop --> Outbox
    Outbox -->|POST playback / sync-result| CentralEvents["中央 /api/client-events/*"]
```

## 4. 同步流程

```mermaid
sequenceDiagram
    participant C as Client sync loop
    participant Central as 中央 API
    participant DB as Client SQLite
    participant Media as Client storage/media
    participant Outbox as Client outbox

    C->>Central: POST /api/clients/register + X-Registration-Key
    Central-->>C: client_token
    C->>Central: GET /api/client-manifest/latest
    Central-->>C: manifest_version / checksum

    alt manifest 未變更
        C->>Central: POST /api/clients/heartbeat
    else manifest 已變更
        C->>Central: GET /api/client-manifest/{version}
        Central-->>C: full manifest
        C->>DB: 匯入 media / playlists / schedules
        C->>Media: 只下載缺少或 checksum 改變的影片
        C->>Outbox: 補送 pending playback / sync-result
        C->>Central: POST /api/client-events/sync-result
        C->>Central: POST /api/clients/heartbeat
    end
```

## 5. 播放流程

```mermaid
sequenceDiagram
    participant P as Player Browser
    participant API as 本機 API
    participant DB as 本機 SQLite
    participant Media as 本機 storage/media
    participant Outbox as 本機 outbox
    participant Central as 中央 API

    loop 每 15 秒
        P->>API: GET /api/player/current
        API->>DB: 依日期 / 星期 / 時段 / 次數選排程
        API-->>P: schedule + playlist items
    end

    P->>Media: 播放本機影片
    P->>API: POST /api/player/complete-cycle
    API->>DB: 更新每日播放次數
    API->>Central: POST /api/client-events/playback

    alt 中央不可連線
        API->>Outbox: 寫入 pending playback event
    else 中央可連線
        Central-->>API: ok
    end
```

## 6. 資料表對應

```mermaid
erDiagram
    MEDIA_ITEMS ||--o{ PLAYLIST_ITEMS : contains
    PLAYLISTS ||--o{ PLAYLIST_ITEMS : orders
    PLAYLISTS ||--o{ SCHEDULE_RULES : scheduled_by
    CLIENTS ||--o{ CLIENT_EVENTS : reports
    MANIFEST_SNAPSHOTS }o--|| APP_SETTINGS : generated_with

    MEDIA_ITEMS {
        int id
        string media_code
        string title
        string source_url
        string local_file_name
        string checksum
        int size_bytes
        bool enabled
    }

    PLAYLISTS {
        int id
        string playlist_code
        string name
        string target_scope
        string target_code
        bool enabled
    }

    SCHEDULE_RULES {
        int id
        string schedule_code
        int playlist_id
        string weekdays
        string start_date
        string end_date
        string start_time
        string end_time
        int play_count
        int priority
        bool enabled
    }

    CLIENTS {
        int id
        string client_code
        string client_token
        string site_name
        string group_name
        datetime last_seen_at
        string last_manifest_version
    }

    CLIENT_EVENTS {
        int id
        string client_code
        string event_type
        string payload_json
    }

    MANIFEST_SNAPSHOTS {
        int id
        string manifest_version
        string checksum
        string scope
        string target_code
        string payload_json
    }
```

## 7. 邊界與責任

- 中央端負責內容維護、manifest 版本、client 註冊、狀態與事件收集。
- client 負責本機播放、本機排程判斷、差異同步、媒體下載與離線補送。
- 前台播放器只連本機服務，不直接向中央查排程。
- 中央端不承擔大量即時影片播放流量；client 播放本機 `storage/media`。
- `client_registration_key` 用於首次註冊；註冊後使用 `client_token` 呼叫 manifest、heartbeat 與 event API。
