import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
MEDIA_DIR = STORAGE_DIR / "media"
UPDATES_DIR = STORAGE_DIR / "updates"
MANIFEST_DIR = STORAGE_DIR / "manifests"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = STORAGE_DIR / "banner.db"


APP_VERSION = "0.1.0"
DEFAULT_SYNC_INTERVAL_SECONDS = 300
DEFAULT_TIMEZONE = "Asia/Taipei"
DEFAULT_APP_ROLE = "client"
APP_ROLE = os.getenv("BANNER_APP_ROLE", DEFAULT_APP_ROLE).strip().lower() or DEFAULT_APP_ROLE
DEFAULT_CENTRAL_BASE_URL = os.getenv("BANNER_CENTRAL_BASE_URL", "").strip()
