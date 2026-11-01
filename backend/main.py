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
from PIL import Image

# ========== 配置读取 ==========
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/cache"))
CONFIG_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

USER_CONFIG_PATH = CONFIG_DIR / "users.json"
SESSION_EXPIRE_SEC = 86400

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi"}
COVER_NAMES = {"cover.jpg", "cover.png", "cover.webp"}

# 数据模型
class LoginForm(BaseModel):
    username: str
    password: str

class UserItem(BaseModel):
    username: str
    password_hash: str
    allow_dirs: List[str]

class ChangePwdForm(BaseModel):
    old_password: str
    new_password: str

class AdminUserForm(BaseModel):
    username: str
    password: Optional[str] = Field(None, description="新增必填；编辑留空则不修改密码")
    allow_dirs: List[str]

# 内存会话存储
sessions: Dict[str, str] = {}

def load_users() -> List[UserItem]:
    if not USER_CONFIG_PATH.exists():
        default_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        init_data = [
            {
                "username": "admin",
                "password_hash": default_hash,
                "allow_dirs": ["/"]
            }
        ]
        USER_CONFIG_PATH.write_text(json.dumps(init_data, ensure_ascii=False, indent=2))
    raw = json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    return [UserItem(**x) for x in raw]

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
    if user.username != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

# 路径安全校验：防止越权、路径穿越
def check_path_allowed(user: UserItem, target_dir: str) -> Path:
    target_dir = target_dir.strip()
    real_base = Path(MEDIA_ROOT).resolve()
    user_allowed_real = []
    for ad in user.allow_dirs:
        ap = (real_base / ad.lstrip("/")).resolve()
        user_allowed_real.append(ap)

    req_path = (real_base / target_dir.lstrip("/")).resolve()
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

# ========== APP初始化 ==========
app = FastAPI()
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
        "is_admin": user.username == "admin",
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
            "allow_dirs": u.allow_dirs
        })
    return {"code":0, "list": out}

## 管理员新增/编辑用户
@app.post("/api/admin/user-save")
async def admin_save_user(form: AdminUserForm, _admin: UserItem = Depends(require_admin)):
    reload_users()
    exist = next((u for u in users if u.username == form.username), None)
    # admin用户名禁止修改删除
    if form.username.lower() == "admin":
        if form.password is not None:
            u_admin = next(x for x in users if x.username == "admin")
            u_admin.password_hash = bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode()
        u_admin.allow_dirs = form.allow_dirs
        save_users(users)
        return {"code":0,"msg":"管理员账号已更新"}

    if exist is not None:
        # 编辑已有用户
        if form.password is not None and form.password.strip()!="":
            exist.password_hash = bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode()
        exist.allow_dirs = form.allow_dirs
    else:
        # 新增用户
        if not form.password or form.password.strip()=="":
            raise HTTPException(400, "新增用户必须填写密码")
        new_u = UserItem(
            username=form.username,
            password_hash=bcrypt.hashpw(form.password.encode(), bcrypt.gensalt()).decode(),
            allow_dirs=form.allow_dirs
        )
        users.append(new_u)
    save_users(users)
    return {"code":0,"msg":"保存成功"}

## 管理员删除用户
@app.delete("/api/admin/user/{username}")
async def admin_del_user(username: str, _admin: UserItem = Depends(require_admin)):
    if username == "admin":
        raise HTTPException(400, "禁止删除admin管理员账号")
    reload_users()
    global users
    users = [u for u in users if u.username != username]
    save_users(users)
    return {"code":0,"msg":"已删除"}

# ========== 媒体列表接口 ==========
@app.get("/api/list")
async def api_list(dir: str = "", user: UserItem = Depends(get_current_user)):
    work_path = check_path_allowed(user, dir)
    if not work_path.exists() or not work_path.is_dir():
        return {"list": [], "breadcrumb": []}

    def get_folder_cover(folder_abs: Path, base_abs: Path):
        cover_candidate = None
        first_img = None
        try:
            for name in os.listdir(folder_abs):
                full = folder_abs / name
                if not os.path.isfile(full):
                    continue
                lower_name = name.lower()
                if lower_name in COVER_NAMES:
                    rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                    cover_candidate = "/" + rel
                    break
                ext = os.path.splitext(lower_name)[1]
                if ext in IMAGE_EXT and first_img is None:
                    rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                    first_img = "/" + rel
            return cover_candidate if cover_candidate is not None else first_img
        except Exception:
            pass
        return None

    items = []
    breadcrumb = []
    parts = Path(dir).parts
    for i in range(len(parts)):
        p = "/".join(parts[:i+1])
        breadcrumb.append({"name": parts[i], "path": p})

    entries = sorted(work_path.iterdir(), key=lambda x:x.name.lower())
    base_abs = Path(MEDIA_ROOT).resolve()
    for entry in entries:
        entry_name_low = entry.name.lower()
        if entry_name_low in COVER_NAMES:
            continue
        try:
            rel = entry.relative_to(base_abs)
            rel_str = str(rel).replace(os.sep, "/")
        except Exception:
            continue
        if entry.is_dir():
            cover = get_folder_cover(entry, base_abs)
            items.append({
                "id": rel_str,
                "name": entry.name,
                "type": "folder",
                "path": rel_str,
                "cover_path": cover
            })
        else:
            suf = entry.suffix.lower()
            if suf in IMAGE_EXT:
                items.append({"id":rel_str,"name":entry.name,"type":"image","path":rel_str})
            elif suf in VIDEO_EXT:
                items.append({"id":rel_str,"name":entry.name,"type":"video","path":rel_str})
    return {"list": items, "breadcrumb": breadcrumb}

# ========== 原图接口 ==========
@app.get("/api/src")
async def api_src(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists():
        raise HTTPException(404)
    return FileResponse(fp)

# ========== 缩略图占位，你原有缩略逻辑放回这里 ==========
@app.get("/api/thumb")
async def api_thumb(path: str, user: UserItem = Depends(get_current_user)):
    fp = check_path_allowed(user, path)
    if not fp.exists():
        raise HTTPException(404)
    return FileResponse(fp)

# ========== 缓存任务接口 ==========
@app.get("/api/cache-status")
async def cache_status(user: UserItem = Depends(get_current_user)):
    return {"running": False, "percent":0, "message":"", "processed":0, "total":0}

@app.get("/api/cache-run")
async def cache_run(user: UserItem = Depends(get_current_user)):
    return {"code":0, "msg":"ok"}

@app.get("/api/cache-stop")
async def cache_stop(user: UserItem = Depends(get_current_user)):
    return {"code":0, "msg":"ok"}

@app.get("/")
async def index():
    return FileResponse("/frontend/dist/index.html")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
