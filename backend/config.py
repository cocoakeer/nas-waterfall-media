import os
import json
from pathlib import Path

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/config"))
CACHE_PATH = Path(os.getenv("CACHE_PATH", "/cache"))

CONFIG_PATH.mkdir(parents=True, exist_ok=True)
CACHE_PATH.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = CONFIG_PATH / "settings.json"


def _default_slide_delay() -> int:
    """幻灯片默认切换间隔（秒），优先读环境变量 SLIDE_DEFAULT_DELAY。"""
    try:
        return int(os.getenv("SLIDE_DEFAULT_DELAY", "5"))
    except (TypeError, ValueError):
        return 5


def load_settings():
    if not SETTINGS_FILE.exists():
        default = {
            "media_root": os.getenv("MEDIA_ROOT", "/media"),
            "slide_delay": _default_slide_delay(),
            "slide_loop": True,
            "view_mode": "waterfall",
        }
        save_settings(default)
        return default
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}  # 文件损坏或不可读时回退默认值，避免接口 500
    # 兜底：旧配置文件缺字段时补默认值（环境变量优先）
    if "slide_delay" not in data:
        data["slide_delay"] = _default_slide_delay()
    if "slide_loop" not in data:
        data["slide_loop"] = True
    return data


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
