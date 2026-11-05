"""缩略图 / 视频封面生成模块。

图片：Pillow 等比缩放到指定宽度，存为 JPEG。
视频：ffmpeg 截取首帧，等比缩放，存为 JPEG。
所有缓存写入 CACHE_PATH/thumbs/ 下，保持原目录结构，按源文件 mtime 判断是否过期。
"""
import os
import json
import errno
import re
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .config import CACHE_PATH, CONFIG_PATH

# 缩略图宽度（卡片 270px 的 2 倍，retina 屏足够清晰）
THUMB_WIDTH = 540
# 缩略图最大高度，避免超长图把卡片拉得过高
THUMB_MAX_HEIGHT = 4000

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi"}
MEDIA_EXTS = IMAGE_EXT | VIDEO_EXT  # 预计算并集，避免循环内重复构造


def is_cover_file(name: str) -> bool:
    """判断文件名是否为文件夹封面（cover），文件名大小写、图片扩展名均不敏感。

    cover.jpg / Cover.JPG / cover.jpeg / COVER.webp 均视为封面，不会作为独立图片展示。
    """
    p = Path(name)
    return p.stem.lower() == "cover" and p.suffix.lower() in IMAGE_EXT


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


def generate_image_thumb(src_full: Path, dest_full: Path) -> tuple:
    """Pillow 生成图片缩略图，返回 (成功与否, 错误信息)。"""
    try:
        from PIL import Image, ImageFile

        # 容错：允许加载「截断」的图片（文件尾部缺失），尽量生成缩略图
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        with Image.open(src_full) as img:
            img = img.convert("RGB")  # 统一处理 PNG 透明 / GIF 等
            img.thumbnail((THUMB_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS)
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest_full, "JPEG", quality=80)
        return True, ""
    except Exception as exc:
        return False, f"Pillow: {exc}"


def generate_video_cover(video_full: Path, dest_full: Path) -> tuple:
    """ffmpeg 抽取首帧作为视频封面，返回 (成功与否, 错误信息)。"""
    dest_full.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-i", str(video_full),
        "-vframes", "1",
        "-vf", f"scale={THUMB_WIDTH}:-1",
        "-q:v", "9",
        "-y",
        str(dest_full),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if dest_full.exists():
            return True, ""
        # 抽帧失败：错误信息在 stderr 末尾（头部是版本/版权声明），取末尾 300 字符
        err = result.stderr.decode("utf-8", errors="ignore").strip()
        return False, f"ffmpeg: {err[-300:]}"
    except Exception as exc:
        return False, f"ffmpeg: {exc}"


# 条带锁：固定 64 把锁按 key 取模复用，避免为每个文件常驻一把锁导致内存无限增长
_LOCK_STRIPES = 64
_locks = tuple(threading.Lock() for _ in range(_LOCK_STRIPES))
# 限制缩略图并发生成数，避免浏览器一次请求几十张图时把 NAS CPU/IO 打满
_GEN_SLOTS = 4
_gen_semaphore = threading.BoundedSemaphore(_GEN_SLOTS)


def _get_lock(key: str) -> threading.Lock:
    return _locks[hash(key) % _LOCK_STRIPES]


def ensure_thumb(src_full: Path, rel_path: str, err_out: dict = None):
    """按文件类型生成缩略图/封面，返回缓存路径；生成失败返回 None。

    err_out 可选：传入 dict，失败时写入 {"error": 错误信息}，供调用方记录失败原因。
    """
    suf = src_full.suffix.lower()
    dest = get_thumb_cache_path(rel_path)
    if is_cache_fresh(src_full, dest):
        return dest
    # double-checked locking：同一文件并发请求时串行化，避免重复生成
    lock = _get_lock(str(dest))
    with lock:
        if is_cache_fresh(src_full, dest):
            return dest
        with _gen_semaphore:
            if suf in IMAGE_EXT:
                ok, err = generate_image_thumb(src_full, dest)
            elif suf in VIDEO_EXT:
                ok, err = generate_video_cover(src_full, dest)
            else:
                return None
    if not ok and err_out is not None:
        err_out["error"] = err
    return dest if ok else None


def _collect_media_stems(parent: Path):
    """收集目录内所有媒体文件的 stem（大小写不敏感）。

    返回 (stems, trustworthy)。trustworthy=False 表示目录存在但读取失败
    （无权限 / I/O 故障 / NAS 挂载异常），调用方必须跳过该目录，不能把
    空集合当成「原图已删除」而误删缓存。
    """
    stems = set()
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                name = Path(entry.name)
                if name.suffix.lower() in MEDIA_EXTS:
                    stems.add(name.stem.lower())
    except OSError as exc:
        # 目录确实不存在或不再是目录：可安全按「原图已删除」处理
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return stems, True
        # 其它错误无法判定，跳过不删（保守优先）
        return stems, False
    return stems, True


def _media_mount_ready(media_root: Path, mountinfo_path: str = "/proc/self/mountinfo") -> bool:
    """判断媒体根是否确实挂载生效，用于区分「媒体库真清空」与「挂载未就绪」。

    Linux 容器里 /proc/self/mountinfo 第 5 列是挂载点；同时匹配媒体根
    及其祖先目录（不含 /），兼容 MEDIA_ROOT 配到子目录的情况。
    非 Linux 或读不到信息时返回 False，保持保守跳过。
    """
    try:
        # 同时保留原始路径与符号链接解析后的路径（/tmp、软链接挂载都适用）
        targets = {str(media_root), str(media_root.resolve())}
    except OSError:
        return False
    candidates = set()
    for target in targets:
        cur = Path(target)
        while cur != cur.parent:
            candidates.add(str(cur))
            cur = cur.parent
    try:
        with open(mountinfo_path, "r", encoding="utf-8") as f:
            for line in f:
                head = line.split(" - ", 1)[0].split()
                if len(head) < 5:
                    continue
                mount_point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), head[4])
                if mount_point.rstrip("/") in candidates:
                    return True
    except OSError:
        return False
    return False


def cleanup_orphan_thumbs(media_root: Path) -> int:
    """删除原图已不存在的孤儿缩略图缓存，返回删除数量。

    按目录缓存原图 stem 集合：同一目录只 scandir 一次，避免每个缓存文件
    都遍历整个目录（原实现 O(n^2)，媒体库大时缓存任务会卡很久）。
    媒体根不可读、或为空且未检测到有效挂载时整体跳过，绝不误删。
    """
    thumbs_root = CACHE_PATH / "thumbs"
    if not thumbs_root.exists():
        return 0

    # 挂载掉线时 /media 往往仍是个可访问的空目录。空根时看挂载点是否
    # 真的生效：生效 = 媒体库确实清空，可按目录清理；未生效 = 跳过不删。
    # 只取第一个条目判断，开销 O(1)。
    try:
        with os.scandir(media_root) as root_it:
            root_empty = next(root_it, None) is None
    except OSError:
        print("[CACHE] 媒体根目录不可读，跳过孤儿缓存清理")
        return 0
    if root_empty:
        if not _media_mount_ready(media_root):
            print("[CACHE] 媒体根为空且未检测到有效挂载，跳过孤儿缓存清理")
            return 0
        print("[CACHE] 媒体根为空但挂载正常，按目录判定清理孤儿缓存")

    stem_cache: dict = {}
    removed = 0
    skipped_dirs = set()
    for cache_file in thumbs_root.rglob("*.jpg"):
        rel = cache_file.relative_to(thumbs_root)
        stem_path = media_root / rel.with_suffix("")
        parent_key = str(stem_path.parent)
        cached = stem_cache.get(parent_key)
        if cached is None:
            cached = _collect_media_stems(stem_path.parent)
            stem_cache[parent_key] = cached
        stems, trustworthy = cached
        if not trustworthy:
            skipped_dirs.add(parent_key)
            continue
        if stem_path.name.lower() not in stems:
            try:
                cache_file.unlink()
                removed += 1
            except OSError:
                pass
    if skipped_dirs:
        print(f"[CACHE] {len(skipped_dirs)} 个原目录读取失败，已跳过其缓存不做删除")
    return removed


# 视频时长缓存：进程内字典 + 落盘快照，避免容器重启后时长角标全部丢失
_DURATION_FILE = CONFIG_PATH / "durations.json"
_DURATION_MAX = 50000
_duration_cache: dict = {}
_duration_lock = threading.Lock()
_duration_dirty = False


def load_duration_cache():
    """启动时载入上次持久化的视频时长快照。"""
    try:
        if _DURATION_FILE.exists():
            data = json.loads(_DURATION_FILE.read_text(encoding="utf-8"))
            with _duration_lock:
                _duration_cache.update(data)
    except Exception:
        pass


def save_duration_cache():
    """缓存任务结束后一次性落盘，避免每次探测都写文件。"""
    global _duration_dirty
    with _duration_lock:
        if not _duration_dirty:
            return
        snapshot = dict(_duration_cache)
        if len(snapshot) > _DURATION_MAX:
            snapshot = dict(list(snapshot.items())[-_DURATION_MAX:])
            _duration_cache.clear()
            _duration_cache.update(snapshot)
        _duration_dirty = False
    try:
        _DURATION_FILE.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_video_duration(video_path: str, fetch: bool = False) -> Optional[float]:
    """获取视频时长（秒）。fetch=False 只读缓存，缺失返回 None，不阻塞。"""
    global _duration_dirty
    with _duration_lock:
        if video_path in _duration_cache:
            return _duration_cache[video_path]
    if not fetch:
        return None
    dur = _probe_video_duration(video_path)
    with _duration_lock:
        if video_path not in _duration_cache:
            # 探测失败也记入缓存（值为 None），避免损坏文件每次任务都重复 ffprobe
            _duration_cache[video_path] = dur
            _duration_dirty = True
    return dur


def _probe_video_duration(video_path: str) -> Optional[float]:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", video_path,
        ]
        out = subprocess.run(cmd, capture_output=True, timeout=10).stdout.decode().strip()
        if out:
            return float(out)
    except Exception:
        pass
    return None
