import os
import urllib.parse
import ffmpeg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

app = FastAPI(title="NAS Waterfall Media")

# 跨域中间件，本地调试用，容器部署无副作用
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

app.mount("/assets", StaticFiles(directory="/frontend/dist/assets"), name="assets")

@app.get("/")
async def index():
    return FileResponse("/frontend/dist/index.html")

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
            full = os.path.join(target, name)
            rel_path = os.path.relpath(full, base).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if os.path.isdir(full):
                items.append({
                    "id": rel_path,
                    "name": name,
                    "path": "/" + rel_path,
                    "type": "folder"
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


@app.get("/api/thumb")
async def get_thumb(path: str):
    path = urllib.parse.unquote(path)
    base = os.path.abspath(MEDIA_ROOT)
    full_path = os.path.abspath(os.path.join(base, path.lstrip("/")))

    if not full_path.startswith(base):
        raise HTTPException(status_code=403, detail="非法路径")
    if not os.path.isfile(full_path):
        return Response(status_code=204)

    ext = os.path.splitext(full_path)[1].lower()
    cache_key = path.replace("/", "_")
    cache_file = os.path.join(CACHE_DIR, cache_key + ".jpg")

    if os.path.exists(cache_file):
        return FileResponse(cache_file, media_type="image/jpeg")

    try:
        if ext in IMAGE_EXT:
            img = Image.open(full_path)
            img.thumbnail((400, 400))
            img.save(cache_file, "JPEG")
        elif ext in VIDEO_EXT:
            (
                ffmpeg.input(full_path, ss=0.5)
                .filter('scale', 400, -1)
                .output(cache_file, vframes=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
        return FileResponse(cache_file, media_type="image/jpeg")
    except Exception:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
