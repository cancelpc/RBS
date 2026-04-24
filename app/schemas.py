from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator


class MediaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1)
    enabled: bool = True


class MediaRead(MediaCreate):
    id: int
    media_code: str
    local_file_name: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    last_synced_at: str | None = None

    class Config:
        from_attributes = True


class PlaylistItemInput(BaseModel):
    media_id: int = Field(ge=1)
    position: int = Field(ge=1)


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    display_title: str | None = Field(default=None, max_length=200)
    target_scope: str = Field(default="global", pattern=r"^(global|group|site)$")
    target_code: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    items: list[PlaylistItemInput] = Field(default_factory=list)


class PlaylistRead(PlaylistCreate):
    id: int
    playlist_code: str

    class Config:
        from_attributes = True


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    playlist_id: int = Field(ge=1)
    target_scope: str = Field(default="global", pattern=r"^(global|group|site)$")
    target_code: str | None = Field(default=None, max_length=200)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    play_count: int = Field(default=0, ge=0)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("至少需要選擇一個播放星期。")
        invalid = [day for day in value if day < 0 or day > 6]
        if invalid:
            raise ValueError("播放星期必須介於 0 到 6。")
        return sorted(set(value))

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        hour, minute = value.split(":")
        if int(hour) > 23 or int(minute) > 59:
            raise ValueError("時間必須使用 HH:MM，且小時 00-23、分鐘 00-59。")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("日期必須使用 YYYY-MM-DD 格式。") from exc
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "ScheduleCreate":
        if (
            self.start_date is not None
            and self.end_date is not None
            and date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date)
        ):
            raise ValueError("結束日期不可早於開始日期。")
        return self


class ScheduleRead(ScheduleCreate):
    id: int
    schedule_code: str
    current_play_count: int
    last_reset_date: str | None = None

    class Config:
        from_attributes = True


class SettingsPayload(BaseModel):
    timezone: str = "Asia/Taipei"
    sync_interval_seconds: int = Field(default=300, ge=30)
    central_base_url: str = ""
    upstream_manifest_url: str = ""
    latest_version: str = "0.1.0"
    latest_package_url: str = ""
    admin_password: str = "admin"
    show_player_brand: bool = False
    default_fullscreen: bool = False
    client_code: str = ""
    client_name: str = ""
    client_site_name: str = ""
    client_group_name: str = ""


class AdminLoginPayload(BaseModel):
    password: str = Field(min_length=1)


class CycleCompletePayload(BaseModel):
    schedule_id: int


class ClientRegisterPayload(BaseModel):
    client_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    site_name: str | None = Field(default=None, max_length=200)
    group_name: str | None = Field(default=None, max_length=200)
    app_version: str = Field(min_length=1, max_length=50)


class ClientHeartbeatPayload(BaseModel):
    client_code: str = Field(min_length=1, max_length=100)
    app_version: str = Field(min_length=1, max_length=50)
    manifest_version: str | None = Field(default=None, max_length=64)
    ip: str | None = Field(default=None, max_length=100)
    disk_free_bytes: int | None = Field(default=None, ge=0)
    last_sync_status: str | None = None
    last_player_status: str | None = None


class PlaybackEventPayload(BaseModel):
    client_code: str = Field(min_length=1, max_length=100)
    schedule_id: int
    playlist_id: int
    completed_at: str = Field(min_length=1, max_length=64)
    manifest_version: str | None = Field(default=None, max_length=64)


class SyncResultPayload(BaseModel):
    client_code: str = Field(min_length=1, max_length=100)
    manifest_version: str | None = Field(default=None, max_length=64)
    status: str = Field(min_length=1, max_length=50)
    summary: dict = Field(default_factory=dict)
