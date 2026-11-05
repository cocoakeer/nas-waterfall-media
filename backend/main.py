import os
import errno
import json
import bcrypt
import uuid
import random
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
    thumb_source,
    load_duration_cache,
    save_duration_cache,
)
from .config import load_settings, save_settings

# ========== 配置读取 适配compose CONFIG_PATH / CACHE_PATH ==========
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
REAL_BASE = Path(MEDIA_ROOT).resolve()  # 预计算，避免每个请求重复 resolve
CONFIG_DIR = Path(os.getenv("CONFIG_PATH", "/config"))
CACHE_DIR = Path(os.getenv("CACHE_PATH", "/cache"))
# 创建目录并设置权限，打印路径用于排错
CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o775)
CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o775)
USER_CONFIG_PATH = CONFIG_DIR / "users.json"
print(f"[CONFIG] 用户配置文件路径: {USER_CONFIG_PATH}")

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
    USER_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def reload_users():
    global users
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
    resolved = tuple((REAL_BASE / ad.lstrip("/")).resolve() for ad in allow_dirs)
    if len(_allow_dirs_cache) < 100:
        _allow_dirs_cache[key] = resolved
    return resolved


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
_cache_stats = {
    "total": 0,
    "cached": 0,
    "uncached": 0,
    "failed": 0,
    "failed_files": [],  # 缓存失败的文件相对路径列表
    "last_finish_time": None,  # 上次缓存任务完成时间（epoch 秒）
}
_cache_stats_lock = threading.Lock()


def load_cache_stats():
    """启动时从磁盘加载上次的统计快照。"""
    try:
        if _CACHE_STATS_FILE.exists():
            data = json.loads(_CACHE_STATS_FILE.read_text(encoding="utf-8"))
            with _cache_stats_lock:
                _cache_stats.update(data)
    except Exception:
        pass


def record_cache_stats(total: int, cached: int, failed: int = 0, failed_files: list = None):
    """缓存任务完成后记录统计快照（内存 + 磁盘持久化）。"""
    snapshot = {
        "total": total,
        "cached": cached,
        "uncached": total - cached,
        "failed": failed,
        "failed_files": failed_files or [],
        "last_finish_time": time.time(),
    }
    with _cache_stats_lock:
        _cache_stats.update(snapshot)
    try:
        _CACHE_STATS_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
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
        self._thread.start()
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
            # 缓存任务可能新增/删除图片，让随机幻灯片索引失效，下次请求重建
            with _all_images_lock:
                _all_images_cache.clear()
            invalidate_folder_stats()
            self._set(running=False)
            self._stop.clear()

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
            for name in names:
                if self._stop.is_set():
                    break
                if Path(name).suffix.lower() not in MEDIA_EXTS:
                    continue
                if is_cover_file(name, Path(root)):
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
                # 视频以本地 Emby 封面为准判断新鲜度，海报更新后缓存任务会重新生成
                freshness_src = thumb_source(full) if full.suffix.lower() in VIDEO_EXT else full
                if is_cache_fresh(freshness_src, get_thumb_cache_path(str(rel))):
                    cached_count += 1
                    continue
                files.append((full, str(rel)))
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
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(daily_cache_job, "cron", hour=3, minute=0, id="daily_cache")
    scheduler.start()
    print("[SCHEDULER] 缓存增量任务已调度：每天 03:00（Asia/Shanghai）")
    _folder_watcher_stop.clear()
    threading.Thread(target=_folder_watcher_loop, daemon=True, name="folder-watcher").start()
    print(f"[FOLDER] 目录变化后台校验已启动：每 {_FOLDER_STATS_CHECK_SEC} 秒")
    yield
    _folder_watcher_stop.set()
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="/frontend/dist/assets"), name="assets")

# ========== 登录登出接口 ==========
@app.post("/api/login")
def login(form: LoginForm, resp: Response):
    reload_users()
    user = next((u for u in users if u.username == form.username), None)
    if not user:
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
    reload_users()
    u = next((x for x in users if x.username == user.username), None)
    if not u:
        raise HTTPException(404, "用户不存在")
    if not bcrypt.checkpw(form.old_password.encode(), u.password_hash.encode()):
        raise HTTPException(400, "原密码错误")
    new_hash = bcrypt.hashpw(form.new_password.encode(), bcrypt.gensalt()).decode()
    u.password_hash = new_hash
    save_users(users)
    add_log(user.username, "change_password", "修改本人密码")
    return {"code":0, "msg":"密码修改成功"}

## 管理员获取全部用户
@app.get("/api/admin/users")
async def admin_get_all_users(_admin: UserItem = Depends(require_admin)):
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
async def admin_get_dir_options(_admin: UserItem = Depends(require_admin)):
    dir_options = scan_media_root_dirs()
    return {"code":0, "options": dir_options}

## 管理员重命名用户名
@app.post("/api/admin/user-rename")
async def admin_rename_user(form: UserRenameForm, _admin: UserItem = Depends(require_admin)):
    reload_users()
    old = form.old_username.strip()
    new = form.new_username.strip()
    if not old or not new:
        raise HTTPException(400, "用户名不能为空")
    if old == new:
        return {"code":0, "msg":"未变更"}
    if next((u for u in users if u.username == new), None) is not None:
        raise HTTPException(400, "新用户名已存在")
    u_target = next((u for u in users if u.username == old), None)
    if u_target is None:
        raise HTTPException(404, "原用户不存在")
    # 更新内存会话中该用户的session映射
    with _session_lock:
        for sid, (uname, expire_ts) in list(sessions.items()):
            if uname == old:
                sessions[sid] = (new, expire_ts)
    u_target.username = new
    save_users(users)
    add_log(_admin.username, "user_rename", f"重命名用户 {old} → {new}")
    return {"code":0, "msg":"用户名修改成功"}

## 管理员新增/编辑用户（支持设置is_admin管理员标记）
@app.post("/api/admin/user-save")
def admin_save_user(form: AdminUserForm, _admin: UserItem = Depends(require_admin)):
    reload_users()
    exist = next((u for u in users if u.username == form.username), None)
    if exist is not None:
        # 编辑已有用户
        if form.password is not None and form.password.strip()!="":
            exist.password_hash = bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode()
        exist.allow_dirs = form.allow_dirs
        exist.is_admin = form.is_admin
    else:
        # 新增用户
        if not form.password or form.password.strip()=="":
            raise HTTPException(400, "新增用户必须填写密码")
        new_u = UserItem(
            username=form.username,
            password_hash=bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode(),
            allow_dirs=form.allow_dirs,
            is_admin=form.is_admin
        )
        users.append(new_u)
    # 校验：至少保留一个管理员账号；失败时从磁盘回滚，避免内存留下半写入状态
    try:
        check_at_least_one_admin(users)
    except HTTPException:
        reload_users()
        raise
    save_users(users)
    add_log(_admin.username, "user_save", f"{'编辑' if exist is not None else '新增'}用户 {form.username}")
    return {"code":0,"msg":"保存成功"}

## 管理员删除用户【修复：global放到函数第一行】
@app.delete("/api/admin/user/{username}")
async def admin_del_user(username: str, _admin: UserItem = Depends(require_admin)):
    global users
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
    # 清理该用户全部session
    with _session_lock:
        to_del = [k for k, (uname, _exp) in list(sessions.items()) if uname == username]
        for k in to_del:
            sessions.pop(k, None)
    save_users(users)
    add_log(_admin.username, "user_delete", f"删除用户 {username}")
    return {"code":0,"msg":"已删除"}

# ========== 随机幻灯片：全库图片索引（按用户允许目录过滤） ==========
_ALL_IMAGES_TTL = 300  # 索引缓存有效期（秒）
_all_images_cache: Dict[tuple, tuple] = {}  # allow_dirs -> (构建时间, 相对路径列表)
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


def _walk_needed(path: Path, allow_dirs: tuple) -> bool:
    """子目录值得继续遍历：它在允许目录内，或它是允许目录的祖先。"""
    for allow_p in allow_dirs:
        if _is_under(path, allow_p) or _is_under(allow_p, path):
            return True
    return False


def _collect_all_images(allow_dirs: tuple) -> List[str]:
    """递归收集允许目录内全部图片的相对路径；跳过 cover，不做 stat 以保证速度。"""
    images = []
    # 允许根目录时无需剪枝，避免对每个目录做多余的相对路径判断
    skip_prune = any(p == REAL_BASE for p in allow_dirs)
    for root, dirs, names in os.walk(REAL_BASE):
        if not skip_prune:
            root_path = Path(root)
            dirs[:] = [d for d in dirs if _walk_needed(root_path / d, allow_dirs)]
        for name in names:
            if Path(name).suffix.lower() not in IMAGE_EXT or is_cover_file(name, Path(root)):
                continue
            full = Path(root) / name
            if not any(_is_under(full, allow_p) for allow_p in allow_dirs):
                continue
            try:
                images.append(str(full.relative_to(REAL_BASE)).replace(os.sep, "/"))
            except ValueError:
                continue
    return images


def get_all_images(user: UserItem) -> List[str]:
    """按用户允许目录缓存全库图片索引，避免每次随机播放都遍历整个媒体库。"""
    key = tuple(sorted(user.allow_dirs))
    now = time.time()
    with _all_images_lock:
        cached = _all_images_cache.get(key)
        if cached is not None and now - cached[0] < _ALL_IMAGES_TTL:
            return cached[1]
    # 全库扫描可能耗时数秒，放到锁外，避免其它请求排队等锁
    images = _collect_all_images(_resolved_allow_dirs(user.allow_dirs))
    with _all_images_lock:
        _all_images_cache[key] = (time.time(), images)
    return images


@app.get("/api/random-images")
def api_random_images(limit: int = 1000, user: UserItem = Depends(get_current_user)):
    """从整个媒体库随机抽取图片（按用户允许目录过滤），供首页随机幻灯片使用。"""
    limit = max(1, min(limit, RANDOM_IMAGES_LIMIT_MAX))
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
_folder_watcher_stop = threading.Event()


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
    if not snap:
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
    # 第二层保护：挂载点正常、但中途掉线或大范围子目录读不到时仍然拦住
    total_dirs = len(snap.get("mtimes", {}))
    if unreadable > max(5, total_dirs // 5) or len(removed) > max(10, total_dirs // 2):
        print("[FOLDER] 子目录读取异常或大量目录消失，跳过本次校验")
        return 0
    if not changed and not removed:
        return 0
    roots = _topmost_paths(changed)
    removed_roots = [k for k in _topmost_paths(removed)
                     if not any(k == r or k.startswith(r + os.sep) for r in roots)]
    if not roots and not removed_roots:
        return 0
    _refresh_folder_subtrees([Path(k) for k in roots], removed_roots)
    return len(roots) + len(removed_roots)


def _folder_watcher_loop():
    """空闲时自动暂停，有人访问才按周期校验，避免没人看也一直打扰 NAS。"""
    while not _folder_watcher_stop.wait(_FOLDER_STATS_CHECK_SEC):
        try:
            if time.time() - _last_list_activity > _FOLDER_STATS_IDLE_SEC:
                continue
            n = _verify_folder_stats()
            if n:
                print(f"[FOLDER] 后台检测到 {n} 处目录变化，已增量刷新角标快照")
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
    global _last_list_activity
    _last_list_activity = time.time()
    work_path = check_dir_allowed(user, dir)
    if not work_path.exists() or not work_path.is_dir():
        return {"list": [], "breadcrumb": []}

    # 面包屑直接计算（开销小，不缓存）
    breadcrumb = []
    parts = Path(dir).parts
    for i in range(len(parts)):
        p = "/".join(parts[:i+1])
        breadcrumb.append({"name": parts[i], "path": p})

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
@app.get("/api/thumb")
def api_thumb(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404)
    suf = fp.suffix.lower()
    if suf in MEDIA_EXTS:
        rel = str(fp.relative_to(REAL_BASE)).replace(os.sep, "/")
        cache_path = ensure_thumb(fp, rel)
        if cache_path is not None and cache_path.exists():
            return FileResponse(cache_path)
    # 视频封面生成失败时不回退原文件：<img> 无法渲染视频，
    # 回退只会把几十 MB 原片白白传给浏览器且没有任何显示效果
    if suf in VIDEO_EXT:
        raise HTTPException(404)
    # 图片生成失败仍回退原图，至少能看到内容
    return FileResponse(fp)

# ========== 缓存统计接口 ==========
@app.get("/api/cache-stats")
def cache_stats(user: UserItem = Depends(get_current_user)):
    with _cache_stats_lock:
        stats = dict(_cache_stats)
    return {
        "code": 0,
        "total": stats["total"],
        "cached": stats["cached"],
        "uncached": stats["uncached"],
        "failed": stats.get("failed", 0),
        "failed_files": stats.get("failed_files", []),
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
    return cache_task.snapshot()

@app.get("/api/cache-run")
async def cache_run(user: UserItem = Depends(get_current_user)):
    if cache_task.start(operator=user.username):
        add_log(user.username, "cache_run", "手动触发预生成缓存")
        return {"code": 0, "msg": "任务已启动"}
    return {"code": 1, "msg": "已有任务在运行"}

@app.get("/api/cache-stop")
async def cache_stop(user: UserItem = Depends(get_current_user)):
    cache_task.stop()
    add_log(user.username, "cache_stop", "取消缓存任务")
    return {"code": 0, "msg": "停止指令已发送"}

# ========== 设置持久化接口 ==========
@app.get("/api/settings")
async def api_get_settings(user: UserItem = Depends(get_current_user)):
    s = load_settings()
    return {
        "code": 0,
        "settings": {
            "slide_delay": s.get("slide_delay", 5),
            "slide_loop": s.get("slide_loop", True),
        },
    }

@app.post("/api/settings")
async def api_save_settings(form: SettingsForm, user: UserItem = Depends(get_current_user)):
    s = load_settings()
    s["slide_delay"] = form.slide_delay
    s["slide_loop"] = form.slide_loop
    save_settings(s)
    return {"code": 0, "msg": "ok"}

@app.get("/")
async def index():
    return FileResponse("/frontend/dist/index.html")

if __name__ == "__main__":
    # 在项目根目录执行：python -m backend.main
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000)
