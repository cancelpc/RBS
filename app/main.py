from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import APP_ROLE, MANIFEST_DIR, MEDIA_DIR, STATIC_DIR, STORAGE_DIR, UPDATES_DIR
from app.database import Base, SessionLocal, engine
from app.models import MediaItem, Playlist, PlaylistItem, ScheduleRule, ManifestSnapshot
from app.schemas import (
    AdminLoginPayload,
    ClientHeartbeatPayload,
    ClientRegisterPayload,
    CycleCompletePayload,
    MediaCreate,
    PlaybackEventPayload,
    PlaylistCreate,
    ScheduleCreate,
    SettingsPayload,
    SyncResultPayload,
)
from app.services import (
    SYNC_STATE,
    build_player_payload,
    create_admin_session,
    delete_media_record,
    destroy_admin_session,
    ensure_manifest_snapshot,
    ensure_media_code,
    ensure_playlist_code,
    ensure_schedule_code,
    ensure_schema,
    get_settings,
    import_client_manifest,
    is_admin_session_valid,
    list_clients_summary,
    manifest_metadata,
    mark_cycle_complete,
    pull_manifest_and_sync,
    record_client_event,
    record_client_heartbeat,
    register_client,
    replace_playlist_items,
    role_name,
    save_uploaded_media_file,
    set_settings,
    start_sync_loop,
    sync_local_media,
    version_info,
)


for path in (STORAGE_DIR, MEDIA_DIR, UPDATES_DIR, MANIFEST_DIR):
    path.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)
ensure_schema(SessionLocal)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(admin_session: str | None = Cookie(default=None)):
    if not is_admin_session_valid(admin_session):
        raise HTTPException(status_code=401, detail="請先登入管理後台。")
    return True


def require_role(expected: str):
    def checker() -> bool:
        if role_name() != expected:
            raise HTTPException(status_code=403, detail=f"此 API 僅限 {expected} 模式。")
        return True

    return checker


def commit_manifest_change(db: Session):
    db.commit()
    ensure_manifest_snapshot(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_sync_loop(SessionLocal)
    yield


app = FastAPI(title="Rotating Banner System", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/updates", StaticFiles(directory=UPDATES_DIR), name="updates")


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "player.html")


@app.get("/admin")
def admin_page(admin_session: str | None = Cookie(default=None)):
    if not is_admin_session_valid(admin_session):
        return RedirectResponse(url="/admin-login", status_code=303)
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/admin-login")
def admin_login_page():
    return FileResponse(STATIC_DIR / "admin-login.html")


@app.get("/api/system/info")
def system_info(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return {
        "app_role": APP_ROLE,
        "client_code": settings.get("client_code", ""),
        "client_name": settings.get("client_name", ""),
        "central_base_url": settings.get("central_base_url", ""),
    }


@app.get("/api/admin/status")
def admin_status(admin_session: str | None = Cookie(default=None)):
    return {"authenticated": is_admin_session_valid(admin_session)}


@app.post("/api/admin/login")
def admin_login(payload: AdminLoginPayload, response: Response, db: Session = Depends(get_db)):
    settings = get_settings(db)
    if payload.password != settings["admin_password"]:
        raise HTTPException(status_code=401, detail="管理密碼錯誤。")
    token = create_admin_session()
    response.set_cookie("admin_session", token, httponly=True, samesite="lax")
    return {"ok": True}


@app.post("/api/admin/logout")
def admin_logout(response: Response, admin_session: str | None = Cookie(default=None)):
    destroy_admin_session(admin_session)
    response.delete_cookie("admin_session")
    return {"ok": True}


@app.get("/api/media")
def list_media(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return db.execute(select(MediaItem).order_by(MediaItem.id.asc())).scalars().all()


@app.post("/api/media")
def create_media(
    payload: MediaCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    item = MediaItem(media_code="", **payload.model_dump())
    db.add(item)
    db.flush()
    ensure_media_code(db, item)
    commit_manifest_change(db)
    db.refresh(item)
    return item


@app.put("/api/media/{media_id}")
def update_media(
    media_id: int,
    payload: MediaCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到影片。")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    ensure_media_code(db, item)
    commit_manifest_change(db)
    db.refresh(item)
    return item


@app.delete("/api/media/{media_id}")
def delete_media(
    media_id: int,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到影片。")
    result = delete_media_record(db, item)
    ensure_manifest_snapshot(db)
    return result


@app.post("/api/media/upload")
async def upload_media(
    files: list[UploadFile] = File(...),
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    created: list[dict] = []
    for upload in files:
        if not upload.filename:
            continue
        local_name, checksum, size_bytes = save_uploaded_media_file(upload.file, upload.filename)
        item = MediaItem(
            media_code="",
            title=Path(upload.filename).stem,
            source_url=f"local-upload://{local_name}",
            local_file_name=local_name,
            checksum=checksum,
            size_bytes=size_bytes,
            enabled=True,
        )
        db.add(item)
        db.flush()
        ensure_media_code(db, item)
        created.append(
            {
                "id": item.id,
                "title": item.title,
                "local_file_name": item.local_file_name,
            }
        )
        await upload.close()
    commit_manifest_change(db)
    return {"ok": True, "count": len(created), "items": created}


@app.get("/api/playlists")
def list_playlists(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    playlists = (
        db.execute(select(Playlist).options(joinedload(Playlist.items).joinedload(PlaylistItem.media)).order_by(Playlist.id))
        .unique()
        .scalars()
        .all()
    )
    return [
        {
            "id": playlist.id,
            "playlist_code": playlist.playlist_code,
            "name": playlist.name,
            "description": playlist.description,
            "display_title": playlist.display_title,
            "target_scope": playlist.target_scope,
            "target_code": playlist.target_code,
            "enabled": playlist.enabled,
            "items": [
                {
                    "id": item.id,
                    "position": item.position,
                    "media_id": item.media_id,
                    "media_code": item.media.media_code,
                    "media_title": item.media.title,
                }
                for item in playlist.items
            ],
        }
        for playlist in playlists
    ]


@app.post("/api/playlists")
def create_playlist(
    payload: PlaylistCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(Playlist).where(Playlist.name == payload.name)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"播放清單名稱已存在：{payload.name}")
    playlist = Playlist(
        playlist_code="",
        name=payload.name,
        description=payload.description,
        display_title=payload.display_title,
        target_scope=payload.target_scope,
        target_code=payload.target_code,
        enabled=payload.enabled,
    )
    db.add(playlist)
    try:
        db.flush()
        ensure_playlist_code(db, playlist)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"播放清單名稱已存在：{payload.name}") from None
    replace_playlist_items(db, playlist, [item.model_dump() for item in payload.items])
    commit_manifest_change(db)
    db.refresh(playlist)
    return {"ok": True, "id": playlist.id}


@app.put("/api/playlists/{playlist_id}")
def update_playlist(
    playlist_id: int,
    payload: PlaylistCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="找不到播放清單。")
    duplicate = (
        db.execute(select(Playlist).where(Playlist.name == payload.name, Playlist.id != playlist_id)).scalar_one_or_none()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail=f"播放清單名稱已存在：{payload.name}")
    playlist.name = payload.name
    playlist.description = payload.description
    playlist.display_title = payload.display_title
    playlist.target_scope = payload.target_scope
    playlist.target_code = payload.target_code
    playlist.enabled = payload.enabled
    ensure_playlist_code(db, playlist)
    replace_playlist_items(db, playlist, [item.model_dump() for item in payload.items])
    try:
        commit_manifest_change(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"播放清單名稱已存在：{payload.name}") from None
    return {"ok": True}


@app.delete("/api/playlists/{playlist_id}")
def delete_playlist(
    playlist_id: int,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="找不到播放清單。")
    schedules = db.execute(select(ScheduleRule).where(ScheduleRule.playlist_id == playlist_id)).scalars().all()
    for schedule in schedules:
        db.delete(schedule)
    db.delete(playlist)
    db.commit()
    ensure_manifest_snapshot(db)
    return {"ok": True}


@app.get("/api/schedules")
def list_schedules(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    schedules = db.execute(select(ScheduleRule).order_by(ScheduleRule.priority.asc(), ScheduleRule.id.asc())).scalars().all()
    return [
        {
            "id": schedule.id,
            "schedule_code": schedule.schedule_code,
            "name": schedule.name,
            "playlist_id": schedule.playlist_id,
            "target_scope": schedule.target_scope,
            "target_code": schedule.target_code,
            "weekdays": [int(day) for day in schedule.weekdays.split(",") if day != ""],
            "start_date": schedule.start_date or None,
            "end_date": schedule.end_date,
            "start_time": schedule.start_time,
            "end_time": schedule.end_time,
            "play_count": schedule.play_count,
            "priority": schedule.priority,
            "enabled": schedule.enabled,
            "current_play_count": schedule.current_play_count,
            "last_reset_date": schedule.last_reset_date,
        }
        for schedule in schedules
    ]


@app.post("/api/schedules")
def create_schedule(
    payload: ScheduleCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    schedule = ScheduleRule(
        schedule_code="",
        name=payload.name,
        playlist_id=payload.playlist_id,
        target_scope=payload.target_scope,
        target_code=payload.target_code,
        weekdays=",".join(str(day) for day in payload.weekdays),
        start_date=payload.start_date or "",
        end_date=payload.end_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        play_count=payload.play_count,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    db.add(schedule)
    db.flush()
    ensure_schedule_code(db, schedule)
    commit_manifest_change(db)
    db.refresh(schedule)
    return schedule


@app.put("/api/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    payload: ScheduleCreate,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    schedule = db.get(ScheduleRule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="找不到排程。")
    schedule.name = payload.name
    schedule.playlist_id = payload.playlist_id
    schedule.target_scope = payload.target_scope
    schedule.target_code = payload.target_code
    schedule.weekdays = ",".join(str(day) for day in payload.weekdays)
    schedule.start_date = payload.start_date or ""
    schedule.end_date = payload.end_date
    schedule.start_time = payload.start_time
    schedule.end_time = payload.end_time
    schedule.play_count = payload.play_count
    schedule.priority = payload.priority
    schedule.enabled = payload.enabled
    ensure_schedule_code(db, schedule)
    commit_manifest_change(db)
    db.refresh(schedule)
    return schedule


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    schedule = db.get(ScheduleRule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="找不到排程。")
    db.delete(schedule)
    db.commit()
    ensure_manifest_snapshot(db)
    return {"ok": True}


@app.get("/api/settings")
def get_settings_api(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return get_settings(db)


@app.put("/api/settings")
def update_settings(payload: SettingsPayload, _admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    result = set_settings(db, {key: str(value) for key, value in payload.model_dump().items()})
    if role_name() == "central":
        ensure_manifest_snapshot(db)
    return result


@app.post("/api/sync/local")
def sync_local(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return sync_local_media(db)


@app.post("/api/sync/upstream")
def sync_upstream(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    result = pull_manifest_and_sync(db)
    if result.get("message") == "尚未設定 central_base_url。":
        raise HTTPException(status_code=400, detail="目前未設定中央管理端 URL。")
    return result


@app.get("/api/sync/status")
def sync_status(_admin: bool = Depends(require_admin)):
    return SYNC_STATE


@app.get("/api/player/current")
def player_current(db: Session = Depends(get_db)):
    return build_player_payload(db)


@app.post("/api/player/complete-cycle")
def player_complete_cycle(payload: CycleCompletePayload, db: Session = Depends(get_db)):
    return mark_cycle_complete(db, payload.schedule_id)


@app.get("/api/version")
def get_version(db: Session = Depends(get_db)):
    return version_info(db)


@app.get("/api/clients")
def get_clients(
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    return list_clients_summary(db)


@app.post("/api/clients/register")
def api_register_client(
    payload: ClientRegisterPayload,
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    return register_client(db, payload.model_dump())


@app.post("/api/clients/heartbeat")
def api_client_heartbeat(
    payload: ClientHeartbeatPayload,
    x_client_token: str | None = Header(default=None),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    try:
        return record_client_heartbeat(db, payload.model_dump(), x_client_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/client-manifest/latest")
def api_client_manifest_latest(
    client_code: str = Query(..., min_length=1),
    x_client_token: str | None = Header(default=None),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    try:
        record_client_heartbeat(
            db,
            {
                "client_code": client_code,
                "app_version": "",
                "manifest_version": None,
                "ip": None,
                "disk_free_bytes": None,
                "last_sync_status": "manifest-check",
                "last_player_status": None,
            },
            x_client_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return manifest_metadata(db, client_code)


@app.get("/api/client-manifest/{version}")
def api_client_manifest_version(
    version: str,
    client_code: str = Query(..., min_length=1),
    x_client_token: str | None = Header(default=None),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    try:
        record_client_heartbeat(
            db,
            {
                "client_code": client_code,
                "app_version": "",
                "manifest_version": version,
                "ip": None,
                "disk_free_bytes": None,
                "last_sync_status": "manifest-download",
                "last_player_status": None,
            },
            x_client_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    snapshot = db.execute(select(ManifestSnapshot).where(ManifestSnapshot.manifest_version == version)).scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="找不到指定 manifest 版本。")
    return Response(content=snapshot.payload_json, media_type="application/json")


@app.post("/api/client-events/playback")
def api_client_playback(
    payload: PlaybackEventPayload,
    x_client_token: str | None = Header(default=None),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    try:
        return record_client_event(db, payload.client_code, "playback", payload.model_dump(), x_client_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/client-events/sync-result")
def api_client_sync_result(
    payload: SyncResultPayload,
    x_client_token: str | None = Header(default=None),
    _role: bool = Depends(require_role("central")),
    db: Session = Depends(get_db),
):
    try:
        return record_client_event(db, payload.client_code, "sync-result", payload.model_dump(), x_client_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/client/import-manifest")
def api_import_manifest(
    payload: dict,
    _admin: bool = Depends(require_admin),
    _role: bool = Depends(require_role("client")),
    db: Session = Depends(get_db),
):
    imported = import_client_manifest(db, payload)
    return {"ok": True, "imported": imported}


@app.get("/favicon.ico")
def favicon():
    icon_path = STATIC_DIR / "favicon.ico"
    if icon_path.exists():
        return FileResponse(icon_path)
    raise HTTPException(status_code=404)
