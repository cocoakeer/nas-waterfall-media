from .config import CACHE_PATH
import os
import subprocess
from pathlib import Path

def get_cover_cache_path(rel_media_path: str):
    p = Path(rel_media_path)
    cover_name = p.with_suffix(".jpg").name
    cover_full = CACHE_PATH / "covers" / rel_media_path / cover_name
    cover_full.parent.mkdir(parents=True, exist_ok=True)
    return str(cover_full)

def generate_video_cover(video_full_path: str, cover_full_path: str):
    if os.path.exists(cover_full_path):
        return cover_full_path
    cmd = [
        "ffmpeg",
        "-ss", "00:00:01",
        "-i", video_full_path,
        "-vframes", "1",
        "-vf", "scale=400:-1",
        "-q:v", "9",
        "-y",
        cover_full_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15)
        if os.path.exists(cover_full_path):
            return cover_full_path
    except Exception:
        pass
    return None
