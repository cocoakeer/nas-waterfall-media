"""缩略图 / 视频封面生成模块。

图片：Pillow 等比缩放到指定宽度，存为 JPEG。
视频：ffmpeg 截取首帧，等比缩放，存为 JPEG。
所有缓存写入 CACHE_PATH/thumbs/ 下，保持原目录结构，按源文件 mtime 判断是否过期。
"""
import os
import json
import errno
import re
import time
import subprocess
import threading
from collections import OrderedDict
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
# Emby 本地图片可用的扩展名（.tbn 是 JPEG 数据，但不加入 IMAGE_EXT，避免作为普通照片展示）
ARTWORK_IMAGE_EXTS = IMAGE_EXT | {".tbn"}

# Emby 刮削生成的目录级图片名
ARTWORK_DIR_NAMES = {
    "poster", "folder", "cover", "default", "movie", "thumb", "landscape",
    "backdrop", "fanart", "background", "art", "banner", "logo", "clearlogo",
    "clearart", "disc", "cdart", "show", "season",
}
# {name}-poster / {name}-thumb 这类按视频名派生的图片
ARTWORK_SUFFIXES = (
    "-poster", "-cover", "-default", "-movie", "-thumb", "-landscape",
    "-banner", "-logo", "-clearlogo", "-clearart", "-disc", "-cdart",
    "-fanart", "-backdrop", "-background", "-art",
)


def is_cover_file(name: str, parent: Path = None, video_stems: set = None) -> bool:
    """判断是否为封面/剧照类元数据图片（含 Emby 命名），不参与列表展示与计数。

    兼容原有 cover.*，并扩展 poster.* / folder.* / xxx-poster.* / xxx-thumb.* 等。
    传入 parent（所在目录）时，若同目录存在同名视频，这张图片也视为视频缩图：
    用户库里这类同名图基本都是本地视频封面。不传 parent 时保持旧行为。
    video_stems 可由调用方预先算好传入，避免一次批量扫描里重复 scandir。
    """
    p = Path(name)
    if p.suffix.lower() not in ARTWORK_IMAGE_EXTS:
        return False
    stem = p.stem.lower()
    if stem in ARTWORK_DIR_NAMES:
        return True
    if any(stem.endswith(sfx) for sfx in ARTWORK_SUFFIXES):
        return True
    # backdrop1 / fanart-2 / art_3 等编号背景图
    if re.match(r"^(?:backdrop|fanart|background|art)[-_]?\d+$", stem) is not None:
        return True
    if parent is not None:
        stems = video_stems if video_stems is not None else _video_stems_in(Path(parent))
        if stem in stems:
            return True
    return False


def artwork_rank(name: str, video_stems: set = None) -> int:
    """文件夹封面选择优先级：数字越小越优先。

    原来是 scandir 顺序里最后一个 cover 文件胜出，结果随文件系统顺序漂移；
    这里固定为「目录级 poster/folder > 影片海报 > 通用 cover > 横版剧照 > 背景图」。
    """
    stem = Path(name).stem.lower()
    if stem in ("folder", "poster"):
        return 0
    if stem.endswith(("-poster", "-cover", "-default", "-movie")):
        return 1
    if video_stems is not None and stem in video_stems:
        return 2  # 与视频同名的本地缩图
    if stem in ("cover", "default", "movie"):
        return 3
    if stem.endswith(("-thumb", "-landscape")) or stem in ("thumb", "landscape"):
        return 4
    return 5


def get_thumb_cache_path(rel_path: str) -> Path:
    """缩略图缓存绝对路径：保留源文件完整文件名再加 .jpg。

    只按 stem 命名会让同目录的 a.jpg 和 a.mp4 撞到同一个缓存文件：
    谁后生成谁赢，另一边反复判定过期并重建，还可能把视频封面显示成图片。
    """
    p = Path(rel_path)
    return CACHE_PATH / "thumbs" / p.parent / (p.name + ".jpg")


def _freshness_mtime(src: Path) -> float:
    """缩略图的新鲜度基准时间。

    图片用自己的 mtime。视频优先看本地海报：换海报要重建。
    海报被**删掉**时不能只回退到视频 mtime——视频 mtime 通常很旧，会让
    「用已删除海报生成的旧缩略图」永远判定新鲜。所以无海报时取「视频 mtime
    与所在目录 mtime 中较新的那个」，目录有变动就重建。
    """
    if src.suffix.lower() not in VIDEO_EXT:
        return src.stat().st_mtime
    artwork = find_local_artwork(src)
    if artwork is not None:
        try:
            return artwork.stat().st_mtime
        except OSError:
            pass
    dir_mtime = 0.0
    try:
        dir_mtime = src.parent.stat().st_mtime
    except OSError:
        pass
    try:
        return max(src.stat().st_mtime, dir_mtime)
    except OSError:
        return dir_mtime


def is_cache_fresh(src_full: Path, cache_full: Path) -> bool:
    """缓存存在且 mtime 不旧于新鲜度基准（见 _freshness_mtime）即可跳过生成。"""
    try:
        if not cache_full.exists():
            return False
        return cache_full.stat().st_mtime >= _freshness_mtime(src_full)
    except OSError:
        return False


def _part_path(dest: Path) -> Path:
    """缩略图的临时文件名：保持 .jpg 后缀让 Pillow/ffmpeg 能推断格式。

    孤儿清理识别 .part.jpg：停放不足 1 小时的视为正在写、跳过；
    超过 1 小时的才当残留清掉，所以半截文件不会永久堆积。
    """
    return dest.with_name(f"{dest.stem}.part{dest.suffix}")


def generate_image_thumb(src_full: Path, dest_full: Path) -> tuple:
    """Pillow 生成图片缩略图，返回 (成功与否, 错误信息)。"""
    tmp = _part_path(dest_full)
    try:
        from PIL import Image, ImageFile

        # 容错：允许加载「截断」的图片（文件尾部缺失），尽量生成缩略图
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        with Image.open(src_full) as img:
            img = img.convert("RGB")  # 统一处理 PNG 透明 / GIF 等
            img.thumbnail((THUMB_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS)
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子换名：直接写目标文件时若进程被杀会留下半截 JPEG，
            # 而它的 mtime 已经是新的，is_cache_fresh 会永远认为它新鲜，再也不重建
            img.save(tmp, "JPEG", quality=80)
        os.replace(tmp, dest_full)
        return True, ""
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"Pillow: {exc}"


# Emby 本地封面的目录索引与查找结果缓存（避免每个视频都重复 scandir / 读图片头）
_artwork_index_cache: OrderedDict = OrderedDict()
_artwork_result_cache: OrderedDict = OrderedDict()
_video_stems_cache: OrderedDict = OrderedDict()
_artwork_lock = threading.Lock()
# 超限时只淘汰最旧的四分之一；原来整体 clear 会让大媒体库的缓存任务反复重扫同一批目录
_INDEX_CACHE_MAX = 4096
_RESULT_CACHE_MAX = 20000


def _cache_put(cache: OrderedDict, key, value, max_size: int):
    """LRU 写入：命中移到末尾，超限淘汰最旧的一批（而非全清）。"""
    with _artwork_lock:
        if key in cache:
            cache.move_to_end(key)
        cache[key] = value
        if len(cache) > max_size:
            for _ in range(max(1, max_size // 4)):
                cache.popitem(last=False)
    return value


def _video_stems_in(parent: Path) -> set:
    """按 (目录, 目录 mtime) 缓存同目录所有视频的 stem 集合，大小其一不敏感。"""
    try:
        dir_mtime = parent.stat().st_mtime
    except OSError:
        return set()
    key = (str(parent), dir_mtime)
    with _artwork_lock:
        cached = _video_stems_cache.get(key)
    if cached is not None:
        return cached
    stems = set()
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                if Path(entry.name).suffix.lower() in VIDEO_EXT:
                    stems.add(Path(entry.name).stem.lower())
    except OSError:
        return set()
    return _cache_put(_video_stems_cache, key, stems, _INDEX_CACHE_MAX)


def _index_local_images(parent: Path) -> dict:
    """按 (目录, 目录 mtime) 缓存同目录所有图片：{stem.lower(): 绝对路径}。"""
    try:
        dir_mtime = parent.stat().st_mtime
    except OSError:
        return {}
    key = (str(parent), dir_mtime)
    with _artwork_lock:
        cached = _artwork_index_cache.get(key)
    if cached is not None:
        return cached
    index = {}
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                p = Path(entry.name)
                if p.suffix.lower() in ARTWORK_IMAGE_EXTS:
                    index.setdefault(p.stem.lower(), parent / entry.name)
    except OSError:
        return {}
    return _cache_put(_artwork_index_cache, key, index, _INDEX_CACHE_MAX)


def find_local_artwork(video_full: Path):
    """按 Emby 规则找视频的本地封面：优先竖版海报，没有竖版则取横版。

    候选按 Emby Primary 顺序排列，先扫一遍读图片头判断宽高比；
    找到第一张竖版（高 > 宽 × 1.05）就用它，否则用优先级最高的横版。
    """
    parent = video_full.parent
    index = _index_local_images(parent)
    if not index:
        return None
    try:
        dir_mtime = parent.stat().st_mtime
    except OSError:
        dir_mtime = 0
    cache_key = (str(video_full), dir_mtime)
    with _artwork_lock:
        if cache_key in _artwork_result_cache:
            return _artwork_result_cache[cache_key]

    stem = video_full.stem
    poster_names = [
        f"{stem}-poster", f"{stem}-cover", f"{stem}-default", f"{stem}-movie",
        stem,
        "poster", "folder", "cover", "default", "movie",
    ]
    thumb_names = [f"{stem}-thumb", f"{stem}-landscape", "thumb", "landscape"]
    from PIL import Image
    measured = []
    for name, group in ([(n, "poster") for n in poster_names] +
                        [(n, "thumb") for n in thumb_names]):
        path = index.get(name.lower())
        if path is None:
            continue
        try:
            with Image.open(path) as im:
                measured.append((path, im.width, im.height, group))
        except Exception:
            continue
    chosen = None
    # 1) 所有候选里第一张竖版（海报优先）
    for path, width, height, group in measured:
        if height > width * 1.05:
            chosen = path
            break
    # 2) 没有竖版：优先 Thumb 类横图，再退到其它横版
    if chosen is None:
        for path, width, height, group in measured:
            if group == "thumb":
                chosen = path
                break
        if chosen is None and measured:
            chosen = measured[0][0]

    return _cache_put(_artwork_result_cache, cache_key, chosen, _RESULT_CACHE_MAX)


def generate_video_cover(video_full: Path, dest_full: Path) -> tuple:
    """优先用同目录 Emby 本地封面生成缩略图，没有才回退 ffmpeg 抽首帧。"""
    tmp = _part_path(dest_full)
    try:
        dest_full.parent.mkdir(parents=True, exist_ok=True)
        artwork = find_local_artwork(video_full)
        if artwork is not None:
            ok, err = generate_image_thumb(artwork, dest_full)
            return ok, (f"Pillow(artwork): {err}" if not ok else "")
        cmd = [
            "ffmpeg",
            "-i", str(video_full),
            "-vframes", "1",
            "-vf", f"scale={THUMB_WIDTH}:-1",
            "-q:v", "9",
            "-y",
            str(tmp),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        # 不能只看文件存在：ffmpeg 失败时也会留下 0 字节文件，而它 mtime 是新的，
        # is_cache_fresh 会一直判定新鲜，坏图永不重建
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, dest_full)
            return True, ""
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        # 抽帧失败：错误信息在 stderr 末尾（头部是版本/版权声明），取末尾 300 字符
        err = result.stderr.decode("utf-8", errors="ignore").strip()
        return False, f"ffmpeg: {err[-300:]}"
    except subprocess.TimeoutExpired:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, "ffmpeg: 抽帧超时（15 秒）"
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
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
    # 新鲜度规则只有一处：is_cache_fresh → _freshness_mtime。
    # 图片看自身 mtime；视频有海报看海报、无海报看 max(视频, 目录 mtime)。
    if is_cache_fresh(src_full, dest):
        return dest
    # double-checked locking：同一文件并发请求时串行化，避免重复生成
    lock = _get_lock(str(dest))
    with lock:
        if is_cache_fresh(src_full, dest):
            return dest
        with _gen_semaphore:
            # 单个文件出任何意外都只算这一个失败，不能让整个缓存任务中断
            try:
                if suf in IMAGE_EXT:
                    ok, err = generate_image_thumb(src_full, dest)
                elif suf in VIDEO_EXT:
                    ok, err = generate_video_cover(src_full, dest)
                else:
                    return None
            except Exception as exc:
                ok, err = False, f"未捕获异常：{exc}"
    if not ok and err_out is not None:
        err_out["error"] = err
    return dest if ok else None


def _collect_media_names(parent: Path):
    """收集目录内所有媒体文件名（小写、含扩展名）。

    必须带扩展名：缓存名现在是「源文件名 + .jpg」，a.jpg 与 a.mp4 是两个
    不同条目，只比 stem 会把它们混为一谈。

    返回 (names, trustworthy)。trustworthy=False 表示目录存在但读取失败
    （无权限 / I/O 故障 / NAS 挂载异常），调用方必须跳过该目录，不能把
    空集合当成「原图已删除」而误删缓存。
    """
    names = set()
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                if Path(entry.name).suffix.lower() in MEDIA_EXTS:
                    names.add(entry.name.lower())
    except OSError as exc:
        # 目录确实不存在或不再是目录：可安全按「原图已删除」处理
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return names, True
        # 其它错误无法判定，跳过不删（保守优先）
        return names, False
    return names, True


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

    按目录缓存原图文件名集合：同一目录只 scandir 一次，避免每个缓存文件
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

    name_cache: dict = {}
    removed = 0
    skipped_dirs = set()
    for cache_file in thumbs_root.rglob("*.jpg"):
        rel = cache_file.relative_to(thumbs_root)
        # 缓存名 = 源文件名 + .jpg，去掉最外层后缀正好还原原媒体的文件名
        src_path = media_root / rel.with_suffix("")
        # 生成中的临时文件（a.mp4.part.jpg）：绝不能删——缓存任务清理阶段
        # 和 /api/thumb 的生成可能同时进行，删掉会让 os.replace 失败、缩略图丢失。
        # 只有停放超过一小时、明显是残留的才清掉。
        if src_path.name.lower().endswith(".part"):
            try:
                st = cache_file.stat()
                if time.time() - st.st_mtime < 3600:
                    continue
                # TOCTOU 复核：stat 与 unlink 之间可能正好有新的生成任务
                # 重建了同名 .part，mtime 会变（新文件不可能是 1 小时前的）
                if cache_file.stat().st_mtime != st.st_mtime:
                    continue
                cache_file.unlink()
                removed += 1
            except OSError:
                continue
            continue
        parent_key = str(src_path.parent)
        cached = name_cache.get(parent_key)
        if cached is None:
            cached = _collect_media_names(src_path.parent)
            name_cache[parent_key] = cached
        names, trustworthy = cached
        if not trustworthy:
            skipped_dirs.add(parent_key)
            continue
        if src_path.name.lower() not in names:
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
    tmp = _DURATION_FILE.with_name(_DURATION_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _DURATION_FILE)
    except Exception:
        # 写失败（只读配置卷 / 磁盘满）就保留 dirty，下次任务结束再试，
        # 否则这一批探测结果永远不会再落盘
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return
    with _duration_lock:
        _duration_dirty = False


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
