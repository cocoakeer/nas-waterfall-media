import os
import json
import bcrypt
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn
import threading
import time
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from .cover import (
    IMAGE_EXT,
    VIDEO_EXT,
    is_cover_file,
    ensure_thumb,
    get_thumb_cache_path,
    is_cache_fresh,
    cleanup_orphan_thumbs,
    get_video_duration,
)
from .config import load_settings, save_settings

# ========== 配置读取 适配compose CONFIG_PATH / CACHE_PATH ==========
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
REAL_BASE = Path(MEDIA_ROOT).resolve()  # 预计算，避免每个请求重复 resolve
CONFIG_DIR = Path(os.getenv("CONFIG_PATH", "/app/config"))
CACHE_DIR = Path(os.getenv("CACHE_PATH", "/app/cache"))
# 创建目录并设置权限，打印路径用于排错
CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o775)
CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o775)
USER_CONFIG_PATH = CONFIG_DIR / "users.json"
print(f"[CONFIG] 用户配置文件路径: {USER_CONFIG_PATH}")

SESSION_EXPIRE_SEC = 86400

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
    slide_delay: int = 5
    slide_loop: bool = True

class AdminUserForm(BaseModel):
    username: str
    password: Optional[str] = Field(None, description="新增必填；编辑留空则不修改密码")
    allow_dirs: List[str]
    is_admin: bool

class UserRenameForm(BaseModel):
    old_username: str
    new_username: str

# 内存会话存储
sessions: Dict[str, str] = {}

def load_users() -> List[UserItem]:
    if not USER_CONFIG_PATH.exists():
        default_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        init_data = [
            {
                "username": "admin",
                "password_hash": default_hash,
                "allow_dirs": ["/"],
                "is_admin": True
            }
        ]
        USER_CONFIG_PATH.write_text(json.dumps(init_data, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_list = json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    out = []
    # 兼容旧配置文件，旧数据缺少is_admin字段自动补为False，原admin用户名自动升级为管理员
    for item in raw_list:
        if "is_admin" not in item:
            item["is_admin"] = (item.get("username") == "admin")
        out.append(UserItem(**item))
    return out

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
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    uname = sessions[session_id]
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
def check_path_allowed(user: UserItem, target_dir: str) -> Path:
    target_dir = target_dir.strip()
    user_allowed_real = []
    for ad in user.allow_dirs:
        ap = (REAL_BASE / ad.lstrip("/")).resolve()
        user_allowed_real.append(ap)

    req_path = (REAL_BASE / target_dir.lstrip("/")).resolve()
    ok = False
    for allow_p in user_allowed_real:
        try:
            req_path.relative_to(allow_p)
            ok = True
            break
        except ValueError:
            continue
    if not ok:
        raise HTTPException(status_code=403, detail="无权访问该目录")
    return req_path

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


def record_cache_stats(total: int, cached: int):
    """缓存任务完成后记录统计快照（内存 + 磁盘持久化）。"""
    snapshot = {
        "total": total,
        "cached": cached,
        "uncached": total - cached,
        "last_finish_time": time.time(),
    }
    with _cache_stats_lock:
        _cache_stats.update(snapshot)
    try:
        _CACHE_STATS_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


load_cache_stats()  # 启动时加载上次快照


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
        self.total = 0
        self.current = ""

    def snapshot(self):
        with self._lock:
            return {
                "running": self.running,
                "percent": self.percent,
                "message": self.message,
                "processed": self.processed,
                "total": self.total,
                "current": self.current,
            }

    def _set(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.percent = 0
            self.message = ""
            self.processed = 0
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
            self._set(running=False)
            self._stop.clear()

    def _build(self):
        base = Path(self._media_root).resolve()
        # 1. 遍历收集：统计全部媒体文件 + 需要处理的（增量跳过新鲜的）
        all_total = 0
        cached_count = 0
        files = []
        for root, _dirs, names in os.walk(base):
            if self._stop.is_set():
                break
            for name in names:
                if Path(name).suffix.lower() not in (IMAGE_EXT | VIDEO_EXT):
                    continue
                full = Path(root) / name
                try:
                    rel = full.relative_to(base)
                except ValueError:
                    continue
                all_total += 1
                # 增量判断：缓存存在且不旧于源文件则跳过
                if is_cache_fresh(full, get_thumb_cache_path(str(rel))):
                    cached_count += 1
                    continue
                files.append((full, str(rel)))
        total = len(files)
        self._set(total=total)
        if total == 0:
            self._set(percent=100, message="缓存已是最新，无增量文件")
            record_cache_stats(all_total, cached_count)
            return
        # 2. 逐个生成缩略图/封面
        processed = 0
        failed = 0
        for full, rel in files:
            if self._stop.is_set():
                self._set(message="已取消", percent=int(processed * 100 / total))
                record_cache_stats(all_total, cached_count + (processed - failed))
                return
            result = ensure_thumb(full, rel)
            if result is None:
                failed += 1
            # 视频顺便探测并缓存时长，供列表接口直接读取
            if full.suffix.lower() in VIDEO_EXT:
                get_video_duration(str(full), fetch=True)
            processed += 1
            self._set(processed=processed, percent=int(processed * 100 / total), current=rel)
        self._set(percent=100, message="全部完成")
        record_cache_stats(all_total, cached_count + (processed - failed))


# ========== 缓存任务实例 ==========
cache_task = CacheTask(MEDIA_ROOT)


# ========== 每日缓存任务 ==========
def daily_cache_job():
    """每天凌晨 3 点：清理孤儿缓存 + 增量生成缓存。"""
    try:
        cleaned = cleanup_orphan_thumbs(REAL_BASE)
        print(f"[CACHE-JOB] 清理孤儿缓存 {cleaned} 个")
    except Exception as exc:
        print(f"[CACHE-JOB] 清理孤儿缓存失败：{exc}")
    if cache_task.start():
        print("[CACHE-JOB] 增量生成已启动")
    else:
        print("[CACHE-JOB] 已有任务在运行，跳过本次增量")


# ========== APP初始化 ==========
@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(daily_cache_job, "cron", hour=3, minute=0, id="daily_cache")
    scheduler.start()
    print("[SCHEDULER] 缓存增量任务已调度：每天 03:00（Asia/Shanghai）")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="/frontend/dist/assets"), name="assets")

# ========== 登录登出接口 ==========
@app.post("/api/login")
async def login(form: LoginForm, resp: Response):
    reload_users()
    user = next((u for u in users if u.username == form.username), None)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if not bcrypt.checkpw(form.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    sid = str(uuid.uuid4())
    sessions[sid] = user.username
    resp.set_cookie(key="session_id", value=sid, max_age=SESSION_EXPIRE_SEC, httponly=True)
    return {"code": 0, "msg": "ok"}

@app.post("/api/logout")
async def logout(resp: Response, user: UserItem = Depends(get_current_user)):
    to_del = [k for k, v in sessions.items() if v == user.username]
    for k in to_del:
        del sessions[k]
    resp.delete_cookie("session_id")
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
async def api_change_my_pwd(form: ChangePwdForm, user: UserItem = Depends(get_current_user)):
    reload_users()
    u = next((x for x in users if x.username == user.username), None)
    if not u:
        raise HTTPException(404, "用户不存在")
    if not bcrypt.checkpw(form.old_password.encode(), u.password_hash.encode()):
        raise HTTPException(400, "原密码错误")
    new_hash = bcrypt.hashpw(form.new_password.encode(), bcrypt.gensalt()).decode()
    u.password_hash = new_hash
    save_users(users)
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
    for sid, uname in list(sessions.items()):
        if uname == old:
            sessions[sid] = new
    u_target.username = new
    save_users(users)
    return {"code":0, "msg":"用户名修改成功"}

## 管理员新增/编辑用户（支持设置is_admin管理员标记）
@app.post("/api/admin/user-save")
async def admin_save_user(form: AdminUserForm, _admin: UserItem = Depends(require_admin)):
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
    # 校验：至少保留一个管理员账号
    check_at_least_one_admin(users)
    save_users(users)
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
    # 删除之后校验至少还有一个管理员
    check_at_least_one_admin(users)
    # 清理该用户全部session
    to_del = [k for k, v in sessions.items() if v == username]
    for k in to_del:
        del sessions[k]
    save_users(users)
    return {"code":0,"msg":"已删除"}

# ========== 媒体列表接口 ==========
# 目录列表缓存：key=解析后目录路径, value=(目录mtime, 缓存时间戳, items)
_dir_cache: Dict[str, tuple] = {}
_dir_cache_lock = threading.Lock()
_DIR_CACHE_MAX = 500
_DIR_CACHE_TTL = 30  # 缓存有效期（秒），兼顾递归计数对深层变化的感知

@app.get("/api/list")
def api_list(dir: str = "", user: UserItem = Depends(get_current_user)):
    work_path = check_path_allowed(user, dir)
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
        mtime = work_path.stat().st_mtime
    except OSError:
        mtime = 0
    key = str(work_path)
    with _dir_cache_lock:
        cached = _dir_cache.get(key)
    if cached is not None and cached[0] == mtime and (time.time() - cached[1]) < _DIR_CACHE_TTL:
        return {"list": cached[2], "breadcrumb": breadcrumb}

    def get_folder_info(folder_abs: Path):
        # 找封面（直接子项）+ 递归统计图片/视频总数
        cover_candidate = None
        first_img = None
        try:
            with os.scandir(folder_abs) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    lower_name = entry.name.lower()
                    ext = os.path.splitext(lower_name)[1]
                    if ext not in IMAGE_EXT and ext not in VIDEO_EXT:
                        continue
                    if is_cover_file(entry.name):
                        rel = os.path.relpath(entry.path, REAL_BASE).replace(os.sep, "/")
                        cover_candidate = "/" + rel
                    elif ext in IMAGE_EXT and first_img is None:
                        rel = os.path.relpath(entry.path, REAL_BASE).replace(os.sep, "/")
                        first_img = "/" + rel
            cover = cover_candidate if cover_candidate is not None else first_img
            # 递归统计该文件夹下（含所有子文件夹）的图片+视频总数
            count = 0
            for _root, _dirs, names in os.walk(folder_abs):
                for name in names:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in IMAGE_EXT or ext in VIDEO_EXT:
                        count += 1
            return cover, count
        except Exception:
            pass
        return None, 0

    items = []
    entries = sorted(work_path.iterdir(), key=lambda x: x.name.lower())
    for entry in entries:
        if is_cover_file(entry.name):
            continue
        try:
            rel = entry.relative_to(REAL_BASE)
            rel_str = str(rel).replace(os.sep, "/")
        except Exception:
            continue
        try:
            st = entry.stat()
            size = st.st_size
            mtime = st.st_mtime
        except OSError:
            size = None
            mtime = None
        if entry.is_dir():
            cover, count = get_folder_info(entry)
            items.append({
                "id": rel_str,
                "name": entry.name,
                "type": "folder",
                "path": rel_str,
                "cover_path": cover,
                "count": count,
                "mtime": mtime,
            })
        else:
            suf = entry.suffix.lower()
            if suf in IMAGE_EXT:
                items.append({
                    "id": rel_str, "name": entry.name, "type": "image",
                    "path": rel_str, "size": size, "mtime": mtime,
                })
            elif suf in VIDEO_EXT:
                duration = get_video_duration(str(entry), fetch=False)
                items.append({
                    "id": rel_str, "name": entry.name, "type": "video",
                    "path": rel_str, "size": size, "mtime": mtime, "duration": duration,
                })

    with _dir_cache_lock:
        if len(_dir_cache) >= _DIR_CACHE_MAX:
            _dir_cache.clear()
        _dir_cache[key] = (mtime, time.time(), items)
    return {"list": items, "breadcrumb": breadcrumb}

# ========== 原图接口 ==========
@app.get("/api/src")
def api_src(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists():
        raise HTTPException(404)
    return FileResponse(fp)

# ========== 缩略图接口（图片 Pillow / 视频 ffmpeg，结果落盘缓存） ==========
@app.get("/api/thumb")
def api_thumb(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404)
    suf = fp.suffix.lower()
    if suf in IMAGE_EXT or suf in VIDEO_EXT:
        rel = str(fp.relative_to(REAL_BASE)).replace(os.sep, "/")
        cache_path = ensure_thumb(fp, rel)
        if cache_path is not None and cache_path.exists():
            return FileResponse(cache_path)
    # 生成失败或未知类型，回退原图
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
        "last_finish_time": stats["last_finish_time"],
    }


# ========== 缓存任务接口 ==========
@app.get("/api/cache-status")
async def cache_status(user: UserItem = Depends(get_current_user)):
    return cache_task.snapshot()

@app.get("/api/cache-run")
async def cache_run(user: UserItem = Depends(get_current_user)):
    if cache_task.start():
        return {"code": 0, "msg": "任务已启动"}
    return {"code": 1, "msg": "已有任务在运行"}

@app.get("/api/cache-stop")
async def cache_stop(user: UserItem = Depends(get_current_user)):
    cache_task.stop()
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
