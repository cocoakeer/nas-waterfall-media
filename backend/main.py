import os
import errno
import json
import bcrypt
import uuid
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from .cover import (
    IMAGE_EXT,
    VIDEO_EXT,
    MEDIA_EXTS,
    is_cover_file,
    artwork_rank,
    ensure_thumb,
    get_thumb_cache_path,
    is_cache_fresh,
    cleanup_orphan_thumbs,
    _media_mount_ready,
    get_video_duration,
    load_duration_cache,
    save_duration_cache,
)
from .config import load_settings, save_settings, CONFIG_PATH

# ========== 配置读取 适配compose CONFIG_PATH / CACHE_PATH ==========
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
REAL_BASE = Path(MEDIA_ROOT).resolve()  # 预计算，避免每个请求重复 resolve
# 目录统一复用 config.py 的定义（它 import 时就已 mkdir）；缓存目录由
# cover.py 直接用 CACHE_PATH，main.py 不需要再留一个没人用的别名
CONFIG_DIR = CONFIG_PATH
USER_CONFIG_PATH = CONFIG_DIR / "users.json"

SESSION_EXPIRE_SEC = 86400
# 各接口的 limit 上限分开命名：逻辑相同但语义不同，避免改一处误伤另一处
LOG_LIMIT_MAX = 1000           # /api/logs 单次最多返回日志条数
RANDOM_IMAGES_LIMIT_MAX = 2000  # /api/random-images 单次最多返回图片数

# 数据模型 新增 is_admin 布尔标记，不再依靠用户名admin
class LoginForm(BaseModel):
    username: str
    password: str

class UserItem(BaseModel):
    username: str
    password_hash: str
    allow_dirs: List[str]
    is_admin: bool

class ChangePwdForm(BaseModel):
    old_password: str
    new_password: str

class SettingsForm(BaseModel):
    # 限制 1~3600 秒，避免 0/负值让前端 setTimeout 空转打满 CPU
    slide_delay: int = Field(5, ge=1, le=3600)
    slide_loop: bool = True

class AdminUserForm(BaseModel):
    username: str
    password: Optional[str] = Field(None, description="新增必填；编辑留空则不修改密码")
    allow_dirs: List[str]
    is_admin: bool

class UserRenameForm(BaseModel):
    old_username: str
    new_username: str


def _valid_password(pw: str) -> bool:
    """bcrypt 只接受 72 字节以内、不含 NUL 的口令，超限会直接抛 ValueError。

    不先挡住的话，超长口令会让登录/改密接口直接 500，而不是给出正常提示。
    """
    if not pw:
        return False
    try:
        raw = pw.encode("utf-8")
    except UnicodeError:
        return False
    return len(raw) <= 72 and b"\x00" not in raw

# 内存会话存储：sid -> (用户名, 过期时间戳)，带过期清理避免长期运行内存无限增长
sessions: Dict[str, tuple] = {}
_session_lock = threading.Lock()


def _purge_expired_sessions():
    now = time.time()
    with _session_lock:
        for sid, (_uname, expire_ts) in list(sessions.items()):
            if expire_ts <= now:
                sessions.pop(sid, None)

_last_good_users: List[UserItem] = []


def _default_users() -> List[UserItem]:
    default_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
    return [UserItem(username="admin", password_hash=default_hash,
                     allow_dirs=["/"], is_admin=True)]


def load_users() -> List[UserItem]:
    """读取用户配置；文件损坏时沿用上次成功加载的结果，避免服务崩溃或密码被重置。"""
    global _last_good_users
    try:
        if not USER_CONFIG_PATH.exists():
            out = _default_users()
            USER_CONFIG_PATH.write_text(
                json.dumps([u.model_dump() for u in out], ensure_ascii=False, indent=2),
                encoding="utf-8")
        else:
            raw_list = json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
            out = []
            # 兼容旧配置文件，旧数据缺少is_admin字段自动补为False，原admin用户名自动升级为管理员
            for item in raw_list:
                if "is_admin" not in item:
                    item["is_admin"] = (item.get("username") == "admin")
                out.append(UserItem(**item))
        _last_good_users = list(out)
        return out
    except Exception as exc:
        # 不覆盖损坏文件，保留现场供人工排查；也不重新生成默认密码
        print(f"[CONFIG] users.json 读取失败（{exc}），沿用上次成功加载的用户配置")
        return list(_last_good_users) if _last_good_users else _default_users()

def save_users(user_list: List[UserItem]):
    data = [u.model_dump() for u in user_list]
    # 原子写：直接写目标文件时若进程被杀，会留下半截 JSON，
    # 下次启动读失败就会回落到默认账号，等于把密码重置成 admin123
    tmp = USER_CONFIG_PATH.with_name(USER_CONFIG_PATH.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, USER_CONFIG_PATH)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

def _check_username(raw: str) -> str:
    """校验并返回规范化的用户名，不合法直接 400。

    用户名既是登录标识，又是 /api/admin/user/{username} 的路径参数，
    所以不能容忍空值、首尾空格、路径分隔符以及 . / ..——
    否则能造出「改不了、也删不掉」的账号。
    """
    name = (raw or "").strip()
    if not name:
        raise HTTPException(400, "用户名不能为空")
    if name != raw:
        raise HTTPException(400, "用户名首尾不能包含空格")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(400, "用户名不能包含 / \\ 或为 . / ..")
    return name


def _check_allow_dirs(dirs: List[str]) -> List[str]:
    """校验允许目录：拒绝含 .. 或解析后越出媒体根的配置。

    只做放行判断是不够的："/photos/2024/../../" 会解析回媒体根，等于把
    受限用户悄悄升级成全库可见；"/foo/../.." 更是直接解析到容器根。
    写接口挡住脏数据，读接口再做边界兜底（_resolved_allow_dirs）。
    """
    cleaned = []
    for raw in dirs or []:
        d = (raw or "").strip()
        if ".." in Path(d).parts:
            raise HTTPException(400, "允许目录不能包含 .. ")
        try:
            (REAL_BASE / d.lstrip("/")).resolve().relative_to(REAL_BASE)
        except (ValueError, OSError):
            raise HTTPException(400, f"允许目录超出媒体库范围：{d}")
        cleaned.append(d)
    return cleaned


# 用户写操作都是「读盘 → 改内存 → 写盘」，必须串行化：
# 否则两个管理员同时保存时，后写者会用旧快照覆盖前者刚保存的修改。
# 用 RLock：写操作持锁期间还会调 reload_users() 重入。
_users_lock = threading.RLock()


def reload_users():
    global users
    with _users_lock:
        users = load_users()

users = load_users()

# ========== 鉴权依赖 ==========
async def get_current_user(request: Request) -> UserItem:
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    with _session_lock:
        entry = sessions.get(session_id)
    if not entry:
        raise HTTPException(status_code=401, detail="Unauthorized")
    uname, expire_ts = entry
    if expire_ts <= time.time():
        with _session_lock:
            sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = next((u for u in users if u.username == uname), None)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

async def require_admin(user: UserItem = Depends(get_current_user)):
    # 不再判断用户名admin，判断is_admin标记
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

# 路径安全校验：防止越权、路径穿越
# 解析后的允许目录缓存（相同 allow_dirs 配置共享，避免每个请求重复 resolve）
_allow_dirs_cache: Dict[tuple, tuple] = {}


def _resolved_allow_dirs(allow_dirs: List[str]):
    key = tuple(sorted(allow_dirs))
    cached = _allow_dirs_cache.get(key)
    if cached is not None:
        return cached
    resolved = []
    for ad in allow_dirs:
        try:
            p = (REAL_BASE / ad.lstrip("/")).resolve()
            # allow_dirs 可能来自手工编辑的 users.json / 旧备份。解析后越出媒体根
            # 的值（例如 "/foo/../.." 解析成 "/"）会让 relative_to 对全库成立，
            # 等于直接放行全库，必须丢掉。
            p.relative_to(REAL_BASE)
        except (ValueError, OSError):
            continue
        resolved.append(p)
    result = tuple(resolved)
    if len(_allow_dirs_cache) < 100:
        _allow_dirs_cache[key] = result
    return result


def check_path_allowed(user: UserItem, target_dir: str) -> Path:
    target_dir = target_dir.strip()
    req_path = (REAL_BASE / target_dir.lstrip("/")).resolve()
    # 文件接口同样守住媒体根边界，防止符号链接 / 路径穿越读到容器其它目录
    try:
        req_path.relative_to(REAL_BASE)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径超出媒体库范围")
    for allow_p in _resolved_allow_dirs(user.allow_dirs):
        try:
            req_path.relative_to(allow_p)
            return req_path
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="无权访问该目录")


def check_dir_allowed(user: UserItem, target_dir: str) -> Path:
    """目录导航校验：允许访问允许目录内部，也允许访问它的祖先路径。

    只用于 /api/list，让受限用户能从媒体根逐级点进自己的目录；
    具体条目还会由 _entry_visible 再过滤一遍。
    文件访问（/api/src、/api/thumb）必须用严格的 check_path_allowed。
    """
    req_path = (REAL_BASE / target_dir.strip().lstrip("/")).resolve()
    # 祖先放宽不能越出媒体根：否则 dir=../../.. 会把容器根目录也放行
    try:
        req_path.relative_to(REAL_BASE)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径超出媒体库范围")
    for allow_p in _resolved_allow_dirs(user.allow_dirs):
        try:
            req_path.relative_to(allow_p)   # 目录在允许范围内
            return req_path
        except ValueError:
            pass
        try:
            allow_p.relative_to(req_path)   # 目录是允许目录的祖先
            return req_path
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="无权访问该目录")


# 获取media根下全部一级子目录（给前端下拉选择）
def scan_media_root_dirs() -> List[str]:
    dir_list = ["/"]
    try:
        for entry in REAL_BASE.iterdir():
            if entry.is_dir():
                rel = "/" + str(entry.relative_to(REAL_BASE)).replace(os.sep, "/")
                dir_list.append(rel)
    except Exception:
        pass
    return dir_list

# 校验：至少保留一个管理员账号，禁止把全部管理员取消
def check_at_least_one_admin(user_list: List[UserItem]):
    admin_count = sum(1 for u in user_list if u.is_admin)
    if admin_count <= 0:
        raise HTTPException(status_code=400, detail="系统至少保留一名管理员账号，不允许全部取消管理员")

# ========== 缓存统计（缓存任务执行后记录快照，持久化到磁盘） ==========
_CACHE_STATS_FILE = CONFIG_DIR / "cache_stats.json"
# 失败明细只保留前这么多条：全库失败时（比如 ffmpeg 没装）明细能到几十 MB，
# 存内存、整份落盘、每次请求全量返回都会把后端和浏览器一起拖死
_FAILED_FILES_MAX = 500
_cache_stats = {
    "total": 0,
    "cached": 0,
    "uncached": 0,
    "failed": 0,
    "failed_files": [],  # 缓存失败的文件相对路径列表（最多 _FAILED_FILES_MAX 条）
    "failed_files_truncated": False,  # 明细是否被截断
    "last_finish_time": None,  # 上次缓存任务完成时间（epoch 秒）
}
_cache_stats_lock = threading.Lock()


def load_cache_stats():
    """启动时从磁盘加载上次的统计快照。"""
    try:
        if _CACHE_STATS_FILE.exists():
            data = json.loads(_CACHE_STATS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                files = data.get("failed_files")
                if not isinstance(files, list):
                    files = []
                # 旧版本没有条数上限，升级后第一次启动可能带着几万条明细回来，
                # 载入时就截断，别等下一次缓存任务跑完才生效
                truncated_now = False
                if len(files) > _FAILED_FILES_MAX:
                    files = files[:_FAILED_FILES_MAX]
                    data["failed_files_truncated"] = True
                    truncated_now = True
                data["failed_files"] = files
                data.setdefault("failed_files_truncated", False)
                with _cache_stats_lock:
                    _cache_stats.update(data)
                # 截断结果写回磁盘，否则每次启动都要重新解析几十 MB 的旧文件，
                # 而且磁盘上的明细与内存长期不一致
                if truncated_now:
                    try:
                        tmp = _CACHE_STATS_FILE.with_name(_CACHE_STATS_FILE.name + ".tmp")
                        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        os.replace(tmp, _CACHE_STATS_FILE)
                    except Exception:
                        pass
    except Exception:
        pass


def record_cache_stats(total: int, cached: int, failed: int = 0, failed_files: list = None):
    """缓存任务完成后记录统计快照（内存 + 磁盘持久化）。"""
    files = failed_files or []
    snapshot = {
        "total": total,
        "cached": cached,
        "uncached": total - cached,
        "failed": failed,
        "failed_files": files[:_FAILED_FILES_MAX],
        "failed_files_truncated": len(files) > _FAILED_FILES_MAX,
        "last_finish_time": time.time(),
    }
    with _cache_stats_lock:
        _cache_stats.update(snapshot)
    tmp = _CACHE_STATS_FILE.with_name(_CACHE_STATS_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _CACHE_STATS_FILE)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


load_cache_stats()  # 启动时加载上次快照


# ========== 执行日志（JSONL 追加存储） ==========
_LOG_FILE = CONFIG_DIR / "logs.jsonl"
_log_lock = threading.Lock()
_LOG_MAX_LINES = 2000  # 最多保留的日志条数
_log_line_count = 0  # 内存行数：避免每次写日志都全量读文件


def _init_log_count():
    """启动时只统计一次现有日志行数。"""
    global _log_line_count
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            _log_line_count = sum(1 for _ in f)
    except OSError:
        _log_line_count = 0


def add_log(operator: str, action: str, detail: str = ""):
    """追加一条执行日志；仅在超过上限时裁剪，追加与裁剪同锁保护。"""
    global _log_line_count
    entry = {
        "id": uuid.uuid4().hex[:8],
        "time": time.time(),
        "operator": operator,
        "action": action,
        "detail": detail,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _log_lock:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            _log_line_count += 1
        except Exception:
            return
        if _log_line_count > _LOG_MAX_LINES:
            try:
                with open(_LOG_FILE, "r", encoding="utf-8") as f:
                    lines = deque(f, maxlen=_LOG_MAX_LINES)
                with open(_LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                _log_line_count = len(lines)
            except Exception:
                pass


def read_logs(limit: int = 200) -> List[dict]:
    """读取最近 limit 条日志（最新在前），流式读尾部，内存占用 O(limit)。"""
    if not _LOG_FILE.exists():
        return []
    try:
        with _log_lock:
            with open(_LOG_FILE, "r", encoding="utf-8") as f:
                lines = list(deque(f, maxlen=limit))
        entries = []
        for line in reversed(lines):
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries
    except Exception:
        return []


_init_log_count()


# ========== 预生成缓存任务（后台线程） ==========
class CacheTask:
    def __init__(self, media_root: str):
        self._media_root = media_root
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.running = False
        self.percent = 0
        self.message = ""
        self.processed = 0
        self.succeeded = 0  # 本次实际成功生成的缓存数
        self.failed = 0  # 本次生成失败的数量
        self.total = 0
        self.current = ""
        self.operator = "system"  # 触发者（system=定时任务，否则为用户名）

    def snapshot(self):
        with self._lock:
            return {
                "running": self.running,
                "percent": self.percent,
                "message": self.message,
                "processed": self.processed,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "total": self.total,
                "current": self.current,
            }

    def _set(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def start(self, operator: str = "system") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.operator = operator
            self.percent = 0
            self.message = ""
            self.processed = 0
            self.succeeded = 0
            self.failed = 0
            self.total = 0
            self.current = ""
            self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        try:
            self._thread.start()
        except Exception as exc:
            # 线程起不来（线程数/内存耗尽）必须把状态退回去，否则界面永远显示运行中，
            # 后续 cache-run 也永远返回「已有任务在运行」，只能重启进程
            with self._lock:
                self.running = False
            print(f"[CACHE] 缓存任务启动失败：{exc}")
            return False
        return True

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            self._build()
        except Exception as exc:
            self._set(message=f"任务异常：{exc}")
        finally:
            try:
                save_duration_cache()
            except Exception:
                pass
            # 缓存任务可能改动媒体库：标记索引待后台重建，不阻塞用户点击
            _mark_images_index_dirty()
            invalidate_folder_stats()
            self._set(running=False)
            # 不在这里 _stop.clear()：start() 已经清过了。旧任务收尾时清一次，
            # 会把「刚启动的新任务」收到的停止请求吞掉。

    def _build(self):
        base = Path(self._media_root).resolve()
        # 0. 清理孤儿缓存（原图已删除的缩略图），手动/定时任务都会执行
        cleaned = 0
        try:
            cleaned = cleanup_orphan_thumbs(base)
        except Exception:
            pass
        # 1. 遍历收集：统计全部媒体文件 + 需要处理的（增量跳过新鲜的）
        all_total = 0
        cached_count = 0
        files = []
        for root, _dirs, names in os.walk(base):
            if self._stop.is_set():
                break
            # 每个目录算一次同名视频集合，避免 is_cover_file 对每个文件 stat 父目录
            video_stems = {
                Path(n).stem.lower()
                for n in names if Path(n).suffix.lower() in VIDEO_EXT
            }
            for name in names:
                if self._stop.is_set():
                    break
                if Path(name).suffix.lower() not in MEDIA_EXTS:
                    continue
                if is_cover_file(name, Path(root), video_stems):
                    continue  # 封面/元数据图不预生成缓存、不参与统计与失败计数
                full = Path(root) / name
                try:
                    rel = full.relative_to(base)
                except ValueError:
                    continue
                all_total += 1
                # 视频时长缓存补齐：仅在缓存缺失时才 ffprobe，任务结束统一落盘
                if full.suffix.lower() in VIDEO_EXT:
                    get_video_duration(str(full), fetch=True)
                # 新鲜度判断内部已区分：视频看本地海报，海报被删则看目录 mtime
                if is_cache_fresh(full, get_thumb_cache_path(str(rel))):
                    cached_count += 1
                    continue
                files.append((full, str(rel)))
        if self._stop.is_set():
            # 收集阶段就被取消：这时 all_total/cached_count 只是扫到的那一部分，
            # 既不能当成「缓存已是最新」，也不能落成全库统计快照
            msg = f"已取消，扫描到 {all_total} 个媒体文件，尚未开始生成缓存"
            self._set(message=msg, percent=0, succeeded=0, failed=0)
            add_log(self.operator, "cache_result", msg)
            return
        total = len(files)
        self._set(total=total)
        if total == 0:
            m = "缓存已是最新，无增量文件"
            if cleaned:
                m += f"，清理孤儿缓存 {cleaned} 个"
            self._set(percent=100, message=m, failed=0)
            record_cache_stats(all_total, cached_count, failed=0)
            add_log(self.operator, "cache_result", m)
            return
        # 2. 逐个生成缩略图/封面
        processed = 0
        failed = 0
        failed_files = []  # 记录缓存失败的文件路径
        for full, rel in files:
            if self._stop.is_set():
                succeeded = processed - failed
                uncached = all_total - cached_count - succeeded
                msg = f"已取消，本次实际缓存 {succeeded} 个，失败 {failed} 个，剩余未缓存 {uncached} 个"
                if cleaned:
                    msg += f"，清理孤儿缓存 {cleaned} 个"
                self._set(message=msg, percent=int(processed * 100 / total), succeeded=succeeded, failed=failed)
                record_cache_stats(all_total, cached_count + succeeded, failed=failed, failed_files=failed_files)
                add_log(self.operator, "cache_result", msg)
                return
            err_out = {}
            result = ensure_thumb(full, rel, err_out)
            if result is None:
                failed += 1
                failed_files.append({"path": str(rel), "error": err_out.get("error", "未知错误")})
            processed += 1
            self._set(processed=processed, percent=int(processed * 100 / total), current=rel)
        succeeded = processed - failed
        uncached = all_total - cached_count - succeeded
        msg = f"本次实际缓存 {succeeded} 个，失败 {failed} 个，剩余未缓存 {uncached} 个"
        if cleaned:
            msg += f"，清理孤儿缓存 {cleaned} 个"
        self._set(percent=100, message=msg, succeeded=succeeded, failed=failed)
        record_cache_stats(all_total, cached_count + succeeded, failed=failed, failed_files=failed_files)
        add_log(self.operator, "cache_result", msg)


# ========== 缓存任务实例 ==========
cache_task = CacheTask(MEDIA_ROOT)


# ========== 每日缓存任务 ==========
def daily_cache_job():
    """每天凌晨 3 点：触发缓存任务（内部会清理孤儿缓存 + 增量生成）。"""
    if cache_task.start(operator="system"):
        add_log("system", "cache_daily", "定时任务触发缓存任务")
        print("[CACHE-JOB] 缓存任务已启动")
    else:
        print("[CACHE-JOB] 已有任务在运行，跳过")


# ========== APP初始化 ==========
@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_duration_cache()
    load_images_index()
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(daily_cache_job, "cron", hour=3, minute=0, id="daily_cache")
    scheduler.start()
    print("[SCHEDULER] 缓存增量任务已调度：每天 03:00（Asia/Shanghai）")
    _folder_watcher_stop.clear()
    threading.Thread(target=_folder_watcher_loop, daemon=True, name="folder-watcher").start()
    print(f"[FOLDER] 目录变化后台校验已启动：每 {_FOLDER_STATS_CHECK_SEC} 秒")
    _images_index_stop.clear()
    threading.Thread(target=_images_index_loop, daemon=True, name="images-index").start()
    print(f"[IMAGES] 图片索引后台维护已启动"
          f"（目录变化增量合并，兜底全量 {_IMAGES_INDEX_MAX_AGE}s）")
    yield
    _images_index_stop.set()
    _folder_watcher_stop.set()
    _folder_watcher_wake.set()  # 立刻打断 wait，别让退出等满一个周期
    # 丢弃排队中的任务；已在跑的生成任务由解释器退出钩子 join，
    # wait=False 只省掉 shutdown 自身的等待，仍可能等最慢的一个 ffmpeg
    _thumb_pool.shutdown(wait=False, cancel_futures=True)
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
# 容器里是 Dockerfile COPY 出来的 /frontend/dist；本地开发回退到项目内
# frontend/dist，否则注释里那句 `python -m backend.main` 根本起不来。
_FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "/frontend/dist"))
if not _FRONTEND_DIST.is_dir():
    _FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets"), check_dir=False), name="assets")

# ========== 登录登出接口 ==========
@app.post("/api/login")
def login(form: LoginForm, resp: Response):
    reload_users()
    user = next((u for u in users if u.username == form.username), None)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if not _valid_password(form.password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if not bcrypt.checkpw(form.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    _purge_expired_sessions()
    sid = str(uuid.uuid4())
    with _session_lock:
        sessions[sid] = (user.username, time.time() + SESSION_EXPIRE_SEC)
    resp.set_cookie(key="session_id", value=sid, max_age=SESSION_EXPIRE_SEC, httponly=True)
    add_log(user.username, "login", "登录系统")
    return {"code": 0, "msg": "ok"}

@app.post("/api/logout")
async def logout(resp: Response, user: UserItem = Depends(get_current_user)):
    with _session_lock:
        to_del = [k for k, (uname, _exp) in list(sessions.items()) if uname == user.username]
        for k in to_del:
            sessions.pop(k, None)
    resp.delete_cookie("session_id")
    add_log(user.username, "logout", "退出登录")
    return {"code":0}

@app.get("/api/whoami")
async def whoami(user: UserItem = Depends(get_current_user)):
    return {
        "code":0,
        "username": user.username,
        "is_admin": user.is_admin,
        "allow_dirs": user.allow_dirs
    }

# ========== 用户账号管理接口 ==========
## 修改本人密码
@app.post("/api/user/change-password")
def api_change_my_pwd(form: ChangePwdForm, user: UserItem = Depends(get_current_user)):
    with _users_lock:
        reload_users()
        u = next((x for x in users if x.username == user.username), None)
        if not u:
            raise HTTPException(404, "用户不存在")
        if not _valid_password(form.old_password):
            raise HTTPException(400, "原密码错误")
        if not bcrypt.checkpw(form.old_password.encode(), u.password_hash.encode()):
            raise HTTPException(400, "原密码错误")
        if not _valid_password(form.new_password):
            raise HTTPException(400, "新密码需为 1~72 字节，且不能包含空字符")
        u.password_hash = bcrypt.hashpw(form.new_password.encode(), bcrypt.gensalt()).decode()
        try:
            save_users(users)
        except Exception as exc:
            # 落盘失败就回滚内存，否则会出现「内存已改、磁盘没改」，重启后又变回去
            reload_users()
            raise HTTPException(500, f"保存失败：{exc}")
    add_log(user.username, "change_password", "修改本人密码")
    return {"code":0, "msg":"密码修改成功"}

## 管理员获取全部用户
@app.get("/api/admin/users")
def admin_get_all_users(_admin: UserItem = Depends(require_admin)):
    reload_users()
    out = []
    for u in users:
        out.append({
            "username": u.username,
            "allow_dirs": u.allow_dirs,
            "is_admin": u.is_admin
        })
    return {"code":0, "list": out}

## 获取媒体库目录下拉选项
@app.get("/api/admin/dirs")
def admin_get_dir_options(_admin: UserItem = Depends(require_admin)):
    # scan_media_root_dirs 要对媒体根做 iterdir + is_dir，NAS 上可能慢，放线程池
    dir_options = scan_media_root_dirs()
    return {"code":0, "options": dir_options}

## 管理员重命名用户名
@app.post("/api/admin/user-rename")
def admin_rename_user(form: UserRenameForm, _admin: UserItem = Depends(require_admin)):
    """同步端点：内部持 _users_lock，不能用 async 在事件循环里阻塞等锁。"""
    with _users_lock:
        reload_users()
        old = form.old_username.strip()
        if not old:
            raise HTTPException(400, "用户名不能为空")
        # 旧名只做 strip（可能是历史脏数据），新名必须完全合规
        new = _check_username(form.new_username)
        if old == new:
            return {"code":0, "msg":"未变更"}
        if next((u for u in users if u.username == new), None) is not None:
            raise HTTPException(400, "新用户名已存在")
        u_target = next((u for u in users if u.username == old), None)
        if u_target is None:
            raise HTTPException(404, "原用户不存在")
        u_target.username = new
        try:
            save_users(users)
        except Exception as exc:
            reload_users()
            raise HTTPException(500, f"保存失败：{exc}")
        # 落盘成功之后再改会话映射：写盘失败时磁盘和内存都是旧名，
        # 若先把 session 改成新名，get_current_user 会找不到用户，把人踢下线
        with _session_lock:
            for sid, (uname, expire_ts) in list(sessions.items()):
                if uname == old:
                    sessions[sid] = (new, expire_ts)
    add_log(_admin.username, "user_rename", f"重命名用户 {old} → {new}")
    return {"code":0, "msg":"用户名修改成功"}

## 管理员新增/编辑用户（支持设置is_admin管理员标记）
@app.post("/api/admin/user-save")
def admin_save_user(form: AdminUserForm, _admin: UserItem = Depends(require_admin)):
    with _users_lock:
        reload_users()
        # 用户名要做成「可登录、可作路径参数」的标识，空值/首尾空格/路径字符都不行
        name = _check_username(form.username)
        allow_dirs = _check_allow_dirs(form.allow_dirs)
        # bcrypt 对超 72 字节或含 NUL 的口令会抛 ValueError，不先挡住接口就变成 500
        if form.password is not None and form.password.strip() != "" and not _valid_password(form.password):
            raise HTTPException(400, "密码需为 1~72 字节，且不能包含空字符")
        exist = next((u for u in users if u.username == name), None)
        if exist is not None:
            # 编辑已有用户
            if form.password is not None and form.password.strip()!="":
                exist.password_hash = bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode()
            exist.allow_dirs = allow_dirs
            exist.is_admin = form.is_admin
        else:
            # 新增用户
            if not form.password or form.password.strip()=="":
                raise HTTPException(400, "新增用户必须填写密码")
            new_u = UserItem(
                username=name,
                password_hash=bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode(),
                allow_dirs=allow_dirs,
                is_admin=form.is_admin
            )
            users.append(new_u)
        # 校验：至少保留一个管理员账号；失败时从磁盘回滚，避免内存留下半写入状态
        try:
            check_at_least_one_admin(users)
        except HTTPException:
            reload_users()
            raise
        try:
            save_users(users)
        except Exception as exc:
            reload_users()
            raise HTTPException(500, f"保存失败：{exc}")
    add_log(_admin.username, "user_save", f"{'编辑' if exist is not None else '新增'}用户 {name}")
    return {"code":0,"msg":"保存成功"}

## 管理员删除用户
@app.delete("/api/admin/user/{username}")
def admin_del_user(username: str, _admin: UserItem = Depends(require_admin)):
    """同步端点：内部持 _users_lock，不能用 async 在事件循环里阻塞等锁。"""
    global users
    with _users_lock:
        reload_users()
        target_user = next((u for u in users if u.username == username), None)
        if not target_user:
            raise HTTPException(404, "用户不存在")
        users = [u for u in users if u.username != username]
        # 删除之后校验至少还有一个管理员；失败时回滚内存
        try:
            check_at_least_one_admin(users)
        except HTTPException:
            reload_users()
            raise
        try:
            save_users(users)
        except Exception as exc:
            reload_users()
            raise HTTPException(500, f"保存失败：{exc}")
        # 落盘成功之后再清会话：写盘失败时用户其实还在，提前清会话会把他踢下线
        with _session_lock:
            to_del = [k for k, (uname, _exp) in list(sessions.items()) if uname == username]
            for k in to_del:
                sessions.pop(k, None)
    add_log(_admin.username, "user_delete", f"删除用户 {username}")
    return {"code":0,"msg":"已删除"}

# ========== 随机幻灯片：全库图片索引（后台维护，点击路径只读） ==========
# 用户点击时只读内存索引，绝不触发全库扫描。索引按目录分组维护：
# 后台发现哪个目录变了就只重扫那一层（只有新增子目录才递归进子树），
# 因此「往一部影片目录里加几张图」只花一次 scandir，不再重走整个媒体库。
# 索引持久化到 config/，容器重启后也能立刻播放。
_IMAGES_INDEX_FILE = CONFIG_DIR / "random_images.json"
_IMAGES_INDEX_CHECK_SEC = 60        # 后台检查（兜底重建 / 落盘防抖）的间隔
_IMAGES_INDEX_MAX_AGE = 3600        # 兜底全量重建周期，修正 mtime 基线漂移
_IMAGES_INDEX_SAVE_MIN_INTERVAL = 120  # 增量变化后写盘的最短间隔（写盘防抖）
_IMAGES_INDEX_FORMAT = 2            # 落盘格式版本：2 = 按目录分组

# 目录绝对路径 -> 该目录下「非缩图」图片的相对路径列表。
# 空目录不入表：全库目录数远大于有图的目录数，省内存也省拼接时间。
_images_by_dir: Dict[str, List[str]] = {}
# 目录绝对路径 -> 直接子目录绝对路径列表，增量时用它判断子目录增删。
_images_subdirs: Dict[str, List[str]] = {}
# 派生：所有目录拼接成的一维列表，get_all_images 直接读它
_images_index: List[str] = []
_images_index_ts: float = 0.0        # 上次「全量重建」时间，只用于兜底周期
_images_index_gen: int = 0
_images_index_dirty: bool = True     # 语义：有人报告索引可能过期，请尽快校验一次
_images_index_unsaved: bool = False  # 内存已更新但还没落盘
_images_index_saved_ts: float = 0.0
_images_index_lock = threading.Lock()        # 只保护引用与标记，锁内绝不做 IO
_images_index_write_lock = threading.RLock()  # 串行化全量重建与增量合并（可重入）
_images_index_stop = threading.Event()

# 派生缓存：allow_dirs -> (主索引版本, 按权限过滤后的图片列表)
_all_images_cache: Dict[tuple, tuple] = {}
_all_images_lock = threading.Lock()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalized_allow_dirs(allow_dirs) -> tuple:
    """去掉被其它允许目录包含的冗余项，避免同一子树被重复计数。"""
    result = []
    for p in sorted(allow_dirs, key=lambda x: len(str(x))):
        if not any(_is_under(p, q) for q in result):
            result.append(p)
    return tuple(result)


def _visible_count(folder_abs: Path, allowed: tuple, stats: dict) -> int:
    """按用户允许目录裁剪文件夹的递归媒体数。

    folder 落在某个允许目录内 → 整棵子树可见，直接读快照计数；
    folder 是允许目录的祖先 → 只累加落在允许范围内的那些子树；
    都不满足 → 0（无权看到任何文件数）。
    """
    counts = stats["counts"]
    for allow_p in allowed:
        if _is_under(folder_abs, allow_p):
            return counts.get(str(folder_abs), 0)
    total = 0
    for allow_p in allowed:
        if _is_under(allow_p, folder_abs):
            total += counts.get(str(allow_p), 0)
    return total


def _entry_visible(path: Path, allowed: tuple, is_dir: bool) -> bool:
    """列表条目是否对当前用户可见。

    文件必须落在允许目录内；文件夹还允许「是允许目录的祖先」，
    这样受限用户能从根逐级导航到自己的目录，但看不到无关分支。
    """
    for allow_p in allowed:
        if _is_under(path, allow_p):
            return True
        if is_dir and _is_under(allow_p, path):
            return True
    return False


def _flatten_images(by_dir: Dict[str, List[str]]) -> List[str]:
    """把按目录分组的索引拼成一维列表（点击路径只认这个）。"""
    flat: List[str] = []
    for items in by_dir.values():
        flat.extend(items)
    return flat


def _save_images_index(by_dir: Dict[str, List[str]], subdirs: Dict[str, List[str]], ts: float):
    """原子落盘：先写临时文件再 rename，避免断电写坏索引。"""
    tmp = _IMAGES_INDEX_FILE.with_name(_IMAGES_INDEX_FILE.name + ".tmp")
    payload = {
        "v": _IMAGES_INDEX_FORMAT,
        "ts": ts,
        "count": sum(len(v) for v in by_dir.values()),
        "dirs": by_dir,
        "subdirs": subdirs,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _IMAGES_INDEX_FILE)


def _migrate_legacy_images(images: List[str]) -> tuple:
    """把 v1 的一维图片列表还原成目录分组。

    旧索引没有目录信息，但相对路径自带的父目录就够用：
    dirname 即分组键，再按 key 反推一层父子关系。完全空、且没有任何图片的
    子目录无法还原，代价只是第一次增量时多做一次递归扫描，不影响结果。
    """
    by_dir: Dict[str, List[str]] = {}
    for rel in images:
        try:
            abs_dir = str((REAL_BASE / Path(rel).parent))
        except Exception:
            continue
        by_dir.setdefault(abs_dir, []).append(rel)
    subdirs: Dict[str, List[str]] = {}
    for key in by_dir:
        parent = str(Path(key).parent)
        if parent != key:
            subdirs.setdefault(parent, []).append(key)
    return by_dir, subdirs


def load_images_index():
    """启动时从 config/ 恢复索引（毫秒级），文件损坏或不存在则由后台重建。"""
    global _images_by_dir, _images_subdirs, _images_index
    global _images_index_ts, _images_index_gen, _images_index_dirty
    global _images_index_unsaved, _images_index_saved_ts
    try:
        if _IMAGES_INDEX_FILE.exists():
            data = json.loads(_IMAGES_INDEX_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                by_dir = subdirs = None
                if isinstance(data.get("dirs"), dict):
                    by_dir = {}
                    for key, items in data["dirs"].items():
                        if isinstance(key, str) and isinstance(items, list):
                            by_dir[key] = [x for x in items if isinstance(x, str)]
                    raw_subs = data.get("subdirs")
                    subdirs = {}
                    if isinstance(raw_subs, dict):
                        for key, items in raw_subs.items():
                            if isinstance(key, str) and isinstance(items, list):
                                subdirs[key] = [x for x in items if isinstance(x, str)]
                    ts = float(data.get("ts", 0)) or time.time()
                elif isinstance(data.get("images"), list):
                    # v1 兼容：按路径分组，并在 60 秒内补一次全量重建
                    legacy = [x for x in data["images"] if isinstance(x, str)]
                    by_dir, subdirs = _migrate_legacy_images(legacy)
                    ts = 0.0
                if by_dir is not None:
                    flat = _flatten_images(by_dir)
                    with _images_index_lock:
                        _images_by_dir = by_dir
                        _images_subdirs = subdirs or {}
                        _images_index = flat
                        _images_index_ts = ts
                        _images_index_gen += 1
                        # 磁盘快照可能落后于停机期间的媒体库变更，标记待校准，
                        # 让启动预热做一次全量重建对齐磁盘（在后台线程，不阻塞服务）
                        _images_index_dirty = True
                        # 重新排一次盘：把旧格式升级成分组格式
                        _images_index_unsaved = ts == 0.0
                        _images_index_saved_ts = ts
                    print(f"[IMAGES] 从磁盘恢复图片索引 {len(flat)} 张 / {len(by_dir)} 个目录")
                    return
    except Exception as exc:
        print(f"[IMAGES] 图片索引文件损坏（{exc}），由后台重建")
    _images_index_dirty = True


def _mark_images_index_dirty():
    """媒体库可能变了：只做标记，实际校验交给后台，不阻塞用户点击。"""
    global _images_index_dirty
    with _images_index_lock:
        _images_index_dirty = True


def _clear_images_index_dirty():
    global _images_index_dirty
    with _images_index_lock:
        _images_index_dirty = False


def _images_index_loop():
    """启动时校准一次 + 每 _IMAGES_INDEX_MAX_AGE 全量重建一次。

    磁盘索引是上次落盘的快照，停机期间媒体库可能已经变了，所以启动后
    无条件全量重建一次（后台线程，不阻塞服务可用）。日常「哪个目录变了」
    由目录 watcher 驱动增量合并，这里不再定时全扫，百万级图库也不会出现
    「每十分钟全库重走一遍」的持续压力。
    """
    _rebuild_images_index("（启动校准）")
    while not _images_index_stop.wait(_IMAGES_INDEX_CHECK_SEC):
        try:
            with _images_index_lock:
                age = time.time() - _images_index_ts
                unsaved = _images_index_unsaved
                saved_age = time.time() - _images_index_saved_ts
            if age >= _IMAGES_INDEX_MAX_AGE:
                _rebuild_images_index("（兜底全量）")
            elif unsaved and saved_age >= _IMAGES_INDEX_SAVE_MIN_INTERVAL:
                _flush_images_index()
        except Exception as exc:
            print(f"[IMAGES] 后台索引维护异常：{exc}")


def _images_in_names(dir_p: Path, names) -> List[str]:
    """一个目录内的图片（排除封面/剧照/与视频同名的缩图）。

    video_stems 在本层只算一次，避免每张图片都去 scandir 父目录。
    """
    video_stems = {
        Path(n).stem.lower() for n in names if Path(n).suffix.lower() in VIDEO_EXT
    }
    images = []
    for name in names:
        if Path(name).suffix.lower() not in IMAGE_EXT:
            continue
        if is_cover_file(name, dir_p, video_stems):
            continue
        try:
            images.append(str((dir_p / name).relative_to(REAL_BASE)).replace(os.sep, "/"))
        except ValueError:
            continue
    return images


def _collect_images_grouped(root_p: Path) -> tuple:
    """walk 整棵子树：返回 ({目录: [图片]}, {目录: [直接子目录]})。"""
    by_dir: Dict[str, List[str]] = {}
    subdirs: Dict[str, List[str]] = {}
    for root, dirs, names in os.walk(root_p):
        root_path = Path(root)
        key = str(root_path)
        images = _images_in_names(root_path, names)
        if images:
            by_dir[key] = images
        if dirs:
            subdirs[key] = [str(root_path / d) for d in dirs]
    return by_dir, subdirs


def _scan_dir_shallow(dir_p: Path) -> Optional[tuple]:
    """只扫一层：返回 ([文件名], [子目录绝对路径])；目录已消失返回 None。

    其它 OSError（权限、I/O 故障、ESTALE）直接抛出，调用方据此保留原有条目
    —— 挂载抖一下就把整棵子树从索引里删掉是最坏的结果。
    """
    try:
        with os.scandir(dir_p) as it:
            entries = list(it)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return None
        raise
    names = [e.name for e in entries if not e.is_dir()]
    subs = [str(dir_p / e.name) for e in entries if e.is_dir()]
    return names, subs


def _drop_images_subtree(by_dir: dict, subdirs: dict, root_key: str):
    """从副本里删掉某个目录及其整棵子树的条目。"""
    prefix = root_key + os.sep
    for k in [k for k in by_dir if k == root_key or k.startswith(prefix)]:
        by_dir.pop(k, None)
    for k in [k for k in subdirs if k == root_key or k.startswith(prefix)]:
        subdirs.pop(k, None)


def _refresh_images_subtrees(changed, removed=()) -> bool:
    """按目录增量刷新图片索引，替代「有变化就全量重扫」。

    每个变化目录只重扫本层；只有子目录清单出现新增时才递归进新子树。
    调用方（_verify_folder_stats）传的是已 topmost 化的目录，父子同时变化
    时本轮只处理父目录，子目录由 watcher 下一轮发现后补上，最多晚一个周期。
    copy-on-write：构建期间用户点击读到的仍是旧索引，合并完成才整体换引用。
    """
    global _images_by_dir, _images_subdirs, _images_index
    global _images_index_gen, _images_index_unsaved, _images_index_dirty
    changed = [str(k) for k in changed]
    # 删除项先归并到最顶层：整棵目录树被删时，逐个删会退化成 O(n²)
    removed = _topmost_paths([str(k) for k in removed])
    if not changed and not removed:
        return False
    if not _media_root_ready():
        print("[IMAGES] /media 未挂载或不可读，跳过索引增量刷新")
        return False
    t0 = time.perf_counter()
    with _images_index_write_lock:
        with _images_index_lock:
            if not _images_index:
                return False
            new_by_dir = dict(_images_by_dir)
            new_subdirs = dict(_images_subdirs)
            old_subdirs = _images_subdirs
        touched = 0
        rescanned = []  # 已整棵重扫过的子树，其内部目录不必再逐个处理
        for key in sorted(set(removed), key=len):
            if any(key == r or key.startswith(r + os.sep) for r in rescanned):
                continue
            _drop_images_subtree(new_by_dir, new_subdirs, key)
            touched += 1
        for key in sorted(set(changed), key=len):
            if any(key == r or key.startswith(r + os.sep) for r in rescanned):
                continue
            dir_p = Path(key)
            try:
                scanned = _scan_dir_shallow(dir_p)
            except OSError as exc:
                print(f"[IMAGES] 目录暂时不可读，保留原有条目：{key}（{exc}）")
                continue
            touched += 1
            if scanned is None:
                _drop_images_subtree(new_by_dir, new_subdirs, key)
                continue
            names, subs = scanned
            images = _images_in_names(dir_p, names)
            if images:
                new_by_dir[key] = images
            else:
                new_by_dir.pop(key, None)
            if subs:
                new_subdirs[key] = subs
            else:
                new_subdirs.pop(key, None)
            # 子目录增删：新增的递归收进来，消失的整支摘掉
            previous = set(old_subdirs.get(key, []))
            current = set(subs)
            for gone in previous - current:
                _drop_images_subtree(new_by_dir, new_subdirs, gone)
            for added in current - previous:
                sub_by_dir, sub_dirs = _collect_images_grouped(Path(added))
                new_by_dir.update(sub_by_dir)
                new_subdirs.update(sub_dirs)
                rescanned.append(added)
        if not touched:
            return False
        ts = time.time()
        flat = _flatten_images(new_by_dir)
        with _images_index_lock:
            _images_by_dir = new_by_dir
            _images_subdirs = new_subdirs
            _images_index = flat
            _images_index_gen += 1
            _images_index_unsaved = True
            _images_index_dirty = False
            need_save = ts - _images_index_saved_ts >= _IMAGES_INDEX_SAVE_MIN_INTERVAL
        with _all_images_lock:
            _all_images_cache.clear()
        if need_save:
            _flush_images_index()
        print(f"[IMAGES] 增量刷新 {len(flat)} 张 / {touched} 个目录，"
              f"耗时 {time.perf_counter()-t0:.3f}s")
        return True


def _flush_images_index() -> bool:
    """把当前内存索引落盘（写盘防抖由调用方判断）。"""
    global _images_index_unsaved, _images_index_saved_ts
    with _images_index_write_lock:
        with _images_index_lock:
            # 全库真的被清空时 _images_by_dir 也是空的，仍要落盘并复位标记，
            # 否则 unsaved 永远清不掉，后台每 60 秒空转一次
            if not _images_index_unsaved:
                return False
            by_dir = _images_by_dir
            subdirs = _images_subdirs
        ts = time.time()
        try:
            _save_images_index(by_dir, subdirs, ts)
        except Exception as exc:
            print(f"[IMAGES] 索引落盘失败：{exc}")
            return False
        with _images_index_lock:
            _images_index_unsaved = False
            _images_index_saved_ts = ts
        return True


def _rebuild_images_index(reason: str = "") -> bool:
    """全量重建：整库扫描 → 原子落盘 → 替换内存引用 → 失效派生缓存。"""
    global _images_by_dir, _images_subdirs, _images_index
    global _images_index_ts, _images_index_gen, _images_index_dirty
    global _images_index_unsaved, _images_index_saved_ts
    t0 = time.perf_counter()
    if not _media_root_ready():
        print("[IMAGES] /media 未挂载或不可读，跳过本次重建")
        return False
    with _images_index_write_lock:
        try:
            by_dir, subdirs = _collect_images_grouped(REAL_BASE)
        except Exception as exc:
            print(f"[IMAGES] 索引重建失败：{exc}")
            return False
        with _images_index_lock:
            old_len = len(_images_index)
        if old_len and not by_dir:
            # 索引非空却扫出 0 张：几乎都是挂载点没生效或库暂时读不到
            print(f"[IMAGES] 扫描结果从 {old_len} 张变成 0 张，疑似挂载异常，保留原索引")
            return False
        ts = time.time()
        flat = _flatten_images(by_dir)
        with _images_index_lock:
            _images_by_dir = by_dir
            _images_subdirs = subdirs
            _images_index = flat
            _images_index_ts = ts
            _images_index_gen += 1
            _images_index_dirty = False
        with _all_images_lock:
            _all_images_cache.clear()
        try:
            _save_images_index(by_dir, subdirs, ts)
            with _images_index_lock:
                _images_index_unsaved = False
                _images_index_saved_ts = ts
        except Exception as exc:
            print(f"[IMAGES] 索引落盘失败（{exc}），仅更新内存")
            with _images_index_lock:
                _images_index_unsaved = True
    print(f"[IMAGES] 索引重建完成 {len(flat)} 张 / {len(by_dir)} 个目录，"
          f"耗时 {time.perf_counter()-t0:.2f}s{reason}")
    return True


def _allow_prefixes(allowed) -> List[str]:
    """把允许目录换算成「相对媒体根的 posix 路径前缀」。

    受限用户的过滤是百万级热路径：原来每条都要构造 Path 再 relative_to
    并捕获异常，实测 100 万张要 10 秒以上；换成字符串前缀后只剩几十毫秒。
    索引里的路径都是 posix 分隔、且都位于 REAL_BASE 之内，语义完全等价。
    """
    prefixes = []
    for p in allowed:
        try:
            rel = p.relative_to(REAL_BASE).as_posix()
        except ValueError:
            continue
        if rel in ("", "."):
            continue
        prefixes.append(rel + "/")
    return prefixes


def get_all_images(user: UserItem) -> List[str]:
    """点击路径：只读内存索引并按 allow_dirs 过滤，绝不触发全库扫描。"""
    key = tuple(sorted(user.allow_dirs))
    with _images_index_lock:
        source = _images_index
        gen = _images_index_gen
    with _all_images_lock:
        cached = _all_images_cache.get(key)
        if cached is not None and cached[0] == gen:
            return cached[1]
    allowed = _resolved_allow_dirs(user.allow_dirs)
    if any(x == REAL_BASE for x in allowed):
        images = list(source)
    else:
        prefixes = _allow_prefixes(allowed)
        images = [rel for rel in source if any(rel.startswith(pfx) for pfx in prefixes)]
    with _all_images_lock:
        _all_images_cache[key] = (gen, images)
    return images


@app.get("/api/random-images")
def api_random_images(limit: int = 1000, user: UserItem = Depends(get_current_user)):
    """从整个媒体库随机抽取图片（按用户允许目录过滤），供首页随机幻灯片使用。"""
    _touch_activity()  # 只看幻灯片也算有人访问，后台别因空闲暂停
    limit = max(1, min(limit, RANDOM_IMAGES_LIMIT_MAX))
    # 首次部署时后台预热可能尚未完成，最多等 1.5 秒；不在这里自己扫全库
    if not _images_index:
        deadline = time.time() + 1.5
        while time.time() < deadline and not _images_index:
            time.sleep(0.05)
    if not _images_index:
        return {"code": 2, "list": [], "total": 0, "msg": "图片索引准备中，请稍候重试"}
    images = get_all_images(user)
    picked = random.sample(images, min(limit, len(images))) if images else []
    items = [
        {"id": p, "name": Path(p).name, "type": "image", "path": p}
        for p in picked
    ]
    return {"code": 0, "list": items, "total": len(images)}


# ========== 媒体列表接口 ==========
# 目录列表缓存：key=解析后目录路径, value=(目录mtime, 缓存时间戳, items)
_dir_cache: Dict[str, tuple] = {}
_dir_cache_lock = threading.Lock()
_DIR_CACHE_MAX = 500
_DIR_CACHE_TTL = 10  # 条目缓存窗口；快照靠 mtime 增量更新，缩短此值让角标更快跟上变化

# 目录统计快照：一次全库自底向上遍历，算出每个目录的递归媒体数与最佳封面。
# 快照长期有效，目录 mtime 变化时才增量重扫那一支并把差值传播到所有祖先；
# TTL 只是兜底全量重建周期，覆盖「深层变了但用户始终没打开到那一层」的情况。
_FOLDER_STATS_TTL = 1800
_FOLDER_STATS_CHECK_SEC = 15  # 后台比对全库目录 mtime 的间隔（秒）
_FOLDER_STATS_IDLE_SEC = 90   # 超过这段时间无人访问就暂停后台校验
_folder_stats_lock = threading.Lock()
_folder_stats_refresh_lock = threading.Lock()  # 串行化增量刷新，避免锁内做文件 IO
_folder_stats: dict = {}
_folder_stats_building = False
_last_list_activity = time.time()
_last_verify_ts = 0.0                        # 上次真正比对完全库 mtime 的时间
_folder_watcher_stop = threading.Event()
_folder_watcher_wake = threading.Event()     # 有人访问时提前叫醒后台，不必等满周期


def invalidate_folder_stats():
    """媒体内容变化后让快照失效（替换引用，不动正在被读取的旧快照）。"""
    global _folder_stats
    with _folder_stats_lock:
        _folder_stats = {}


def _summarize_dir(root_p: Path, dirs, names, child_counts: dict) -> tuple:
    """统计单个目录：返回 (递归媒体数, 最佳封面相对路径, 首图相对路径)。

    child_counts 里应已包含所有子目录的递归数（调用方需自底向上遍历）。
    """
    video_stems = {
        Path(n).stem.lower()
        for n in names if Path(n).suffix.lower() in VIDEO_EXT
    }
    own = 0
    best_rank, best_cover = 99, None
    first_img = None
    for name in names:
        suf = Path(name).suffix.lower()
        if suf not in MEDIA_EXTS:
            continue
        rel = str((root_p / name).relative_to(REAL_BASE)).replace(os.sep, "/")
        if is_cover_file(name, root_p, video_stems):
            rank = artwork_rank(name, video_stems)
            if rank < best_rank:
                best_rank, best_cover = rank, rel
        else:
            own += 1
            if suf in IMAGE_EXT and first_img is None:
                first_img = rel
    total = own + sum(child_counts.get(str(root_p / d), 0) for d in dirs)
    return total, best_cover, first_img


def _get_folder_stats() -> dict:
    """返回完整快照引用；构建期间其它请求复用旧快照，避免并发全库遍历。"""
    global _folder_stats, _folder_stats_building
    now = time.time()
    with _folder_stats_lock:
        stale = _folder_stats
        if stale and now - stale["ts"] < _FOLDER_STATS_TTL:
            return stale
        if _folder_stats_building:
            return stale
        _folder_stats_building = True
    data = {}
    try:
        # 构建放锁外（大库可能耗时数秒），避免其它请求排队等锁
        counts, covers, first_imgs, mtimes, children = {}, {}, {}, {}, {}
        for root, dirs, names in os.walk(REAL_BASE, topdown=False):
            root_p = Path(root)
            key = str(root_p)
            # 自底向上：子目录此时已算完，直接累加即可，不需要重复遍历子树
            total, cover, first = _summarize_dir(root_p, dirs, names, counts)
            counts[key] = total
            covers[key] = cover
            first_imgs[key] = first
            children[key] = [str(root_p / d) for d in dirs]
            try:
                mtimes[key] = os.stat(root).st_mtime
            except OSError:
                mtimes[key] = 0.0  # 基线未知，下一轮校验会补上真实 mtime
        data = {"ts": time.time(), "counts": counts, "covers": covers,
                "first_imgs": first_imgs, "mtimes": mtimes, "children": children}
    except Exception as exc:
        print(f"[FOLDER] 目录统计快照构建失败：{exc}")
    finally:
        with _folder_stats_lock:
            _folder_stats_building = False
            if data:
                # 替换引用而非原地 clear/update：持有旧快照的请求不会被清空一半
                _folder_stats = data
    # 构建失败（如媒体根暂时不可读）时沿用旧快照，比逐目录重新扫描更安全
    return data or stale


def _refresh_folder_subtrees(changed, removed=(), current_dir: Path = None,
                              current_mtime=None) -> dict:
    """只重扫变化目录的子树，把差值传播到所有祖先。

    copy-on-write：先复制索引再修改并整体替换引用，持有旧快照的请求不受影响。
    changed 是目录 Path 列表，removed 是已删除目录的绝对路径字符串列表。
    """
    global _folder_stats
    # 只在此锁内做纯内存的引用读取；下面的 scandir/os.walk 放到锁外，
    # 否则新增目录触发全库重扫时会阻塞所有 api_list 请求数秒
    with _folder_stats_refresh_lock:
        with _folder_stats_lock:
            old = _folder_stats
        if not old:
            return old
        new = {
            "ts": old["ts"],  # 局部刷新不重置兜底全量重建的计时
            "counts": dict(old["counts"]),
            "covers": dict(old["covers"]),
            "first_imgs": dict(old["first_imgs"]),
            "mtimes": dict(old.get("mtimes", {})),
            "children": {k: list(v) for k, v in old.get("children", {}).items()},
        }
        fields = ("counts", "covers", "first_imgs", "mtimes", "children")
        for folder, rescan in ([(Path(f), True) for f in changed] +
                               [(Path(k), False) for k in removed]):
            prefix = str(folder)
            old_count = new["counts"].get(prefix, 0)
            # 先看子目录清单是否变化：没变就只重算本目录（1 次 scandir），
            # 避免后台校验发现「加了几张图」时把整棵子树重扫一遍
            light = False
            sub_dirs, file_names, actual_children = [], [], []
            if rescan:
                try:
                    with os.scandir(folder) as it:
                        dir_entries = list(it)
                    sub_dirs = [e.name for e in dir_entries if e.is_dir()]
                    file_names = [e.name for e in dir_entries if not e.is_dir()]
                    actual_children = [str(folder / d) for d in sub_dirs]
                    light = set(actual_children) == set(new["children"].get(prefix, []))
                except OSError:
                    light = False
            if light:
                total, cover, first = _summarize_dir(folder, sub_dirs, file_names, new["counts"])
                new["counts"][prefix] = total
                new["covers"][prefix] = cover
                new["first_imgs"][prefix] = first
                new["children"][prefix] = actual_children
                try:
                    new["mtimes"][prefix] = os.stat(folder).st_mtime
                except OSError:
                    new["mtimes"][prefix] = 0.0
                new_count = total
            else:
                # 清掉这一支的旧条目（含已从磁盘消失的目录）
                for k in [k for k in new["counts"] if k == prefix or k.startswith(prefix + os.sep)]:
                    for d in fields:
                        new[d].pop(k, None)
                new_count = 0
                if rescan:
                    local = {}
                    for root, dirs, names in os.walk(folder, topdown=False):
                        root_p = Path(root)
                        key = str(root_p)
                        total, cover, first = _summarize_dir(root_p, dirs, names, local)
                        local[key] = total
                        new["counts"][key] = total
                        new["covers"][key] = cover
                        new["first_imgs"][key] = first
                        new["children"][key] = [str(root_p / d) for d in dirs]
                        try:
                            new["mtimes"][key] = os.stat(root).st_mtime
                        except OSError:
                            new["mtimes"][key] = 0.0
                    new_count = local.get(prefix, 0)
            # 同步父目录的子目录清单（新增 / 删除目录）
            parent_key = str(folder.parent)
            if parent_key in new["children"]:
                sibs = [c for c in new["children"][parent_key] if c != prefix]
                if rescan and prefix not in sibs:
                    sibs.append(prefix)
                new["children"][parent_key] = sibs
            # 任一子树的增减量，对它的所有祖先都是同一个 delta
            delta = new_count - old_count
            if delta:
                anc = folder.parent
                while True:
                    akey = str(anc)
                    if akey in new["counts"]:
                        new["counts"][akey] += delta
                    if anc == REAL_BASE or anc == anc.parent:
                        break
                    anc = anc.parent
        if current_dir is not None:
            new["mtimes"][str(current_dir)] = current_mtime
        with _folder_stats_lock:
            _folder_stats = new
        # 角标变了，其它目录已缓存的 items 也带着旧数字，一并失效
        with _dir_cache_lock:
            _dir_cache.clear()
        return new


def _topmost_paths(paths):
    """只保留最顶层目录：父目录要重扫时，子目录不必重复处理。"""
    result = []
    for p in sorted(set(paths), key=lambda x: (len(x), x)):
        if not any(p == q or p.startswith(q + os.sep) for q in result):
            result.append(p)
    return result


def _removed_are_real(removed: list, sample: int = 12) -> bool:
    """区分「用户真的删了一批目录」和「挂载掉线导致全库 stat 不到」。

    真删除时父目录还在、可 scandir，且里面确实没有这个子目录名；
    挂载异常时父目录本身也读不到。只抽查少量最顶层路径，首尾各取一半，
    避免为保护逻辑再走一遍全库。
    """
    roots = _topmost_paths(removed)
    if len(roots) > sample:
        half = sample // 2
        picks = roots[:half] + roots[-half:]
    else:
        picks = roots
    for key in picks:
        p = Path(key)
        try:
            with os.scandir(p.parent) as it:
                if any(e.name == p.name for e in it):
                    return False  # 目录其实还在，是读取时序问题
        except OSError:
            return False
    return True


def _media_root_ready(mountinfo_path: str = "/proc/self/mountinfo") -> bool:
    """校验前先体检 /media：挂载是否生效、媒体根是否可访问。

    Linux 容器里 /media 是 bind mount，挂载没生效时它只是镜像自带的空目录，
    此时逐目录 stat 会把全库判成「已删除」。非 Linux（本地开发）无此概念，
    mountinfo 不存在就跳过挂载检测，只确认媒体根可访问。
    mountinfo_path 可注入，便于验证挂载判定的真实链路。
    """
    if Path(mountinfo_path).is_file() and not _media_mount_ready(REAL_BASE, mountinfo_path):
        return False
    try:
        os.stat(REAL_BASE)
        return True
    except OSError:
        return False


def _verify_folder_stats(mountinfo_path: str = "/proc/self/mountinfo") -> int:
    """后台比对全库目录 mtime，任意层级变化都增量刷新快照。

    先确认 /media 挂载生效；之后只做 stat、不读目录内容，
    目录增删会改变父目录 mtime，重扫父目录时自然纳入新增子目录。
    返回处理的目录数。
    """
    if not _media_root_ready(mountinfo_path):
        print("[FOLDER] /media 未挂载或不可读，跳过本次目录校验")
        return 0
    with _folder_stats_lock:
        snap = _folder_stats
    rebuilt_baseline = not snap
    if not snap:
        # 还没人翻过目录时快照是空的，角标和图片索引都需要一个 mtime 基线
        snap = _get_folder_stats()
    if not snap:
        return 0
    # 缓存任务结束时 invalidate_folder_stats() 会清空快照。基线按「当前磁盘」
    # 重建后，任务期间的增删已被吸收进 mtime，下面再比对必然是「无变化」。
    # 若此时索引还标着 dirty，绝不能据此认定它是最新的，直接全量校准：
    # 否则新图/已删图会一直留在随机幻灯片里，直到 1 小时后的兜底重建。
    if rebuilt_baseline:
        with _images_index_lock:
            need_calibration = _images_index_dirty
        if need_calibration:
            # 成功时 dirty 已在重建内部清掉；失败保留，等下一轮重试
            _rebuild_images_index("（基线重建后校准）")
            return 0
    changed, removed = [], []
    unreadable = 0
    for key, old_mt in snap.get("mtimes", {}).items():
        try:
            mt = os.stat(key).st_mtime
        except OSError as exc:
            # 只有「目录确实不存在」才当删除；权限不足 / I/O 故障 / ESTALE
            # 一律视为不可判定，不能据此清掉缓存（挂载异常时尤其危险）
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                removed.append(key)
            else:
                unreadable += 1
            continue
        if mt != old_mt:
            changed.append(key)
    # 第二层保护：中途掉线或大范围子目录读不到时拦住。
    # 注意 removed 不能按「数量大」整体放弃：快照没更新就会每 15 秒重复跳过，
    # 后台校验被永久楔住，已删除的图片会一直留在随机幻灯片索引里。
    # 改为逐个确认「父目录可读且里面确实没这个目录」，真删除照常刷新。
    total_dirs = len(snap.get("mtimes", {}))
    if unreadable > max(5, total_dirs // 5):
        print("[FOLDER] 子目录大面积不可判定（I/O 故障或挂载掉线），跳过本次校验")
        return 0
    if removed and not _removed_are_real(removed):
        print("[FOLDER] 目录消失但父目录不可读，疑似挂载异常，跳过本次校验")
        return 0
    if not changed and not removed:
        _clear_images_index_dirty()
        return 0
    roots = _topmost_paths(changed)
    removed_roots = [k for k in _topmost_paths(removed)
                     if not any(k == r or k.startswith(r + os.sep) for r in roots)]
    if not roots and not removed_roots:
        return 0
    _refresh_folder_subtrees([Path(k) for k in roots], removed_roots)
    # 同一次 mtime 比对顺带更新图片索引，不再为它单独全库重扫一遍。
    # 调用方传的是已 topmost 化的 roots，父子同时变化时只处理父目录；
    # 子目录的旧 mtime 留在快照里，下一轮会被再次发现并补上，最多晚一个周期。
    if _refresh_images_subtrees(roots, removed_roots):
        # 增量刷新失败（挂载异常 / 目录不可读 / 索引为空）时不能清 dirty，
        # 否则变化就再也没人补了
        _clear_images_index_dirty()
    return len(roots) + len(removed_roots)


def _touch_activity():
    """有人访问：刷新活跃时间；距上次校验够久就顺带把后台立刻叫醒。

    只做标记不清算，真正的全库 stat 仍在后台线程里跑，点击路径不会被拖慢。
    """
    global _last_list_activity
    now = time.time()
    _last_list_activity = now
    if now - _last_verify_ts >= _FOLDER_STATS_CHECK_SEC:
        _folder_watcher_wake.set()


def _folder_watcher_loop():
    """空闲时自动暂停，有人访问才校验，避免没人看也一直打扰 NAS。

    平时最多睡 _FOLDER_STATS_CHECK_SEC；页面一有请求就提前醒，
    这样「打开页面 → 点随机幻灯片」之间那几秒就足够把新图并进索引。
    """
    global _last_verify_ts
    while not _folder_watcher_stop.is_set():
        _folder_watcher_wake.wait(_FOLDER_STATS_CHECK_SEC)
        _folder_watcher_wake.clear()
        if _folder_watcher_stop.is_set():
            break
        try:
            with _images_index_lock:
                hint = _images_index_dirty
            # 缓存任务 / 启动预热报告过索引可能过期，就插队校验一次
            if not hint and time.time() - _last_list_activity > _FOLDER_STATS_IDLE_SEC:
                continue
            n = _verify_folder_stats()
            _last_verify_ts = time.time()
            # 校验期间攒下的唤醒已经过时，清掉，下一轮老老实实睡满周期
            _folder_watcher_wake.clear()
            if n:
                print(f"[FOLDER] 后台检测到 {n} 处目录变化，已增量刷新角标与图片索引")
        except Exception as exc:
            print(f"[FOLDER] 后台目录校验异常：{exc}")


def _folder_info_uncached(folder_abs: Path):
    """快照不可用时的退化实现：只扫这一个目录及其子树。"""
    cover_rel, first_img = None, None
    best_rank = 99
    try:
        video_stems = set()
        with os.scandir(folder_abs) as it:
            entries = list(it)
        for entry in entries:
            if entry.is_file() and Path(entry.name).suffix.lower() in VIDEO_EXT:
                video_stems.add(Path(entry.name).stem.lower())
        for entry in entries:
            if not entry.is_file():
                continue
            suf = Path(entry.name).suffix.lower()
            if suf not in MEDIA_EXTS:
                continue
            rel = os.path.relpath(entry.path, REAL_BASE).replace(os.sep, "/")
            if is_cover_file(entry.name, folder_abs, video_stems):
                rank = artwork_rank(entry.name, video_stems)
                if rank < best_rank:
                    best_rank, cover_rel = rank, rel
            elif suf in IMAGE_EXT and first_img is None:
                first_img = rel
        count = 0
        for sub_root, _dirs, sub_names in os.walk(folder_abs):
            stems = {
                Path(n).stem.lower()
                for n in sub_names if Path(n).suffix.lower() in VIDEO_EXT
            }
            for name in sub_names:
                if (Path(name).suffix.lower() in MEDIA_EXTS
                        and not is_cover_file(name, Path(sub_root), stems)):
                    count += 1
        chosen = cover_rel or first_img
        return ("/" + chosen if chosen else None), count
    except Exception:
        return None, 0

@app.get("/api/list")
def api_list(dir: str = "", user: UserItem = Depends(get_current_user)):
    _touch_activity()
    work_path = check_dir_allowed(user, dir)
    if not work_path.exists() or not work_path.is_dir():
        return {"list": [], "breadcrumb": []}

    # 面包屑必须基于已解析的真实目录算，不能用原始 dir：
    # dir="/photos/2024" 的 Path.parts 首段是 '/'，会拼出 '//photos'，
    # 前端回传后斜杠逐次累加；dir 里带 .. 还会把编造的名字塞进面包屑。
    breadcrumb = []
    try:
        parts = work_path.relative_to(REAL_BASE).parts
    except ValueError:
        parts = ()
    for i in range(len(parts)):
        breadcrumb.append({"name": parts[i], "path": "/".join(parts[:i + 1])})

    # 目录缓存：目录 mtime 未变则复用上次结果，避免重复遍历
    try:
        dir_mtime = work_path.stat().st_mtime
    except OSError:
        dir_mtime = 0
    # 缓存按「目录 + 用户允许目录」隔离：不同权限看到的角标可能不同
    allowed = _normalized_allow_dirs(_resolved_allow_dirs(user.allow_dirs))
    cache_key = (str(work_path), tuple(sorted(user.allow_dirs)))
    with _dir_cache_lock:
        cached = _dir_cache.get(cache_key)
    if cached is not None and cached[0] == dir_mtime and (time.time() - cached[1]) < _DIR_CACHE_TTL:
        return {"list": cached[2], "breadcrumb": breadcrumb}

    stats = _get_folder_stats()
    # 首次构建中 / 构建失败时 counts 为空。此时若对每个文件夹调用
    # _folder_info_uncached，一次列表会退化成整库 os.walk，比正常路径更慢。
    stats_ready = bool(stats and stats.get("counts"))

    items = []
    # scandir 复用目录项缓存：is_dir()/stat() 不再重复发起系统调用（NAS 上收益明显）
    with os.scandir(work_path) as it:
        entries = sorted(it, key=lambda e: e.name.lower())
    # 每个条目只 stat 一次，结果同时供「mtime 变化检测」和列表字段使用
    stat_cache = {}
    for entry in entries:
        try:
            stat_cache[entry.path] = entry.stat()
        except OSError:
            stat_cache[entry.path] = None
    root_video_stems = {
        Path(e.name).stem.lower()
        for e in entries
        if e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXT
    }
    # 快照长期有效：只有目录 mtime 变化（或有目录增删）才重扫对应子树
    if stats_ready:
        mtimes = stats.get("mtimes", {})
        changed = []
        actual_dirs = set()
        for entry in entries:
            if not entry.is_dir():
                continue
            key = str(Path(entry.path))
            actual_dirs.add(key)
            st = stat_cache.get(entry.path)
            if key not in stats["counts"] or (st is not None and mtimes.get(key) != st.st_mtime):
                changed.append(Path(entry.path))
        expected_dirs = set(stats.get("children", {}).get(str(work_path), []))
        removed = expected_dirs - actual_dirs
        if changed or removed:
            stats = _refresh_folder_subtrees(changed, removed, work_path, dir_mtime)

    def get_folder_info(folder_abs: Path):
        if not stats_ready:
            # 快照未就绪：角标暂显 0，等构建完成后下一次请求即为准确值
            return None, 0
        # 文件夹只是「祖先可见」时，其直接子项（含封面）可能落在允许范围外，
        # 不返回封面路径，避免前端请求到无权文件
        fully_visible = any(_is_under(folder_abs, p) for p in allowed)
        if stats:
            key = str(folder_abs)
            if key in stats["counts"]:
                cover_rel = stats["covers"].get(key) or stats["first_imgs"].get(key)
                cover = "/" + cover_rel if (cover_rel and fully_visible) else None
                return cover, _visible_count(folder_abs, allowed, stats)
        # 快照不可用时的退化路径：无法精确裁剪，仅完全可见目录返回统计
        if not fully_visible:
            return None, 0
        return _folder_info_uncached(folder_abs)

    for entry in entries:
        if not _entry_visible(Path(entry.path), allowed, entry.is_dir()):
            continue
        if is_cover_file(entry.name, work_path, root_video_stems):
            continue
        try:
            rel_str = os.path.relpath(entry.path, REAL_BASE).replace(os.sep, "/")
        except Exception:
            continue
        st = stat_cache.get(entry.path)
        size = st.st_size if st is not None else None
        entry_mtime = st.st_mtime if st is not None else None
        if entry.is_dir():
            cover, count = get_folder_info(Path(entry.path))
            items.append({
                "id": rel_str,
                "name": entry.name,
                "type": "folder",
                "path": rel_str,
                "cover_path": cover,
                "count": count,
                "mtime": entry_mtime,
            })
        else:
            suf = Path(entry.name).suffix.lower()
            if suf in IMAGE_EXT:
                items.append({
                    "id": rel_str, "name": entry.name, "type": "image",
                    "path": rel_str, "size": size, "mtime": entry_mtime,
                })
            elif suf in VIDEO_EXT:
                duration = get_video_duration(str(Path(entry.path)), fetch=False)
                items.append({
                    "id": rel_str, "name": entry.name, "type": "video",
                    "path": rel_str, "size": size, "mtime": entry_mtime, "duration": duration,
                })

    with _dir_cache_lock:
        if len(_dir_cache) >= _DIR_CACHE_MAX:
            _dir_cache.clear()
        _dir_cache[cache_key] = (dir_mtime, time.time(), items)
    return {"list": items, "breadcrumb": breadcrumb}

# ========== 原图接口 ==========
@app.get("/api/src")
def api_src(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404)
    return FileResponse(fp)

# ========== 缩略图接口（图片 Pillow / 视频 ffmpeg，结果落盘缓存） ==========
# 缩略图生成专用线程池：不占用 Starlette 默认的 40 线程池，否则一次列表
# 请求几十张图时，线程全卡在等生成槽上，/api/list、/api/cache-status 一起排队。
# 16 个 worker：其中最多 4 个会阻塞在生成信号量上（cover._GEN_SLOTS），
# 其余要能立刻服务「缓存已命中」的请求。
_thumb_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="thumb")


def _thumb_response(user: UserItem, path: str):
    """缩略图的整条流程都在这里，包括路径校验和两次 stat。

    这些全是阻塞调用：NAS 上一次 lstat 就要 0.5~3ms，一个请求 5~8 次，
    留在事件循环里会把所有接口一起卡住（改造前该端点是同步 def，整段在
    线程池里跑，所以这里必须整体丢进专用线程池，不能只挪 ensure_thumb）。
    """
    fp = check_path_allowed(user, path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404)
    suf = fp.suffix.lower()
    if suf in MEDIA_EXTS:
        try:
            rel = str(fp.relative_to(REAL_BASE)).replace(os.sep, "/")
        except ValueError:
            raise HTTPException(404)
        cache_path = ensure_thumb(fp, rel)
        if cache_path is not None and cache_path.exists():
            return FileResponse(cache_path)
    # 视频封面生成失败时不回退原文件：<img> 无法渲染视频，
    # 回退只会把几十 MB 原片白白传给浏览器且没有任何显示效果
    if suf in VIDEO_EXT:
        raise HTTPException(404)
    # 图片生成失败仍回退原图，至少能看到内容
    return FileResponse(fp)


@app.get("/api/thumb")
async def api_thumb(path: str, user: UserItem = Depends(get_current_user)):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thumb_pool, _thumb_response, user, path)

# ========== 缓存统计接口 ==========
@app.get("/api/cache-stats")
def cache_stats(_admin: UserItem = Depends(require_admin)):
    """统计里带着全库失败文件的相对路径，会把无权目录的文件名暴露给受限用户。"""
    with _cache_stats_lock:
        stats = dict(_cache_stats)
    return {
        "code": 0,
        "total": stats["total"],
        "cached": stats["cached"],
        "uncached": stats["uncached"],
        "failed": stats.get("failed", 0),
        "failed_files": stats.get("failed_files", []),
        "failed_files_truncated": stats.get("failed_files_truncated", False),
        "last_finish_time": stats["last_finish_time"],
    }


# ========== 执行日志接口 ==========
@app.get("/api/logs")
def api_logs(limit: int = 200, _admin: UserItem = Depends(require_admin)):
    limit = max(1, min(limit, LOG_LIMIT_MAX))
    return {"code": 0, "logs": read_logs(limit)}


@app.delete("/api/logs")
def api_clear_logs(_admin: UserItem = Depends(require_admin)):
    """清空全部执行日志（保留一条清空操作记录，便于审计）。"""
    global _log_line_count
    try:
        with _log_lock:
            if _LOG_FILE.exists():
                _LOG_FILE.write_text("", encoding="utf-8")
            _log_line_count = 0
    except Exception:
        raise HTTPException(500, detail="清除日志失败")
    # 清空后记录一条操作日志（add_log 内部自加锁，不可在 _log_lock 内调用）
    add_log(_admin.username, "logs_clear", "清空执行日志")
    return {"code": 0, "msg": "已清空"}


# ========== 缓存任务接口 ==========
@app.get("/api/cache-status")
async def cache_status(user: UserItem = Depends(get_current_user)):
    snap = cache_task.snapshot()
    if not user.is_admin:
        # 缓存任务遍历的是全库，current 会带出受限用户无权目录的文件名。
        # 进度只需要数值字段，把路径剔掉（前端也没用到 current）。
        snap.pop("current", None)
    return snap

@app.get("/api/cache-run")
async def cache_run(admin: UserItem = Depends(require_admin)):
    """触发全库扫描，NAS 上会打满 IO，只允许管理员操作。"""
    if cache_task.start(operator=admin.username):
        add_log(admin.username, "cache_run", "手动触发预生成缓存")
        return {"code": 0, "msg": "任务已启动"}
    if not cache_task.running:
        # start() 返回 False 但状态不是运行中，说明线程根本没起来（内存/线程数耗尽）
        return {"code": 2, "msg": "任务启动失败，请查看服务日志"}
    return {"code": 1, "msg": "已有任务在运行"}

@app.get("/api/cache-stop")
async def cache_stop(admin: UserItem = Depends(require_admin)):
    """会打断管理员或定时任务，同样只允许管理员操作。"""
    cache_task.stop()
    add_log(admin.username, "cache_stop", "取消缓存任务")
    return {"code": 0, "msg": "停止指令已发送"}

# ========== 设置持久化接口 ==========
@app.get("/api/settings")
def api_get_settings(user: UserItem = Depends(get_current_user)):
    s = load_settings()
    return {
        "code": 0,
        "settings": {
            "slide_delay": s.get("slide_delay", 5),
            "slide_loop": s.get("slide_loop", True),
        },
    }

@app.post("/api/settings")
def api_save_settings(form: SettingsForm, _admin: UserItem = Depends(require_admin)):
    """这组设置是全局的，会影响所有人，因此只允许管理员修改。"""
    s = load_settings()
    s["slide_delay"] = form.slide_delay
    s["slide_loop"] = form.slide_loop
    save_settings(s)
    return {"code": 0, "msg": "ok"}

@app.get("/")
async def index():
    return FileResponse(_FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    # 在项目根目录执行：python -m backend.main
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000)
