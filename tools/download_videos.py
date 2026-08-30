# Downloads the census source footage into videos/ (gitignored).
# Run with the piu-annotate venv python:
#   ..\piu-annotate\.venv\Scripts\python.exe tools\download_videos.py
# Idempotent: yt-dlp's --download-archive skips anything already fetched.
# Polite: single-threaded, 2-5s sleep between videos, hard-stops on a bot challenge.
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS = os.path.join(ROOT, "videos")
os.makedirs(VIDEOS, exist_ok=True)
vmap = json.load(open(os.path.join(ROOT, "sources", "video-map.json"), encoding="utf-8"))
targets = [e for e in vmap if e.get("download")]

# 720p-capped video-only stream (arrows stay readable, no ffmpeg merge needed);
# falls back to best available if no 720p mp4 exists.
FMT = "bv*[height<=720][ext=mp4]/bv*[height<=720]/bv*/b"

args = [sys.executable, "-m", "yt_dlp",
        "--download-archive", os.path.join(VIDEOS, ".archive.txt"),
        "-f", FMT,
        "-o", os.path.join(VIDEOS, "%(id)s.%(ext)s"),
        "--no-playlist", "--retries", "3",
        "--sleep-interval", "2", "--max-sleep-interval", "5",
        "--no-progress", "--print", "after_move:%(id)s %(ext)s %(height)s",
        ] + [f"https://www.youtube.com/watch?v={e['vid']}" for e in targets]
print(f"{len(targets)} videos", flush=True)
rc = subprocess.call(args)
have = {f.split(".")[0] for f in os.listdir(VIDEOS) if not f.startswith(".")}
missing = [e["vid"] for e in targets if e["vid"] not in have]
print(f"exit {rc}; have {len(have & {e['vid'] for e in targets})}/{len(targets)}; missing: {missing}")
