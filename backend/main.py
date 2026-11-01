import os
import json
from pathlib import Path
from urllib.parse import quote, unquote
from fastapi import FastAPI, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
import ffmpeg

app = FastAPI()

# 读取环境变量
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/media"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/cache"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
CONFIG_FILE = CONFIG_DIR / "setting.json"

CACHE_DIR.mkdir(exist_ok=True, parents=True)
CONFIG_DIR.mkdir(exist_ok=True, parents=True)

# 默认配置
DEFAULT_SETTING = {
    "slide_delay": 3,
    "loop": False
}
if not CONFIG_FILE.exists():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SETTING, f, ensure_ascii=False, indent=2)

def load_setting():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_setting(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def make_thumbnail(file_path: str, cache_base: Path, size=(400, 300)) -> str:
    fp = Path(file_path)
    key = f"{fp.stat().st_mtime}_{fp.name}"
    thumb_name = f"{hash(key)}.jpg"
    thumb_path = cache_base / thumb_name
    if thumb_path.exists():
        return str(thumb_path)
    lower = fp.name.lower()
    try:
        if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            im = Image.open(fp).convert("RGB")
            im.thumbnail(size)
            im.save(thumb_path, "JPEG", quality=80)
        elif lower.endswith((".mp4", ".mov", ".mkv", ".avi")):
            (
                ffmpeg
                .input(str(fp), ss=0.1)
                .filter("scale", f"{size[0]}:-1")
                .output(str(thumb_path), vframes=1, q=2)
                .overwrite_output()
                .run(quiet=True)
            )
    except Exception:
        return ""
    return str(thumb_path)

# ========== 新增文件夹封面函数 ==========
def get_folder_cover(dir_path: str, cache_dir: Path):
    cover_names = ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp")
    try:
        for cname in cover_names:
            cover_file = os.path.join(dir_path, cname)
            if os.path.isfile(cover_file):
                thumb_path = make_thumbnail(cover_file, cache_dir)
                return f"/api/thumb?path={quote(cover_file)}"
        img_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        vid_exts = (".mp4", ".mov", ".mkv", ".avi")
        files = sorted(os.listdir(dir_path))
        for f in files:
            full = os.path.join(dir_path, f)
            if not os.path.isfile(full):
                continue
            low = f.lower()
            if low.endswith(img_exts):
                thumb_path = make_thumbnail(full, cache_dir)
                return f"/api/thumb?path={quote(full)}"
            if low.endswith(vid_exts):
                thumb_path = make_thumbnail(full, cache_dir)
                return f"/api/thumb?path={quote(full)}"
    except Exception:
        pass
    return ""

@app.get("/api/get-setting")
async def get_setting():
    return load_setting()

@app.post("/api/save-setting")
async def set_setting(data: dict):
    save_setting(data)
    return {"ok": True}

@app.get("/api/list")
async def list_dir(dir: str = "", page: int = 1, size: int = 30):
    current = MEDIA_ROOT / dir
    if not current.is_dir():
        return JSONResponse([], status_code=404)
    entries = []
    for name in sorted(os.listdir(current)):
        full = current / name
        rel_path = str(full.relative_to(MEDIA_ROOT))
        if full.is_dir():
            cover_url = get_folder_cover(str(full), CACHE_DIR)
            entries.append({
                "type": "folder",
                "name": name,
                "path": rel_path,
                "cover": cover_url
            })
        else:
            low = name.lower()
            img_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
            vid_exts = (".mp4", ".mov", ".mkv", ".avi")
            if low.endswith(img_exts):
                entries.append({
                    "type": "image",
                    "name": name,
                    "path": rel_path,
                    "thumb": f"/api/thumb?path={quote(str(full))}"
                })
            elif low.endswith(vid_exts):
                entries.append({
                    "type": "video",
                    "name": name,
                    "path": rel_path,
                    "thumb": f"/api/thumb?path={quote(str(full))}"
                })
    start = (page - 1) * size
    return {"list": entries[start:start+size], "total": len(entries)}

@app.get("/api/thumb")
async def thumb(path: str):
    real_path = unquote(path)
    tp = make_thumbnail(real_path, CACHE_DIR)
    if tp and os.path.exists(tp):
        return FileResponse(tp)
    return Response(status_code=404)

@app.get("/api/src")
async def src(path: str):
    real_path = unquote(path)
    return FileResponse(real_path)

# 静态前端
app.mount("/", StaticFiles(directory="/frontend/dist", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
