import os
import urllib.parse
import subprocess
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
COVER_NAMES = {"cover.jpg", "cover.png", "cover.webp", "Cover.jpg", "Cover.png", "Cover.webp"}

app.mount("/assets", StaticFiles(directory="/frontend/dist/assets"), name="assets")

@app.get("/")
async def index():
    return FileResponse("/frontend/dist/index.html")


def get_folder_cover(folder_abs: str, base_abs: str):
    """获取文件夹封面：优先cover.*，否则取目录第一个图片；返回相对路径，无则返回None"""
    cover_candidate = None
    media_first = None
    try:
        for name in os.listdir(folder_abs):
            full = os.path.join(folder_abs, name)
            if os.path.isfile(full):
                if name in COVER_NAMES:
                    rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                    cover_candidate = "/" + rel
                ext = os.path.splitext(name)[1].lower()
                if ext in IMAGE_EXT and media_first is None and name.lower() not in {"cover.jpg", "cover.png", "cover.webp"}:
                    rel = os.path.relpath(full, base_abs).replace(os.sep, "/")
                    media_first = "/" + rel
    except Exception:
        pass
    if cover_candidate:
        return cover_candidate
    return media_first


@app.get("/api/list")
async def list_dir(dir: str = ""):
    try:
        dir = urllib.parse.unquote(dir)
        base = os.path.abspath(MEDIA_ROOT)
        target = os.path.abspath(os.path.join(base, dir.lstrip("/")))

        if not target.startswith(base):
            raise HTTPException(status_code=403, detail="非法路径")
        if not os.path.exists(target) or not os.path.isdir(target):
            return {"list": [], "breadcrumb": []}

        breadcrumb = []
        if dir.strip() != "":
            parts = dir.strip("/").split("/")
            cur = ""
            for p in parts:
                cur += "/" + p
                breadcrumb.append({"name": p, "path": cur})

        items = []
        for name in os.listdir(target):
            if name in COVER_NAMES:
                continue
            full = os.path.join(target, name)
            rel_path = os.path.relpath(full, base).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if os.path.isdir(full):
                cover_path = get_folder_cover(full, base)
                items.append({
                    "id": rel_path,
                    "name": name,
                    "path": "/" + rel_path,
                    "type": "folder",
                    "cover_path": cover_path
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
    except Exception:
        return {"list": [], "breadcrumb": []}


def generate_thumb(file_abs: str, cache_out: str):
    """生成缩略图，图片用PIL，视频调用系统ffmpeg(subprocess)；同步函数，给定时任务&接口共用"""
    ext = os.path.splitext(file_abs)[1].lower()
    try:
        if ext in IMAGE_EXT:
            img = Image.open(file_abs)
            img.thumbnail((400, 400))
            img.save(cache_out, "JPEG")
            return True
        elif ext in VIDEO_EXT:
            cmd = [
                "ffmpeg",
                "-ss", "0.5",
                "-i", file_abs,
                "-vframes", "1",
                "-vf", "scale=400:-1",
                "-y",
                cache_out
            ]
            subprocess.run(cmd, capture_output=True, timeout=15)
            if os.path.exists(cache_out) and os.path.getsize(cache_out) > 0:
                return True
    except Exception:
        pass
    return False


def pre_cache_all_media():
    """定时任务1：预生成全部缺失的缩略图（增量，已存在缓存跳过）"""
    print("[PreCache] start pre‑generate thumbnails")
    base = os.path.abspath(MEDIA_ROOT)
    for root, _, files in os.walk(base):
        for fname in files:
            full_abs = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if not (ext in IMAGE_EXT or ext in VIDEO_EXT):
                continue
            rel = os.path.relpath(full_abs, base).replace(os.sep, "/")
            cache_key = rel.replace("/", "_")
            cache_file = os.path.join(CACHE_DIR, cache_key + ".jpg")
            if os.path.exists(cache_file):
                continue
            generate_thumb(full_abs, cache_file)
    print("[PreCache] pre‑generate finished")


def clean_orphan_cache():
    """定时任务2：清理孤儿缓存：原始文件已经被删除，但缓存还残留的文件"""
    print("[CacheClean] start clean orphan cache")
    base = os.path.abspath(MEDIA_ROOT)
    if not os.path.isdir(CACHE_DIR):
        return
    for cache_fname in os.listdir(CACHE_DIR):
        if not cache_fname.endswith(".jpg"):
            continue
        raw_key = cache_fname[:-4]
        rel_path = raw_key.replace("_", "/")
        origin_abs = os.path.join(base, rel_path.lstrip("/"))
        if not os.path.exists(origin_abs):
            orphan_path = os.path.join(CACHE_DIR, cache_fname)
            try:
                os.unlink(orphan_path)
            except Exception:
                pass
    print("[CacheClean] clean orphan cache finished")


@app.get("/api/thumb")
async def get_thumb(path: str):
    path = urllib.parse.unquote(path)
    base = os.path.abspath(MEDIA_ROOT)
    full_path = os.path.abspath(os.path.join(base, path.lstrip("/")))

    if not full_path.startswith(base):
        raise HTTPException(status_code=403, detail="非法路径")
    if not os.path.isfile(full_path):
        return Response(status_code=204)

    cache_key = path.replace("/", "_")
    cache_file = os.path.join(CACHE_DIR, cache_key + ".jpg")

    if os.path.exists(cache_file):
        return FileResponse(cache_file, media_type="image/jpeg")

    ok = generate_thumb(full_path, cache_file)
    if ok and os.path.exists(cache_file):
        return FileResponse(cache_file, media_type="image/jpeg")
    return Response(status_code=204)


@app.get("/api/src")
async def get_src(path: str):
    path = urllib.parse.unquote(path)
    base = os.path.abspath(MEDIA_ROOT)
    full_path = os.path.abspath(os.path.join(base, path.lstrip("/")))

    if not full_path.startswith(base):
        raise HTTPException(status_code=403, detail="非法路径")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = os.path.splitext(full_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo"
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return FileResponse(full_path, media_type=mime)


# 手动触发缓存任务接口
@app.get("/api/cache-run", response_class=JSONResponse)
async def api_manual_cache_run():
    """手动触发：预生成缩略 + 清理孤儿缓存，调试用"""
    try:
        pre_cache_all_media()
        clean_orphan_cache()
        return {
            "code":0,
            "msg":"执行完成：预生成缩略图 + 清理孤儿缓存已执行完毕"
        }
    except Exception as e:
        return {
            "code":-1,
            "msg":"执行异常",
            "error":str(e)
        }


# 后台定时调度：每天凌晨2点执行【预生成缩略 + 清理孤儿缓存】
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: (pre_cache_all_media(), clean_orphan_cache()), "cron", hour=2, minute=0)
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
