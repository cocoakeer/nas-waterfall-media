import os
import json
from pathlib import Path

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/app/config"))
CACHE_PATH = Path(os.getenv("CACHE_PATH", "/app/cache"))

CONFIG_PATH.mkdir(parents=True, exist_ok=True)
CACHE_PATH.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = CONFIG_PATH / "settings.json"


def load_settings():
    if not SETTINGS_FILE.exists():
        default = {
            "media_root": "/media",
            "slide_delay": 5,
            "view_mode": "waterfall"
        }
        save_settings(default)
        return default
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
