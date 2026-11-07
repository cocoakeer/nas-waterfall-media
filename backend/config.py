import os
import json
import threading
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
        # 只存真正被读取的字段；media_root 来自环境变量、view_mode 从未使用
        default = {
            "slide_delay": _default_slide_delay(),
            "slide_loop": True,
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


_settings_lock = threading.Lock()


def save_settings(data: dict):
    # 原子写 + 串行化：两个管理员并发保存会共用同一个 tmp 文件，
    # 后者可能因 tmp 已被 rename 而抛 FileNotFoundError 变成 500
    with _settings_lock:
        tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, SETTINGS_FILE)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
