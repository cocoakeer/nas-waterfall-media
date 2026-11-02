"""缩略图 / 视频封面生成模块。

图片：Pillow 等比缩放到指定宽度，存为 JPEG。
视频：ffmpeg 截取首帧，等比缩放，存为 JPEG。
所有缓存写入 CACHE_PATH/thumbs/ 下，保持原目录结构，按源文件 mtime 判断是否过期。
"""
import subprocess
import threading
from pathlib import Path

from .config import CACHE_PATH

# 缩略图宽度（卡片 270px 的 2 倍，retina 屏足够清晰）
THUMB_WIDTH = 540
# 视频抽帧时间点
VIDEO_FRAME_TIME = "00:00:01"
# 缩略图最大高度，避免超长图把卡片拉得过高
THUMB_MAX_HEIGHT = 4000

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi"}
COVER_NAMES = {"cover.jpg", "cover.png", "cover.webp"}


def get_thumb_cache_path(rel_path: str) -> Path:
    """缩略图缓存绝对路径（图片与视频统一，按 stem + .jpg 命名）。"""
    p = Path(rel_path)
    return CACHE_PATH / "thumbs" / p.parent / (p.stem + ".jpg")


def is_cache_fresh(src_full: Path, cache_full: Path) -> bool:
    """缓存存在且不旧于源文件，则视为新鲜，可跳过生成。"""
    try:
        if not cache_full.exists():
            return False
        return cache_full.stat().st_mtime >= src_full.stat().st_mtime
    except OSError:
        return False


def generate_image_thumb(src_full: Path, dest_full: Path) -> bool:
    """Pillow 生成图片缩略图，成功返回 True。"""
    try:
        from PIL import Image

        with Image.open(src_full) as img:
            img = img.convert("RGB")  # 统一处理 PNG 透明 / GIF 等
            img.thumbnail((THUMB_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS)
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest_full, "JPEG", quality=80)
        return True
    except Exception:
        return False


def generate_video_cover(video_full: Path, dest_full: Path) -> bool:
    """ffmpeg 抽取首帧作为视频封面，成功返回 True。"""
    if dest_full.exists():
        return True
    dest_full.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-ss", VIDEO_FRAME_TIME,
        "-i", str(video_full),
        "-vframes", "1",
        "-vf", f"scale={THUMB_WIDTH}:-1",
        "-q:v", "9",
        "-y",
        str(dest_full),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15)
        return dest_full.exists()
    except Exception:
        return False


# 缩略图生成的 per-file 锁，防止同一文件被并发请求重复生成
_locks_guard = threading.Lock()
_locks: dict = {}


def _get_lock(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def ensure_thumb(src_full: Path, rel_path: str):
    """按文件类型生成缩略图/封面，返回缓存路径；生成失败返回 None。"""
    suf = src_full.suffix.lower()
    dest = get_thumb_cache_path(rel_path)
    if is_cache_fresh(src_full, dest):
        return dest
    # double-checked locking：同一文件并发请求时串行化，避免重复生成
    lock = _get_lock(str(dest))
    with lock:
        if is_cache_fresh(src_full, dest):
            return dest
        if suf in IMAGE_EXT:
            ok = generate_image_thumb(src_full, dest)
        elif suf in VIDEO_EXT:
            ok = generate_video_cover(src_full, dest)
        else:
            return None
    return dest if ok else None
