from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
import json
import os
import sqlite3
import time
from urllib.parse import quote

MEDIA_ROOT = "/media"
CONFIG_PATH = "/app/config/config.json"
CACHE_PATH = "/app/cache"
DB_PATH = os.path.join(CACHE_PATH, "stat_cache.db")
CACHE_TTL = 3600
app = FastAPI(title="NAS瀑布流媒体后端")

# 初始化配置目录
def init_config():
    cfg_dir = Path(CONFIG_PATH).parent
    cfg_dir.mkdir(parents=True, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        default_cfg = {"view_mode": "waterfall", "slide_delay": 5, "loop_slide": True}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f)
    Path(CACHE_PATH).mkdir(parents=True, exist_ok=True)
init_config()

# sqlite统计缓存初始化
def init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS dir_stat (
            dir_path TEXT PRIMARY KEY,
            img_count INTEGER,
            video_count INTEGER,
            scan_ts INTEGER
        )
    ''')
    conn.commit()
    conn.close()
init_sqlite()

def get_cached_stat(full_dir: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT img_count, video_count, scan_ts FROM dir_stat WHERE dir_path=?", (full_dir,))
    row = c.fetchone()
    conn.close()
    if row:
        img_cnt, vid_cnt, ts = row
        if time.time() - ts < CACHE_TTL:
            return img_cnt, vid_cnt
    return None

def set_cached_stat(full_dir: str, img_cnt: int, vid_cnt: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO dir_stat(dir_path,img_count,video_count,scan_ts)
        VALUES (?,?,?,?)''', (full_dir, img_cnt, vid_cnt, int(time.time())))
    conn.commit()
    conn.close()

# 递归统计图片视频
def count_folder_media_recursive(full_dir: str):
    cached = get_cached_stat(full_dir)
    if cached is not None:
        return cached
    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    video_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".wmv", ".webm"}
    img_cnt = 0
    vid_cnt = 0
    try:
        for root, _, files in os.walk(full_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in img_exts:
                    img_cnt +=1
                elif ext in video_exts:
                    vid_cnt +=1
    except Exception:
        pass
    set_cached_stat(full_dir, img_cnt, vid_cnt)
    return img_cnt, vid_cnt

# 获取文件夹封面：优先cover.*，其次目录下第一张媒体（图片/视频）
def get_folder_cover(full_dir: Path):
    cover_names = {"cover.jpg","cover.png","cover.webp","cover.jpeg"}
    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    video_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".wmv", ".webm"}
    try:
        for entry in full_dir.iterdir():
            if entry.is_file():
                low_name = entry.name.lower()
                if low_name in cover_names:
                    return str(entry)
                ext = entry.suffix.lower()
                if ext in img_exts or ext in video_exts:
                    return str(entry)
    except Exception:
        pass
    return None

@app.get("/api/get-setting")
async def get_setting():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg

@app.post("/api/save-setting")
async def save_setting(payload: dict):
    valid = {
        "view_mode": payload.get("view_mode", "waterfall"),
        "slide_delay": int(payload.get("slide_delay", 5)),
        "loop_slide": bool(payload.get("loop_slide", True))
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(valid, f)
    return {"ok": True}

@app.get("/api/list")
async def list_files(
    dir: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100)
):
    base = Path(MEDIA_ROOT)
    target = base / dir
    if not target.exists() or not target.is_dir():
        return {"list": [], "total": 0, "page": page, "size": size}

    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    video_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".wmv", ".webm"}
    media_exts = img_exts.union(video_exts)

    items = []
    for f in target.iterdir():
        if f.is_dir():
            cover_fp = get_folder_cover(f)
            img_cnt, vid_cnt = count_folder_media_recursive(str(f))
            folder_thumb = None
            if cover_fp:
                rel = Path(cover_fp).relative_to(base)
                # 后端在这里完成url编码，返回完整url
                folder_thumb = f"/api/thumb?path={quote(str(rel))}"
            items.append({
                "path": str(f.relative_to(base)),
                "name": f.name,
                "type": "folder",
                "folder_thumb": folder_thumb,
                "image_count": img_cnt,
                "video_count": vid_cnt
            })
        elif f.is_file() and f.suffix.lower() in media_exts:
            t = "image"
            if f.suffix.lower() in video_exts:
                t = "video"
            items.append({
                "path": str(f.relative_to(base)),
                "name": f.name,
                "type": t
            })
    total = len(items)
    start = (page - 1) * size
    page_data = items[start: start + size]
    return {
        "list": page_data,
        "total": total,
        "page": page,
        "size": size
    }

@app.get("/api/media")
async def get_media(path: str = Query(...)):
    full = Path(MEDIA_ROOT) / path
    if not full.exists() or not full.is_file():
        return JSONResponse(status_code=404, content={"msg": "文件不存在"})
    return FileResponse(full)

@app.get("/api/thumb")
async def get_thumb(path: str = Query(...)):
    full_path = Path(MEDIA_ROOT) / path
    if not full_path.exists():
        return JSONResponse(status_code=404, content={"msg":"文件不存在"})
    ext = full_path.suffix.lower()
    image_exts = {".jpg",".jpeg",".png",".gif",".webp",".bmp"}
    cache_dir = Path(CACHE_PATH) / "thumb_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"{hash(full_path)}.jpg"

    if cache_file.exists():
        return FileResponse(cache_file)

    if ext in image_exts:
        # 图片缩略图，用pillow
        from PIL import Image
        try:
            with Image.open(str(full_path)) as im:
                im.thumbnail((400,400))
                im.save(cache_file, format="JPEG", quality=75)
            return FileResponse(cache_file)
        except Exception as e:
            print("image thumb err",e)
            return JSONResponse(status_code=500, content={"msg":"图片缩略图生成失败"})
    else:
        # 视频 ffmpeg
        cmd = [
            "ffmpeg", "-ss", "00:00:00.8",
            "-i", str(full_path),
            "-vframes", "1",
            "-q:v", "3",
            "-y", str(cache_file)
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=12)
        if proc.returncode !=0:
            print("ffmpeg fail:", str(full_path), proc.stderr.decode("utf‑8","ignore"))
            return JSONResponse(status_code=500, content={"msg":"视频缩略图生成失败"})
        return FileResponse(cache_file)

# 所有API放前面！
app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
