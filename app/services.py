from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.config import (
    APP_ROLE,
    APP_VERSION,
    DEFAULT_CENTRAL_BASE_URL,
    DEFAULT_SYNC_INTERVAL_SECONDS,
    DEFAULT_TIMEZONE,
    MANIFEST_DIR,
    MEDIA_DIR,
)
from app.models import AppSetting, Client, ClientEvent, ManifestSnapshot, MediaItem, Playlist, PlaylistItem, ScheduleRule


SYNC_STATE: dict[str, Any] = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
    "last_summary": None,
}

ADMIN_SESSIONS: set[str] = set()


def role_name() -> str:
    return APP_ROLE


def is_central_role() -> bool:
    return role_name() == "central"


def ensure_setting(db: Session, key: str, default_value: str) -> str:
    setting = db.get(AppSetting, key)
    if not setting:
        setting = AppSetting(key=key, value=default_value)
        db.add(setting)
        db.commit()
        return default_value
    return setting.value


def setting_defaults() -> dict[str, str]:
    return {
        "app_role": role_name(),
        "timezone": DEFAULT_TIMEZONE,
        "sync_interval_seconds": str(DEFAULT_SYNC_INTERVAL_SECONDS),
        "central_base_url": DEFAULT_CENTRAL_BASE_URL,
        "upstream_manifest_url": DEFAULT_CENTRAL_BASE_URL,
        "latest_version": APP_VERSION,
        "latest_package_url": "",
        "admin_password": "admin",
        "show_player_brand": "false",
        "default_fullscreen": "false",
        "client_code": "",
        "client_name": "",
        "client_site_name": "",
        "client_group_name": "",
        "client_token": "",
        "current_manifest_version": "",
        "manifest_scope": "global",
        "manifest_target_code": "",
        "last_sync_status": "",
    }


def get_settings(db: Session) -> dict[str, str]:
    return {key: ensure_setting(db, key, default_value) for key, default_value in setting_defaults().items()}


def set_settings(db: Session, payload: dict[str, str]) -> dict[str, str]:
    current = get_settings(db)
    current.update(payload)
    if current.get("central_base_url"):
        current["upstream_manifest_url"] = current["central_base_url"]
    elif current.get("upstream_manifest_url"):
        current["central_base_url"] = current["upstream_manifest_url"]
    for key, value in current.items():
        setting = db.get(AppSetting, key)
        if not setting:
            db.add(AppSetting(key=key, value=str(value)))
        else:
            setting.value = str(value)
    db.commit()
    return get_settings(db)


def now_in_timezone(db: Session) -> datetime:
    settings = get_settings(db)
    timezone_name = settings["timezone"]
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return datetime.now(timezone)


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def current_minutes(value: datetime) -> int:
    return value.hour * 60 + value.minute


def window_matches(now_dt: datetime, schedule: ScheduleRule) -> bool:
    weekday = now_dt.weekday()
    allowed_days = {int(item) for item in schedule.weekdays.split(",") if item != ""}
    if weekday not in allowed_days:
        return False
    start_h, start_m = parse_hhmm(schedule.start_time)
    end_h, end_m = parse_hhmm(schedule.end_time)
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    now_total = current_minutes(now_dt)
    if start_total <= end_total:
        return start_total <= now_total <= end_total
    return now_total >= start_total or now_total <= end_total


def reset_schedule_counter_if_needed(db: Session, schedule: ScheduleRule, today: str) -> None:
    if schedule.last_reset_date != today:
        schedule.last_reset_date = today
        schedule.current_play_count = 0


def build_player_payload(db: Session) -> dict[str, Any]:
    now_dt = now_in_timezone(db)
    today = now_dt.date().isoformat()
    settings = get_settings(db)
    schedules = (
        db.execute(
            select(ScheduleRule)
            .options(joinedload(ScheduleRule.playlist).joinedload(Playlist.items).joinedload(PlaylistItem.media))
            .where(ScheduleRule.enabled.is_(True))
            .order_by(ScheduleRule.priority.asc(), ScheduleRule.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )
    chosen: ScheduleRule | None = None
    for schedule in schedules:
        reset_schedule_counter_if_needed(db, schedule, today)
        playlist = schedule.playlist
        if not playlist.enabled:
            continue
        if schedule.play_count and schedule.current_play_count >= schedule.play_count:
            continue
        if not window_matches(now_dt, schedule):
            continue
        items = [item for item in playlist.items if item.media.enabled and item.media.local_file_name]
        if not items:
            continue
        chosen = schedule
        break
    db.commit()

    if not chosen:
        return {
            "active": False,
            "timestamp": now_dt.isoformat(),
            "message": "目前沒有符合時段且可播放的清單。",
            "ui": {
                "show_player_brand": settings["show_player_brand"].lower() == "true",
                "default_fullscreen": settings["default_fullscreen"].lower() == "true",
            },
        }

    items = [
        {
            "media_id": item.media.id,
            "media_code": item.media.media_code,
            "title": item.media.title,
            "url": f"/media/{item.media.local_file_name}",
            "position": item.position,
        }
        for item in chosen.playlist.items
        if item.media.enabled and item.media.local_file_name
    ]
    return {
        "active": True,
        "timestamp": now_dt.isoformat(),
        "manifest_version": settings.get("current_manifest_version", ""),
        "schedule": {
            "id": chosen.id,
            "schedule_code": chosen.schedule_code,
            "name": chosen.name,
            "play_count": chosen.play_count,
            "current_play_count": chosen.current_play_count,
            "playlist_id": chosen.playlist_id,
            "playlist_code": chosen.playlist.playlist_code,
            "playlist_name": chosen.playlist.name,
            "playlist_display_title": chosen.playlist.display_title or "",
        },
        "items": items,
        "ui": {
            "show_player_brand": settings["show_player_brand"].lower() == "true",
            "default_fullscreen": settings["default_fullscreen"].lower() == "true",
        },
    }


def slugify_code(value: str, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:80] or prefix


def ensure_media_code(db: Session, item: MediaItem) -> None:
    if not item.media_code:
        item.media_code = f"{slugify_code(item.title, 'media')}-{item.id}"
        db.flush()


def ensure_playlist_code(db: Session, playlist: Playlist) -> None:
    if not playlist.playlist_code:
        playlist.playlist_code = f"{slugify_code(playlist.name, 'playlist')}-{playlist.id}"
        db.flush()


def ensure_schedule_code(db: Session, schedule: ScheduleRule) -> None:
    if not schedule.schedule_code:
        schedule.schedule_code = f"{slugify_code(schedule.name, 'schedule')}-{schedule.id}"
        db.flush()


def sha256_of_path(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sanitize_filename(title: str, source_url: str) -> str:
    parsed = urlparse(source_url)
    suffix = Path(parsed.path).suffix or ".mp4"
    title_part = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in title).strip("_") or "media"
    digest = hashlib.md5(source_url.encode("utf-8")).hexdigest()[:8]
    return f"{title_part}_{digest}{suffix}"


def sanitize_upload_filename(original_name: str) -> str:
    source_name = Path(original_name or "upload.mp4").name
    suffix = Path(source_name).suffix or ".mp4"
    stem = Path(source_name).stem
    title_part = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem).strip("_") or "media"
    digest = hashlib.md5(f"{source_name}-{datetime.utcnow().isoformat()}".encode("utf-8")).hexdigest()[:8]
    return f"{title_part}_{digest}{suffix}"


def download_to_file(source_url: str, target_path: Path) -> tuple[str, int]:
    response = requests.get(source_url, timeout=60, stream=True)
    response.raise_for_status()
    digest = hashlib.sha256()
    size_bytes = 0
    with target_path.open("wb") as file_obj:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            file_obj.write(chunk)
            digest.update(chunk)
            size_bytes += len(chunk)
    return f"sha256:{digest.hexdigest()}", size_bytes


def download_media_file(item: MediaItem) -> str:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    local_name = sanitize_filename(item.title, item.source_url)
    target_path = MEDIA_DIR / local_name
    checksum, size_bytes = download_to_file(item.source_url, target_path)
    item.checksum = checksum
    item.size_bytes = size_bytes
    return local_name


def save_uploaded_media_file(file_obj, original_name: str) -> tuple[str, str, int]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    local_name = sanitize_upload_filename(original_name)
    target_path = MEDIA_DIR / local_name
    with target_path.open("wb") as output:
        shutil.copyfileobj(file_obj, output)
    return local_name, sha256_of_path(target_path), target_path.stat().st_size


def cleanup_unused_files(db: Session) -> list[str]:
    referenced = {item.local_file_name for item in db.execute(select(MediaItem)).scalars().all() if item.local_file_name}
    deleted: list[str] = []
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    for file_path in MEDIA_DIR.iterdir():
        if file_path.is_file() and file_path.name not in referenced:
            file_path.unlink(missing_ok=True)
            deleted.append(file_path.name)
    return deleted


def sync_local_media(db: Session) -> dict[str, Any]:
    summary = {"downloaded": [], "failed": [], "deleted": []}
    for item in db.execute(select(MediaItem).where(MediaItem.enabled.is_(True))).scalars().all():
        ensure_media_code(db, item)
        if item.source_url.startswith("local-upload://"):
            if item.local_file_name and (MEDIA_DIR / item.local_file_name).exists():
                file_path = MEDIA_DIR / item.local_file_name
                item.checksum = sha256_of_path(file_path)
                item.size_bytes = file_path.stat().st_size
                item.last_synced_at = datetime.utcnow()
                continue
            summary["failed"].append({"title": item.title, "error": "本機上傳檔案不存在。"})
            continue
        try:
            item.local_file_name = download_media_file(item)
            item.last_synced_at = datetime.utcnow()
            summary["downloaded"].append(item.title)
        except Exception as exc:  # noqa: BLE001
            summary["failed"].append({"title": item.title, "error": str(exc)})
    db.commit()
    summary["deleted"] = cleanup_unused_files(db)
    return summary


def replace_playlist_items(db: Session, playlist: Playlist, items: list[dict[str, int]]) -> None:
    playlist.items.clear()
    db.flush()
    for item in sorted(items, key=lambda row: row["position"]):
        playlist.items.append(PlaylistItem(media_id=item["media_id"], position=item["position"]))


def media_public_url(settings: dict[str, str], item: MediaItem) -> str:
    if item.source_url.startswith("http://") or item.source_url.startswith("https://"):
        return item.source_url
    central_base = settings.get("central_base_url", "").rstrip("/")
    if item.local_file_name and central_base:
        return f"{central_base}/media/{item.local_file_name}"
    if item.local_file_name:
        return f"/media/{item.local_file_name}"
    return item.source_url


def normalize_target_scope(value: str | None) -> str:
    return value if value in {"global", "group", "site"} else "global"


def normalize_target_code(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def build_target_context(client: Client | None) -> dict[str, str | None]:
    if not client:
        return {
            "resolved_scope": "global",
            "resolved_code": None,
            "group_name": None,
            "site_name": None,
        }
    site_name = normalize_target_code(client.site_name)
    group_name = normalize_target_code(client.group_name)
    if site_name:
        resolved_scope = "site"
        resolved_code = site_name
    elif group_name:
        resolved_scope = "group"
        resolved_code = group_name
    else:
        resolved_scope = "global"
        resolved_code = None
    return {
        "resolved_scope": resolved_scope,
        "resolved_code": resolved_code,
        "group_name": group_name,
        "site_name": site_name,
    }


def target_matches(scope: str | None, code: str | None, target_context: dict[str, str | None]) -> bool:
    normalized_scope = normalize_target_scope(scope)
    normalized_code = normalize_target_code(code)
    if normalized_scope == "global":
        return True
    if normalized_scope == "group":
        return normalized_code is not None and normalized_code == target_context.get("group_name")
    if normalized_scope == "site":
        return normalized_code is not None and normalized_code == target_context.get("site_name")
    return False


def resolve_manifest_client(db: Session, client_code: str | None) -> Client | None:
    normalized = normalize_target_code(client_code)
    if not normalized:
        return None
    return db.execute(select(Client).where(Client.client_code == normalized)).scalar_one_or_none()


def current_manifest_payload(db: Session, client: Client | None = None) -> dict[str, Any]:
    settings = get_settings(db)
    target_context = build_target_context(client)
    media_items = db.execute(select(MediaItem).order_by(MediaItem.id.asc())).scalars().all()
    playlists = (
        db.execute(select(Playlist).options(joinedload(Playlist.items).joinedload(PlaylistItem.media)).order_by(Playlist.id.asc()))
        .unique()
        .scalars()
        .all()
    )
    schedules = db.execute(select(ScheduleRule).order_by(ScheduleRule.priority.asc(), ScheduleRule.id.asc())).scalars().all()

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    eligible_playlists: list[Playlist] = []
    eligible_playlist_ids: set[int] = set()
    for playlist in playlists:
        ensure_playlist_code(db, playlist)
        if target_matches(playlist.target_scope, playlist.target_code, target_context):
            eligible_playlists.append(playlist)
            eligible_playlist_ids.add(playlist.id)

    schedule_payload = []
    referenced_playlist_ids: set[int] = set()
    for schedule in schedules:
        ensure_schedule_code(db, schedule)
        if not target_matches(schedule.target_scope, schedule.target_code, target_context):
            continue
        if schedule.playlist_id not in eligible_playlist_ids:
            continue
        referenced_playlist_ids.add(schedule.playlist_id)
        schedule_payload.append(
            {
                "schedule_code": schedule.schedule_code,
                "name": schedule.name,
                "playlist_code": schedule.playlist.playlist_code if schedule.playlist else "",
                "target_scope": normalize_target_scope(schedule.target_scope),
                "target_code": normalize_target_code(schedule.target_code),
                "weekdays": [int(day) for day in schedule.weekdays.split(",") if day != ""],
                "start_time": schedule.start_time,
                "end_time": schedule.end_time,
                "play_count": schedule.play_count,
                "priority": schedule.priority,
                "enabled": schedule.enabled,
            }
        )

    filtered_playlists = [playlist for playlist in eligible_playlists if playlist.id in referenced_playlist_ids]
    referenced_media_codes: set[str] = set()
    playlist_payload = []
    for playlist in filtered_playlists:
        items_payload = []
        for item in playlist.items:
            if not item.media:
                continue
            ensure_media_code(db, item.media)
            referenced_media_codes.add(item.media.media_code)
            items_payload.append(
                {
                    "media_code": item.media.media_code,
                    "position": item.position,
                }
            )
        playlist_payload.append(
            {
                "playlist_code": playlist.playlist_code,
                "name": playlist.name,
                "description": playlist.description,
                "display_title": playlist.display_title,
                "target_scope": normalize_target_scope(playlist.target_scope),
                "target_code": normalize_target_code(playlist.target_code),
                "enabled": playlist.enabled,
                "items": items_payload,
            }
        )

    media_payload = []
    for item in media_items:
        ensure_media_code(db, item)
        if item.media_code not in referenced_media_codes:
            continue
        if item.local_file_name and not item.checksum and (MEDIA_DIR / item.local_file_name).exists():
            file_path = MEDIA_DIR / item.local_file_name
            item.checksum = sha256_of_path(file_path)
            item.size_bytes = file_path.stat().st_size
        media_payload.append(
            {
                "media_code": item.media_code,
                "title": item.title,
                "source_url": media_public_url(settings, item),
                "checksum": item.checksum,
                "size_bytes": item.size_bytes,
                "enabled": item.enabled,
            }
        )

    payload = {
        "generated_at": generated_at,
        "target": {
            "scope": target_context["resolved_scope"],
            "target_code": target_context["resolved_code"],
        },
        "ui": {
            "show_player_brand": settings["show_player_brand"].lower() == "true",
            "default_fullscreen": settings["default_fullscreen"].lower() == "true",
        },
        "media": media_payload,
        "playlists": playlist_payload,
        "schedules": schedule_payload,
        "package": {
            "latest_version": settings["latest_version"],
            "latest_package_url": settings["latest_package_url"],
        },
    }
    db.commit()
    return payload


def payload_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_manifest_snapshot(db: Session, client: Client | None = None) -> ManifestSnapshot:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    payload = current_manifest_payload(db, client)
    checksum = payload_checksum(payload)
    latest = (
        db.execute(
            select(ManifestSnapshot)
            .where(
                ManifestSnapshot.scope == payload["target"]["scope"],
                ManifestSnapshot.target_code.is_(payload["target"]["target_code"])
                if payload["target"]["target_code"] is None
                else ManifestSnapshot.target_code == payload["target"]["target_code"],
            )
            .order_by(ManifestSnapshot.id.desc())
        )
        .scalars()
        .first()
    )
    if latest and latest.checksum == checksum:
        return latest

    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    while db.execute(select(ManifestSnapshot).where(ManifestSnapshot.manifest_version == version)).scalar_one_or_none():
        time.sleep(0.001)
        version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    payload["manifest_version"] = version
    payload["generated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    checksum = payload_checksum(payload)
    snapshot = ManifestSnapshot(
        manifest_version=version,
        checksum=checksum,
        scope=payload["target"]["scope"],
        target_code=payload["target"]["target_code"],
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    (MANIFEST_DIR / f"{version}.json").write_text(snapshot.payload_json, encoding="utf-8")
    return snapshot


def manifest_metadata(db: Session, client_code: str | None = None) -> dict[str, Any]:
    snapshot = ensure_manifest_snapshot(db, resolve_manifest_client(db, client_code))
    return {
        "manifest_version": snapshot.manifest_version,
        "checksum": snapshot.checksum,
        "scope": snapshot.scope,
        "target_code": snapshot.target_code,
        "published_at": snapshot.published_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "download_url": f"/api/client-manifest/{snapshot.manifest_version}",
    }


def import_client_manifest(db: Session, manifest: dict[str, Any]) -> dict[str, Any]:
    results = {"media": 0, "playlists": 0, "schedules": 0}
    media_by_code: dict[str, MediaItem] = {}

    current_codes = {row.media_code for row in db.execute(select(MediaItem)).scalars().all()}
    incoming_codes = {row["media_code"] for row in manifest.get("media", [])}

    for media_payload in manifest.get("media", []):
        existing = db.execute(select(MediaItem).where(MediaItem.media_code == media_payload["media_code"])).scalar_one_or_none()
        if not existing:
            existing = MediaItem(
                media_code=media_payload["media_code"],
                title=media_payload["title"],
                source_url=media_payload["source_url"],
            )
            db.add(existing)
        existing.title = media_payload["title"]
        existing.source_url = media_payload["source_url"]
        existing.checksum = media_payload.get("checksum")
        existing.size_bytes = media_payload.get("size_bytes")
        existing.enabled = media_payload.get("enabled", True)
        media_by_code[existing.media_code] = existing
        results["media"] += 1

    for obsolete in current_codes - incoming_codes:
        record = db.execute(select(MediaItem).where(MediaItem.media_code == obsolete)).scalar_one_or_none()
        if record:
            db.delete(record)

    db.flush()

    current_playlists = {row.playlist_code: row for row in db.execute(select(Playlist)).scalars().all()}
    incoming_playlist_codes = {row["playlist_code"] for row in manifest.get("playlists", [])}

    for playlist_payload in manifest.get("playlists", []):
        existing = current_playlists.get(playlist_payload["playlist_code"])
        if not existing:
            existing = Playlist(
                playlist_code=playlist_payload["playlist_code"],
                name=playlist_payload["name"],
            )
            db.add(existing)
        existing.name = playlist_payload["name"]
        existing.description = playlist_payload.get("description")
        existing.display_title = playlist_payload.get("display_title")
        existing.target_scope = normalize_target_scope(playlist_payload.get("target_scope"))
        existing.target_code = normalize_target_code(playlist_payload.get("target_code"))
        existing.enabled = playlist_payload.get("enabled", True)
        replace_playlist_items(
            db,
            existing,
            [
                {"media_id": media_by_code[item["media_code"]].id, "position": item.get("position", index + 1)}
                for index, item in enumerate(playlist_payload.get("items", []))
                if item["media_code"] in media_by_code
            ],
        )
        results["playlists"] += 1

    for obsolete_code, playlist in current_playlists.items():
        if obsolete_code not in incoming_playlist_codes:
            db.delete(playlist)

    db.flush()

    current_schedules = {row.schedule_code: row for row in db.execute(select(ScheduleRule)).scalars().all()}
    incoming_schedule_codes = {row["schedule_code"] for row in manifest.get("schedules", [])}
    playlist_by_code = {row.playlist_code: row for row in db.execute(select(Playlist)).scalars().all()}

    for schedule_payload in manifest.get("schedules", []):
        playlist = playlist_by_code.get(schedule_payload["playlist_code"])
        if not playlist:
            continue
        existing = current_schedules.get(schedule_payload["schedule_code"])
        if not existing:
            existing = ScheduleRule(
                schedule_code=schedule_payload["schedule_code"],
                name=schedule_payload["name"],
                playlist_id=playlist.id,
                target_scope=normalize_target_scope(schedule_payload.get("target_scope")),
                target_code=normalize_target_code(schedule_payload.get("target_code")),
                start_time=schedule_payload["start_time"],
                end_time=schedule_payload["end_time"],
            )
            db.add(existing)
        existing.name = schedule_payload["name"]
        existing.playlist_id = playlist.id
        existing.target_scope = normalize_target_scope(schedule_payload.get("target_scope"))
        existing.target_code = normalize_target_code(schedule_payload.get("target_code"))
        existing.weekdays = ",".join(str(day) for day in schedule_payload.get("weekdays", [0, 1, 2, 3, 4, 5, 6]))
        existing.start_time = schedule_payload["start_time"]
        existing.end_time = schedule_payload["end_time"]
        existing.play_count = schedule_payload.get("play_count", 0)
        existing.priority = schedule_payload.get("priority", 100)
        existing.enabled = schedule_payload.get("enabled", True)
        results["schedules"] += 1

    for obsolete_code, schedule in current_schedules.items():
        if obsolete_code not in incoming_schedule_codes:
            db.delete(schedule)

    db.commit()
    apply_manifest_settings(db, manifest)
    return results


def apply_manifest_settings(db: Session, manifest: dict[str, Any]) -> None:
    ui = manifest.get("ui", {})
    package = manifest.get("package", {})
    set_settings(
        db,
        {
            "show_player_brand": str(bool(ui.get("show_player_brand", False))).lower(),
            "default_fullscreen": str(bool(ui.get("default_fullscreen", False))).lower(),
            "latest_version": package.get("latest_version", APP_VERSION),
            "latest_package_url": package.get("latest_package_url", ""),
            "current_manifest_version": manifest.get("manifest_version", ""),
        },
    )


def sync_manifest_media(db: Session) -> dict[str, Any]:
    summary = {"downloaded": [], "unchanged": [], "failed": [], "deleted": []}
    media_items = db.execute(select(MediaItem).where(MediaItem.enabled.is_(True))).scalars().all()

    for item in media_items:
        target_name = item.local_file_name or sanitize_filename(item.title, item.source_url)
        target_path = MEDIA_DIR / target_name
        needs_download = not target_path.exists()
        if item.checksum and target_path.exists():
            local_checksum = sha256_of_path(target_path)
            needs_download = local_checksum != item.checksum
        if not item.checksum and target_path.exists():
            needs_download = False
        if not needs_download:
            item.local_file_name = target_name
            item.last_synced_at = datetime.utcnow()
            summary["unchanged"].append(item.media_code)
            continue

        temp_path = MEDIA_DIR / f"{target_name}.part"
        try:
            checksum, size_bytes = download_to_file(item.source_url, temp_path)
            if item.checksum and checksum != item.checksum:
                raise ValueError(f"checksum 不符：預期 {item.checksum}，實際 {checksum}")
            temp_path.replace(target_path)
            item.local_file_name = target_name
            item.checksum = item.checksum or checksum
            item.size_bytes = item.size_bytes or size_bytes
            item.last_synced_at = datetime.utcnow()
            summary["downloaded"].append(item.media_code)
        except Exception as exc:  # noqa: BLE001
            temp_path.unlink(missing_ok=True)
            summary["failed"].append({"media_code": item.media_code, "error": str(exc)})

    db.commit()
    summary["deleted"] = cleanup_unused_files(db)
    return summary


def central_headers(settings: dict[str, str]) -> dict[str, str]:
    headers = {}
    if settings.get("client_token"):
        headers["X-Client-Token"] = settings["client_token"]
    return headers


def report_sync_result_to_central(db: Session, summary: dict[str, Any], status: str) -> None:
    settings = get_settings(db)
    central_base = settings.get("central_base_url", "").rstrip("/")
    client_code = settings.get("client_code", "")
    if not central_base or not client_code:
        return
    payload = {
        "client_code": client_code,
        "manifest_version": settings.get("current_manifest_version", "") or None,
        "status": status,
        "summary": summary,
    }
    requests.post(
        f"{central_base}/api/client-events/sync-result",
        json=payload,
        headers=central_headers(settings),
        timeout=15,
    ).raise_for_status()


def heartbeat_to_central(db: Session, player_status: str | None = None) -> None:
    settings = get_settings(db)
    central_base = settings.get("central_base_url", "").rstrip("/")
    client_code = settings.get("client_code", "")
    if not central_base or not client_code or not settings.get("client_token"):
        return
    payload = {
        "client_code": client_code,
        "app_version": APP_VERSION,
        "manifest_version": settings.get("current_manifest_version") or None,
        "ip": None,
        "disk_free_bytes": shutil.disk_usage(MEDIA_DIR).free if MEDIA_DIR.exists() else None,
        "last_sync_status": settings.get("last_sync_status") or None,
        "last_player_status": player_status,
    }
    requests.post(
        f"{central_base}/api/clients/heartbeat",
        json=payload,
        headers=central_headers(settings),
        timeout=15,
    ).raise_for_status()


def register_client_with_central(db: Session) -> dict[str, Any]:
    settings = get_settings(db)
    central_base = settings.get("central_base_url", "").rstrip("/")
    if not central_base:
        return {"message": "尚未設定 central_base_url。"}
    client_code = settings.get("client_code", "").strip()
    client_name = settings.get("client_name", "").strip()
    if not client_code or not client_name:
        return {"message": "尚未設定 client_code 或 client_name。"}
    payload = {
        "client_code": client_code,
        "name": client_name,
        "site_name": settings.get("client_site_name") or None,
        "group_name": settings.get("client_group_name") or None,
        "app_version": APP_VERSION,
    }
    response = requests.post(f"{central_base}/api/clients/register", json=payload, timeout=15)
    response.raise_for_status()
    result = response.json()
    set_settings(
        db,
        {
            "client_token": result["client_token"],
            "latest_version": result.get("latest_version", APP_VERSION),
            "latest_package_url": result.get("latest_package_url", ""),
        },
    )
    return result


def pull_manifest_and_sync(db: Session) -> dict[str, Any]:
    settings = get_settings(db)
    central_base = settings.get("central_base_url", "").rstrip("/")
    if not central_base:
        return {"message": "尚未設定 central_base_url。"}
    if not settings.get("client_code") or not settings.get("client_token"):
        register_result = register_client_with_central(db)
        if register_result.get("message"):
            return register_result
        settings = get_settings(db)

    metadata_response = requests.get(
        f"{central_base}/api/client-manifest/latest",
        params={"client_code": settings["client_code"]},
        headers=central_headers(settings),
        timeout=15,
    )
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    current_version = settings.get("current_manifest_version", "")

    if metadata["manifest_version"] == current_version:
        set_settings(db, {"last_sync_status": "manifest-unchanged"})
        try:
            heartbeat_to_central(db, player_status="manifest-unchanged")
        except Exception:
            pass
        return {"message": "manifest 未變更。", "metadata": metadata}

    manifest_response = requests.get(
        f"{central_base}/api/client-manifest/{metadata['manifest_version']}",
        params={"client_code": settings["client_code"]},
        headers=central_headers(settings),
        timeout=30,
    )
    manifest_response.raise_for_status()
    manifest = manifest_response.json()

    imported = import_client_manifest(db, manifest)
    media_summary = sync_manifest_media(db)
    set_settings(db, {"last_sync_status": "success"})
    result = {"metadata": metadata, "imported": imported, "media": media_summary}
    try:
        report_sync_result_to_central(db, result, "success")
        heartbeat_to_central(db, player_status="sync-success")
    except Exception:
        pass
    return result


def run_sync_job(session_factory) -> None:
    if SYNC_STATE["running"]:
        return
    SYNC_STATE["running"] = True
    SYNC_STATE["last_started_at"] = datetime.utcnow().isoformat()
    SYNC_STATE["last_error"] = None
    try:
        with session_factory() as db:
            result = pull_manifest_and_sync(db) if not is_central_role() else manifest_metadata(db)
        SYNC_STATE["last_summary"] = result
    except Exception as exc:  # noqa: BLE001
        SYNC_STATE["last_error"] = str(exc)
        with session_factory() as db:
            set_settings(db, {"last_sync_status": f"error:{exc}"})
            try:
                report_sync_result_to_central(db, {"error": str(exc)}, "error")
            except Exception:
                pass
    finally:
        SYNC_STATE["running"] = False
        SYNC_STATE["last_finished_at"] = datetime.utcnow().isoformat()


def start_sync_loop(session_factory) -> None:
    def worker() -> None:
        while True:
            with session_factory() as db:
                settings = get_settings(db)
                interval = int(settings["sync_interval_seconds"])
                should_run = is_central_role() or bool(settings.get("central_base_url", "").strip())
            if should_run:
                run_sync_job(session_factory)
            time.sleep(interval)

    thread = threading.Thread(target=worker, daemon=True, name="manifest-sync-loop")
    thread.start()


def version_info(db: Session) -> dict[str, Any]:
    settings = get_settings(db)
    latest_version = settings["latest_version"]
    latest_package_url = settings["latest_package_url"]
    return {
        "app_role": role_name(),
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "latest_package_url": latest_package_url,
        "update_available": latest_version != APP_VERSION,
        "current_manifest_version": settings.get("current_manifest_version", ""),
    }


def delete_media_record(db: Session, item: MediaItem) -> dict[str, Any]:
    local_file_name = item.local_file_name
    db.delete(item)
    db.commit()

    deleted_file = False
    if local_file_name:
        remaining = db.execute(select(MediaItem).where(MediaItem.local_file_name == local_file_name)).scalar_one_or_none()
        if not remaining:
            target_path = MEDIA_DIR / local_file_name
            if target_path.exists():
                target_path.unlink(missing_ok=True)
                deleted_file = True
    return {"ok": True, "deleted_file": deleted_file}


def create_admin_session() -> str:
    token = secrets.token_urlsafe(32)
    ADMIN_SESSIONS.add(token)
    return token


def is_admin_session_valid(token: str | None) -> bool:
    return bool(token and token in ADMIN_SESSIONS)


def destroy_admin_session(token: str | None) -> None:
    if token:
        ADMIN_SESSIONS.discard(token)


def mark_cycle_complete(db: Session, schedule_id: int) -> dict[str, Any]:
    schedule = db.get(ScheduleRule, schedule_id)
    if not schedule:
        return {"ok": False, "message": "找不到排程。"}
    today = now_in_timezone(db).date().isoformat()
    reset_schedule_counter_if_needed(db, schedule, today)
    schedule.current_play_count += 1
    db.commit()
    try:
        report_playback_event(
            db,
            {
                "schedule_id": schedule.id,
                "playlist_id": schedule.playlist_id,
                "completed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception:
        pass
    return {
        "ok": True,
        "schedule_id": schedule.id,
        "current_play_count": schedule.current_play_count,
        "play_count": schedule.play_count,
    }


def report_playback_event(db: Session, data: dict[str, Any]) -> None:
    settings = get_settings(db)
    central_base = settings.get("central_base_url", "").rstrip("/")
    client_code = settings.get("client_code", "")
    if not central_base or not client_code or not settings.get("client_token"):
        return
    payload = {
        "client_code": client_code,
        "schedule_id": data["schedule_id"],
        "playlist_id": data["playlist_id"],
        "completed_at": data["completed_at"],
        "manifest_version": settings.get("current_manifest_version") or None,
    }
    requests.post(
        f"{central_base}/api/client-events/playback",
        json=payload,
        headers=central_headers(settings),
        timeout=15,
    ).raise_for_status()


def get_or_create_client(db: Session, client_code: str, default_name: str) -> Client:
    client = db.execute(select(Client).where(Client.client_code == client_code)).scalar_one_or_none()
    if client:
        return client
    client = Client(client_code=client_code, name=default_name, client_token=secrets.token_urlsafe(32))
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def register_client(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    client = get_or_create_client(db, payload["client_code"], payload["name"])
    client.name = payload["name"]
    client.site_name = payload.get("site_name")
    client.group_name = payload.get("group_name")
    client.last_app_version = payload["app_version"]
    client.last_seen_at = datetime.utcnow()
    if not client.client_token:
        client.client_token = secrets.token_urlsafe(32)
    db.commit()
    settings = get_settings(db)
    return {
        "client_code": client.client_code,
        "client_token": client.client_token,
        "latest_version": settings["latest_version"],
        "latest_package_url": settings["latest_package_url"],
    }


def verify_client_token(db: Session, client_code: str, client_token: str | None) -> Client:
    client = db.execute(select(Client).where(Client.client_code == client_code)).scalar_one_or_none()
    if not client or not client_token or client.client_token != client_token:
        raise PermissionError("client 驗證失敗。")
    return client


def record_client_heartbeat(db: Session, payload: dict[str, Any], client_token: str | None) -> dict[str, Any]:
    client = verify_client_token(db, payload["client_code"], client_token)
    client.last_seen_at = datetime.utcnow()
    if payload.get("app_version"):
        client.last_app_version = payload["app_version"]
    if payload.get("manifest_version") is not None:
        client.last_manifest_version = payload.get("manifest_version")
    if payload.get("last_sync_status") is not None:
        client.last_sync_status = payload.get("last_sync_status")
    if payload.get("last_player_status") is not None:
        client.last_player_status = payload.get("last_player_status")
    if payload.get("ip") is not None:
        client.last_ip = payload.get("ip")
    if payload.get("disk_free_bytes") is not None:
        client.disk_free_bytes = payload.get("disk_free_bytes")
    db.commit()
    return {"ok": True, "client_code": client.client_code, "last_seen_at": client.last_seen_at.isoformat()}


def record_client_event(db: Session, client_code: str, event_type: str, payload: dict[str, Any], client_token: str | None) -> dict[str, Any]:
    client = verify_client_token(db, client_code, client_token)
    db.add(ClientEvent(client_code=client_code, event_type=event_type, payload_json=json.dumps(payload, ensure_ascii=False)))
    client.last_seen_at = datetime.utcnow()
    if event_type == "playback":
        client.last_player_status = payload.get("completed_at")
        client.last_manifest_version = payload.get("manifest_version")
    if event_type == "sync-result":
        client.last_sync_status = payload.get("status")
        client.last_manifest_version = payload.get("manifest_version")
    db.commit()
    return {"ok": True}


def list_clients_summary(db: Session) -> list[dict[str, Any]]:
    clients = db.execute(select(Client).order_by(Client.client_code.asc())).scalars().all()
    return [
        {
            "client_code": item.client_code,
            "name": item.name,
            "site_name": item.site_name,
            "group_name": item.group_name,
            "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
            "last_manifest_version": item.last_manifest_version,
            "last_app_version": item.last_app_version,
            "last_sync_status": item.last_sync_status,
            "last_player_status": item.last_player_status,
            "disk_free_bytes": item.disk_free_bytes,
        }
        for item in clients
    ]


def ensure_schema(session_factory) -> None:
    with session_factory() as db:
        manifest_columns = {row[1] for row in db.execute(text("PRAGMA table_info(media_items)")).fetchall()}
        if "media_code" not in manifest_columns:
            db.execute(text("ALTER TABLE media_items ADD COLUMN media_code VARCHAR(100)"))
        if "checksum" not in manifest_columns:
            db.execute(text("ALTER TABLE media_items ADD COLUMN checksum VARCHAR(128)"))
        if "size_bytes" not in manifest_columns:
            db.execute(text("ALTER TABLE media_items ADD COLUMN size_bytes INTEGER"))

        playlist_columns = {row[1] for row in db.execute(text("PRAGMA table_info(playlists)")).fetchall()}
        if "display_title" not in playlist_columns:
            db.execute(text("ALTER TABLE playlists ADD COLUMN display_title VARCHAR(200)"))
        if "playlist_code" not in playlist_columns:
            db.execute(text("ALTER TABLE playlists ADD COLUMN playlist_code VARCHAR(100)"))
        if "target_scope" not in playlist_columns:
            db.execute(text("ALTER TABLE playlists ADD COLUMN target_scope VARCHAR(20) DEFAULT 'global'"))
        if "target_code" not in playlist_columns:
            db.execute(text("ALTER TABLE playlists ADD COLUMN target_code VARCHAR(200)"))

        schedule_columns = {row[1] for row in db.execute(text("PRAGMA table_info(schedule_rules)")).fetchall()}
        if "schedule_code" not in schedule_columns:
            db.execute(text("ALTER TABLE schedule_rules ADD COLUMN schedule_code VARCHAR(100)"))
        if "target_scope" not in schedule_columns:
            db.execute(text("ALTER TABLE schedule_rules ADD COLUMN target_scope VARCHAR(20) DEFAULT 'global'"))
        if "target_code" not in schedule_columns:
            db.execute(text("ALTER TABLE schedule_rules ADD COLUMN target_code VARCHAR(200)"))
        db.execute(text("UPDATE playlists SET target_scope = 'global' WHERE target_scope IS NULL OR target_scope = ''"))
        db.execute(text("UPDATE schedule_rules SET target_scope = 'global' WHERE target_scope IS NULL OR target_scope = ''"))
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_media_items_media_code ON media_items (media_code)"))
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_playlists_playlist_code ON playlists (playlist_code)"))
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_schedule_rules_schedule_code ON schedule_rules (schedule_code)"))
        db.commit()

        media_items = db.execute(select(MediaItem)).scalars().all()
        for item in media_items:
            ensure_media_code(db, item)
        playlists = db.execute(select(Playlist)).scalars().all()
        for playlist in playlists:
            ensure_playlist_code(db, playlist)
        schedules = db.execute(select(ScheduleRule)).scalars().all()
        for schedule in schedules:
            ensure_schedule_code(db, schedule)
        db.commit()
