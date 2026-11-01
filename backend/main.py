import os
import urllib.parse
import subprocess
import threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from apscheduler.schedulers.background import BackgroundScheduler

Image.MAX_IMAGE_PIXELS = None

app = FastAPI(title="NAS Waterfall Media")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
CACHE_DIR = os.getenv("CACHE_DIR", "/cache")
CONFIG_DIR = os.getenv("CONFIG_DIR", "/config")

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi"}
COVER_NAMES = {"cover.jpg", "cover.png", "cover.webp"}

# ========== 缓存任务状态 ==========
cache_task_lock = threading.Lock()
cache_task_state = {
    "running": False,
    "stop_request": False,
    "processed": 0,
    "total": 0,
    "message": ""
}

app.mount("/assets", StaticFiles(directory="/frontend/dist/assets"), name="assets")

@app.get("/")
async def index():
    return FileResponse("/frontend/dist/index.html")


def get_folder_cover(folder_abs: str, base_abs: str):
    """优先找cover文件；没有cover取目录内第一张图片"""
    cover_candidate = None
    first_img = None
    try:
        for name in os.listdir(folder_abs):
            full = os.path.join(folder_abs, name)
            if not os.path.isfile(full):
                continue
            lower_name = name.lower()
            # 优先匹配cover
            if lower_name in COVER_NAMES:
                rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                cover_candidate = "/" + rel
                break
            # 记录第一张图片备用
            ext = os.path.splitext(lower_name)[1]
            if ext in IMAGE_EXT and first_img is None:
                rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                first_img = "/" + rel
        # 有cover就用cover，没有就第一张图
        return cover_candidate if cover_candidate is not None else first_img
    except Exception:
        pass
    return None


@app.get("/api/list")
async def list_dir(dir: str = ""):
    try:
        dir = urllib.parse.unquote(dir)
        base = os.path.abspath(MEDIA_ROOT)
        target = os.path.abspath(os.path.join(base, dir.lstrip("/")))

        if not target.startswith(base):
            raise HTTPException(status_code=403, detail="Access denied")
        if not os.path.isdir(target):
            return {"list": [], "breadcrumb": []}

        breadcrumb = []
        if dir.strip() != "":
            parts = dir.strip("/").split("/")
            cur = ""
            for p in parts:
                cur += "/" + p
                breadcrumb.append({"name": p, "path": cur})

        items = []
        entries = sorted(os.listdir(target))
        for name in entries:
            # 【重点】过滤cover文件，不在列表展示
            if name.lower() in COVER_NAMES:
                continue
            full_path = os.path.join(target, name)
            rel_path = os.path.relpath(full_path, base).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if os.path.isdir(full_path):
                cover = get_folder_cover(full_path, base)
                items.append({
                    "id": rel_path,
                    "name": name,
                    "path": "/" + rel_path,
                    "type": "folder",
                    "cover_path": cover
                })
            elif ext in IMAGE_EXT:
                items.append({
                    "id": rel_path,
                    "name": name,
                    "path": "/" + rel_path,
                    "type": "image"
                })
            elif ext in VIDEO_EXT:
                items.append({
                    "id": rel_path,
                    "name": name,
                    "path": "/" + rel_path,
                    "type": "video"
                })
        return {"list": items, "breadcrumb": breadcrumb}
    except Exception as e:
        return {"list": [], "breadcrumb": []}


def generate_thumb(file_abs: str, cache_out: str):
    ext = os.path.splitext(file_abs)[1].lower()
    try:
        if ext in IMAGE_EXT:
            with Image.open(file_abs) as im:
                im.thumbnail((400, 400))
                im.save(cache_out, "JPEG")
            return True
        elif ext in VIDEO_EXT:
            cmd = [
                "ffmpeg", "-y", "-ss", "0.5",
                "-i", file_abs,
                "-vframes", "1",
                "-vf", "scale=400:-1",
                cache_out
            ]
            subprocess.run(cmd, capture_output=True, timeout=15)
            return os.path.exists(cache_out)
    except Exception:
        pass
    return False


def background_cache_work():
    global cache_task_state
    base = os.path.abspath(MEDIA_ROOT)
    media_files = []
    print("[PreCache] background task start")
    try:
        for root, _, files in os.walk(base):
            with cache_task_lock:
                if cache_task_state["stop_request"]:
                    raise Exception("task stop requested")
            for fname in files:
                # 缓存任务也跳过cover
                if fname.lower() in COVER_NAMES:
                    continue
                full_abs = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXT or ext in VIDEO_EXT:
                    media_files.append(full_abs)

        with cache_task_lock:
            cache_task_state["total"] = len(media_files)
            cache_task_state["processed"] = 0
            cache_task_state["message"] = "正在生成缩略图"

        for full_abs in media_files:
            with cache_task_lock:
                if cache_task_state["stop_request"]:
                    raise Exception("task stop requested")
            rel = os.path.relpath(full_abs, base).replace(os.sep, "/")
            cache_key = rel.replace("/", "_") + ".jpg"
            cache_file = os.path.join(CACHE_DIR, cache_key)
            if not os.path.exists(cache_file):
                generate_thumb(full_abs, cache_file)
            with cache_task_lock:
                cache_task_state["processed"] += 1

        with cache_task_lock:
            cache_task_state["message"] = "正在清理无效缓存"
        clean_orphan_cache()

        with cache_task_lock:
            cache_task_state["message"] = "任务全部完成"
        print("[PreCache] background task finished")
    except Exception as e:
        print("[PreCache] task stopped/error:", str(e))
        with cache_task_lock:
            cache_task_state["message"] = f"任务已停止：{str(e)}"
    finally:
        with cache_task_lock:
            cache_task_state["running"] = False
            cache_task_state["stop_request"] = False


def clean_orphan_cache():
    base = os.path.abspath(MEDIA_ROOT)
    if not os.path.isdir(CACHE_DIR):
        return
    for fname in os.listdir(CACHE_DIR):
        if not fname.endswith(".jpg"):
            continue
        raw_rel = fname[:-4].replace("_", "/")
        origin_file = os.path.join(base, raw_rel)
        if not os.path.exists(origin_file):
            try:
                os.unlink(os.path.join(CACHE_DIR, fname))
            except Exception:
                pass


@app.get("/api/cache-run", response_class=JSONResponse)
async def api_cache_run():
    global cache_task_state
    with cache_task_lock:
        if cache_task_state["running"]:
            return {"code": -1, "msg": "已有任务正在运行，请等待或取消"}
        cache_task_state["running"] = True
        cache_task_state["stop_request"] = False
        cache_task_state["processed"] = 0
        cache_task_state["total"] = 0
        cache_task_state["message"] = "开始扫描媒体文件"
    t = threading.Thread(target=background_cache_work, daemon=True)
    t.start()
    return {"code": 0, "msg": "任务已提交后台运行"}


@app.get("/api/cache-stop", response_class=JSONResponse)
async def api_cache_stop():
    global cache_task_state
    with cache_task_lock:
        if not cache_task_state["running"]:
            return {"code": -1, "msg": "没有正在运行的任务"}
        cache_task_state["stop_request"] = True
        cache_task_state["message"] = "收到停止指令，正在终止任务"
    return {"code": 0, "msg": "已发送停止信号"}


@app.get("/api/cache-status", response_class=JSONResponse)
async def api_cache_status():
    with cache_task_lock:
        st = dict(cache_task_state)
    pct = 0
    if st["total"] > 0:
        pct = round(100 * st["processed"] / st["total"], 1)
    return {
        "running": st["running"],
        "processed": st["processed"],
        "total": st["total"],
        "percent": pct,
        "message": st["message"]
    }


@app.get("/api/thumb")
async def get_thumb(path: str = ""):
    path = urllib.parse.unquote(path.lstrip("/"))
    base = os.path.abspath(MEDIA_ROOT)
    origin = os.path.abspath(os.path.join(base, path))
    if not origin.startswith(base) or not os.path.isfile(origin):
        return Response(status_code=204)
    cache_key = path.replace("/", "_") + ".jpg"
    cache_file = os.path.join(CACHE_DIR, cache_key)
    if not os.path.exists(cache_file):
        ok = generate_thumb(origin, cache_file)
        if not ok:
            return Response(status_code=204)
    return FileResponse(cache_file)


@app.get("/api/src")
async def get_src(path: str = ""):
    path = urllib.parse.unquote(path.lstrip("/"))
    base = os.path.abspath(MEDIA_ROOT)
    target = os.path.abspath(os.path.join(base, path))
    if not target.startswith(base) or not os.path.isfile(target):
        raise HTTPException(status_code=404)
    ext = os.path.splitext(target)[1].lower()
    mime = "image/jpeg"
    if ext in IMAGE_EXT:
        mime = "image/jpeg"
    elif ext in VIDEO_EXT:
        mime = "video/mp4"
    return FileResponse(target, media_type=mime)


# 定时任务
scheduler = BackgroundScheduler()
def cron_job():
    with cache_task_lock:
        if not cache_task_state["running"]:
            cache_task_state["running"] = True
            cache_task_state["stop_request"] = False
            cache_task_state["processed"] = 0
            cache_task_state["total"] = 0
            cache_task_state["message"] = "定时缓存任务开始"
    t = threading.Thread(target=background_cache_work, daemon=True)
    t.start()

scheduler.add_job(cron_job, "cron", hour=2, minute=0)
scheduler.start()

@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
