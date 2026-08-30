# Dump sample frames from a downloaded video for geometry work.
#   python tools\probe_frames.py <videoId> [t1 t2 ...]   (seconds; default spread)
import os, sys, glob
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
vid = sys.argv[1]
path = glob.glob(os.path.join(ROOT, "videos", vid + ".*"))
path = [p for p in path if not p.endswith((".part", ".ytdl"))][0]
cap = cv2.VideoCapture(path)
fps = cap.get(cv2.CAP_PROP_FPS)
n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
dur = n / fps if fps else 0
w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"{os.path.basename(path)}: {w}x{h} @ {fps:.2f}fps, {dur:.1f}s")

ts = [float(t) for t in sys.argv[2:]] or [dur * f for f in (0.05, 0.2, 0.35, 0.5, 0.7, 0.9)]
outdir = os.path.join(ROOT, "work", "frames", vid)
os.makedirs(outdir, exist_ok=True)
for t in ts:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        print(f"  t={t:.1f}s: read failed")
        continue
    out = os.path.join(outdir, f"t{int(t):04d}.jpg")
    cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"  t={t:.1f}s -> {out}")
