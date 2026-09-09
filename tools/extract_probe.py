# Can the chart itself be read off the screen? First evidence that it can.
#
# Everything else in this repo reads the COMBO COUNTER and does arithmetic on it. That is a
# workaround: a person fixing these charts watches the video and transcribes the notes. This
# reads notes instead - a strip just under the receptors, where an arrow is fully drawn, the
# judgement flash is above it, and the COMBO overlay is below it - and reports one rising edge
# per note per column.
#
# FIRST RESULT (2026-09-09, three repaired charts whose notes are known right):
#   Dr. M D18   file 499 notes, extracted 585      My Way D16  file 447, extracted 503
#   Bee S17     file 463 notes, extracted 505
# The COUNT is close - the notes are being seen, roughly one event each. The TIMING match is
# not (6-19%), and the reason is a flaw in this probe rather than in the idea: it fits ONE
# global lead, and the lead is the scan strip's distance divided by the scroll speed, which
# moves with BPM and the speed mod. A note crossing at 200bpm leads by half what it does at
# 100bpm, so no single number aligns a chart that changes tempo.
#
# The fix is two scan strips a known number of pixels apart: each note's transit time between
# them IS the local scroll speed, which converts its crossing into an exact arrival at the
# receptor and needs no global assumption. That is the next thing to build.
#
#   python -X utf8 tools/extract_probe.py "<chart>"
import bisect, json, os, sys
import cv2, numpy as np
sys.path.insert(0, r"C:\Users\jonec\repos\PiuScoresStepfiles\tools")
import receptors as R, corpus_map
os.chdir(r"C:\Users\jonec\repos\PiuScoresStepfiles")

def extract(vid, band, ncols, t_end, lo=25, hi=55, th=0.30):
    """Every note crossing a strip just under the receptors: a rising edge per column."""
    cap = cv2.VideoCapture("videos/%s.mp4" % vid)
    y0, y1, xs = R.geometry(cap, vid, band, ncols)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
    occ, ts, t = [], [], 0.0
    while t < t_end:
        ok, f = cap.read()
        if not ok: break
        s = f[y1 + lo:y1 + hi]
        hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
        m = ((hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 120)).astype(np.uint8)
        occ.append([float(m[:, max(0, int(x) - 30):int(x) + 30].mean()) for x in xs])
        ts.append(t); t += 1.0 / fps
    occ = np.array(occ)
    ev = {}
    for c in range(ncols):
        v, out, on = occ[:, c], [], False
        for i in range(len(v)):
            if not on and v[i] > th: out.append(ts[i]); on = True
            elif on and v[i] < th * 0.6: on = False
        ev[c] = out
    return ev

def score(ev, notes, ncols, tol=0.05):
    best = (0, 0.0)
    for k in range(-60, 61):
        a = k / 200.0
        hit = 0
        for c in range(ncols):
            col = notes.get(c, [])
            for t in ev[c]:
                i = bisect.bisect_left(col, t - a - tol)
                if i < len(col) and abs(col[i] - (t - a)) <= tol: hit += 1
        if hit > best[0]: best = (hit, a)
    return best

name = sys.argv[1]
smap, cert = corpus_map.chart_map(), corpus_map.certification()
key = smap[name]["key"]
ncols = 10 if name.split()[-1][0] == "D" else 5
rows, taps, beat_at = R.chartstruct(key, ncols)
notes = {}
for r in rows:
    for c, ch in enumerate(r["Line"].lstrip("`")):
        if ch in "12": notes.setdefault(c, []).append(float(r["Time"]))
for c in notes: notes[c].sort()
n_file = sum(len(v) for v in notes.values())
vid, e = next((v, e) for v, e in cert.items() if name in (e.get("charts") or {}))
side = e["charts"][name].get("side") or "1p"
other = e.get("2p" if side == "1p" else "1p") or {}
band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
ev = extract(vid, band, ncols, float(e.get("t") or 150))
n_ev = sum(len(v) for v in ev.values())
hit, a = score(ev, notes, ncols)
print("%-24s file notes %5d | extracted %5d | matched %5d at lead %+.3fs" % (name, n_file, n_ev, hit, a))
print("   recall %.1f%% of the file's notes, precision %.1f%% of what was extracted"
      % (100.0 * hit / max(n_file, 1), 100.0 * hit / max(n_ev, 1)))
