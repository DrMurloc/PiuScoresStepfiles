# What is wrong with the caches under work/, before a loop trips over it.
#
# Every loop reads the shared caches - the sprite passes, the receptor fits and templates, the
# counter scans - and its own resume reports, and until tools/atomicio.py every one of them was
# written in a way a killed process could leave half-done: a 0-byte receptor field cache broke
# Another Truth D19 and Emperor S16 in every tool, and four counter scans stop minutes before
# their videos do. The loaders now treat a broken file as missing and rebuild it; this finds the
# ones already on disk, and the ones a loader cannot tell are wrong.
#
#   python -X utf8 -B tools/fsck.py [--json <report.json>] [--quarantine] [--only spritepass,receptor,combo,reports]
#
# Report-only by default, and it cannot be anything else: the process refuses every file write
# (atomicio.forbid_writes) except the --json report. --quarantine MOVES what is broken into
# work/quarantine/<run>/, keeping each file's path under work/ and writing a manifest.json that
# says why each one went; nothing is ever deleted, and a quarantined cache is simply missing, so
# the next reader rebuilds it.
#
# What counts as broken, and moves under --quarantine:
#   0 bytes; does not load (JSON, pickle, npz, or a jsonl line that does not parse); lacks what
#   its readers need; disagrees with its completion or provenance sidecar; a counter scan that
#   stops more than SHORT seconds before its video ends while the video decodes past that point
#   (a scan cut short - rescanning fixes it); temp files and .partial streams a killed writer
#   left behind.
# What is only reported:
#   stale key formats (names no current reader asks for - harmless, and the superseded receptor
#   fits are kept on purpose, to compare a fit against); a scan that is short because the video
#   itself stops decoding there (rescanning gives the same file); a scan that starts late.
import glob
import json
import os
import pickle
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atomicio as A   # noqa: E402
import cachekey        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
SHORT = 3.0            # s: a scan ending this long before its video is short
LATE = 3.0             # s: a scan starting this long after 0 was cut with from=
MOVE = {"0 bytes", "unloadable", "incomplete", "sidecar mismatch", "truncated scan", "orphan temp file",
        "orphan partial stream"}

VID = r"[A-Za-z0-9_-]{11}"
KEY = r"(?:\.k[0-9a-f]{12})?"
PASS_NAME = re.compile(r"^%s\.[LRC]\.[12]p\.\d+\.\d\.\d\d\.\d\.\d\d\.\d+\.h\d+\.\d\d\.r\d+\.\d\d\.s\d+\.\d\d\.\d+\.\d\.x\d+-\d+(?:\.ref)?%s\.pkl$" % (VID, KEY))
SPRITES_NAME = re.compile(r"^%s\.[12]p\.[LRC]\.\d+\.p\d+\.h\d+\.\d\d\.r\d+\.\d\d\.x\d+-\d+%s\.sprites\.npz$" % (VID, KEY))
FIELD_NAME = re.compile(r"^(%s)\.([LRC])\.(\d+)\.([12]p)\.inset%s\.field\.json$" % (VID, KEY))
OLD_FIELD_NAME = re.compile(r"^%s\.[LRC]\.\d+\.[12]p(?:\.sym)?\.field\.json$" % VID)
GEOM_NAME = re.compile(r"^%s\.[LRC]%s\.geometry\.json$" % (VID, KEY))
SCAN_NPZ_NAME = re.compile(r"^%s\.[LRC]\.(?:\d+|None)\.\d+\.\d-\d+\.\d\.scan\.npz$" % VID)
COMBO_NAME = re.compile(r"^(%s)\.([LRC])(\.[A-Za-z0-9_-]+)?%s\.jsonl$" % (VID, KEY))
TEMP_NAME = re.compile(r"^\..+\.\d+\.\d+\.\d+\.tmp$|\.\d+\.tmp\.npz$")
NON_PARAM = {"written", "complete", "lines", "bytes", "sha256", "finished", "video_seconds", "fps", "frames",
             "read", "first_t", "last_t", "stopped"}


class Findings:
    def __init__(self):
        self.rows = []
        self.checked = defaultdict(int)

    def add(self, area, path, kind, detail=""):
        self.rows.append(dict(area=area, path=os.path.relpath(path, WORK).replace(os.sep, "/"), kind=kind, detail=detail))


def sidecar_digest_ok(path):
    """A keyed file's sidecar must describe the parameters its name was keyed by."""
    m = re.search(r"\.k([0-9a-f]{12})\.", os.path.basename(path))
    meta = A.load_json(path + ".meta.json", quiet=True) or A.load_json(A.done_path(path), quiet=True)
    if not m or meta is None:
        return True
    return cachekey.digest({k: v for k, v in meta.items() if k not in NON_PARAM}) == m.group(1)


def common(f, area, path, name):
    """Checks every cache file gets: temp files, orphaned sidecars. True when it is a data file."""
    if TEMP_NAME.search(name):
        f.add(area, path, "orphan temp file", "left by a writer killed between writing and renaming")
        return False
    if name.endswith(".partial"):
        target = path[:-len(".partial")]
        f.add(area, path, "orphan partial stream", "a scan killed part-way%s" % ("" if not os.path.exists(target) else "; the finished file beside it is older"))
        return False
    for side in (".meta.json", ".done.json"):
        if name.endswith(side):
            if not os.path.exists(path[:-len(side)]):
                f.add(area, path, "orphan sidecar", "describes a file that is not there")
            return False
    return True


# ---------------------------------------------------------------- the areas

def check_spritepass(f):
    d = os.path.join(WORK, "spritepass")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        path = os.path.join(d, name)
        if not common(f, "spritepass", path, name):
            continue
        f.checked["spritepass"] += 1
        if not name.endswith(".pkl"):
            f.add("spritepass", path, "unexpected file"); continue
        if not PASS_NAME.match(name):
            f.add("spritepass", path, "stale key format", "no reader asks for this name (it predates the side in the key)")
        n = os.path.getsize(path)
        if n == 0:
            f.add("spritepass", path, "0 bytes"); continue
        try:
            with open(path, "rb") as fh:
                obj = pickle.load(fh)
        except Exception as ex:                  # noqa: BLE001 - any failure to load is the finding
            f.add("spritepass", path, "unloadable", "%s: %s" % (type(ex).__name__, f"{ex}"[:80])); continue
        if not (isinstance(obj, tuple) and len(obj) == 6):
            f.add("spritepass", path, "incomplete", "not the 6-tuple a sprite pass is"); continue
        if not sidecar_digest_ok(path):
            f.add("spritepass", path, "sidecar mismatch", "its .meta.json does not hash to the name's key")


def check_receptor(f):
    d = os.path.join(WORK, "receptor")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        path = os.path.join(d, name)
        if not common(f, "receptor", path, name):
            continue
        f.checked["receptor"] += 1
        if name.endswith(".json"):
            if OLD_FIELD_NAME.match(name):
                f.add("receptor", path, "superseded fit", "plain/.sym field fit - kept on purpose to compare against, read by nothing")
            elif not (FIELD_NAME.match(name) or GEOM_NAME.match(name)):
                f.add("receptor", path, "stale key format")
            if os.path.getsize(path) == 0:
                f.add("receptor", path, "0 bytes"); continue
            g = A.load_json(path, quiet=True)
            if g is None:
                f.add("receptor", path, "unloadable", "not JSON"); continue
            miss = [k for k in ("y0", "y1", "xs") if k not in g]
            if miss or not all(isinstance(x, int) for x in g.get("xs", [None])):
                f.add("receptor", path, "incomplete", "no %s" % ",".join(miss) if miss else "lanes are not integers"); continue
            m = FIELD_NAME.match(name)
            if m and len(g["xs"]) != int(m.group(3)):
                f.add("receptor", path, "incomplete", "%d lanes in a %s-column fit" % (len(g["xs"]), m.group(3)))
        elif name.endswith(".npz"):
            sprites = name.endswith(".sprites.npz")
            if sprites and not SPRITES_NAME.match(name):
                f.add("receptor", path, "stale key format", "a template key from before the percentile/lanes were in it")
            elif not sprites and not SCAN_NPZ_NAME.match(name):
                f.add("receptor", path, "stale key format")
            if os.path.getsize(path) == 0:
                f.add("receptor", path, "0 bytes"); continue
            z = A.load_npz(path, quiet=True)
            if z is None:
                f.add("receptor", path, "unloadable", "not a whole npz"); continue
            if not sprites and not {"ts", "flash", "lane", "xs", "fps", "y0", "y1"} <= set(z):
                f.add("receptor", path, "incomplete", "a scan without %s" % sorted({"ts", "flash", "lane", "xs", "fps", "y0", "y1"} - set(z)))
            elif sprites and not any(k in z for k in ("p0", "p1", "p2", "p3", "p4")):
                f.add("receptor", path, "empty templates", "no receptor could be cut (the extraction refuses this video)")
        else:
            f.add("receptor", path, "unexpected file")
        if not sidecar_digest_ok(path):
            f.add("receptor", path, "sidecar mismatch", "its .meta.json does not hash to the name's key")


def video_span(vid):
    """(declared seconds, fps) of a cached video, from the container alone - nothing decoded."""
    import cv2
    p = os.path.join(ROOT, "videos", vid + ".mp4")
    if not os.path.exists(p):
        return None, None
    cap = cv2.VideoCapture(p)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return (n / fps if fps else None), fps


def decodes_past(vid, t):
    """Whether the video decodes on past `t`, where a scan stopped: seek two seconds before it and
    decode forward (a seek lands on a keyframe, so one frame after a seek proves nothing) until a
    frame a second past `t` or the decoder stops. Returns (it does, the last time decoded)."""
    import cv2
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t - 2.0) * 1000)
    last = None
    for _ in range(900):
        ok, _ = cap.read()
        if not ok:
            break
        last = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if last > t + 1.0:
            break
    cap.release()
    return last is not None and last > t + 1.0, last


def check_combo(f):
    d = os.path.join(WORK, "combo")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        path = os.path.join(d, name)
        if not common(f, "combo", path, name):
            continue
        f.checked["combo"] += 1
        if name.endswith(".json"):
            if A.load_json(path, quiet=True) is None:
                f.add("combo", path, "0 bytes" if os.path.getsize(path) == 0 else "unloadable")
            continue
        if not name.endswith(".jsonl"):
            f.add("combo", path, "unexpected file"); continue
        m = COMBO_NAME.match(name)
        if not m:
            f.add("combo", path, "stale key format")
        st, why = A.jsonl_status(path)
        if st == "broken":
            f.add("combo", path, "0 bytes" if why == "0 bytes" else "sidecar mismatch", why); continue
        rows = A.read_jsonl(path, quiet=True)
        if rows is None:
            f.add("combo", path, "unloadable", "a line does not parse (a scan killed mid-line)"); continue
        if not all(isinstance(r, list) and len(r) == 3 for r in rows):
            f.add("combo", path, "incomplete", "rows are not [time, value, confidence]"); continue
        if not rows:
            f.add("combo", path, "incomplete", "no rows"); continue
        if not sidecar_digest_ok(path):
            f.add("combo", path, "sidecar mismatch", "its .done.json does not hash to the name's key")
        if not m:
            continue
        vid = m.group(1)
        side = A.load_json(A.done_path(path), quiet=True) or {}
        first, last = float(rows[0][0]), float(rows[-1][0])
        dur, fps = video_span(vid)
        if dur is None:
            f.add("combo", path, "no video", "videos/%s.mp4 is not cached, so its length is unknown" % vid); continue
        if first > LATE and not side.get("t0"):
            f.add("combo", path, "starts late", "first frame %.1fs (a scan cut with from=?)" % first)
        if last < dur - SHORT:
            if side.get("stopped") == "decoder stopped":
                f.add("combo", path, "short footage", "the scan's own record: the video stopped decoding at %.1fs of %.1fs" % (last, dur))
                continue
            ok, at = decodes_past(vid, last)
            if ok:
                f.add("combo", path, "truncated scan", "%d frames, last %.1fs of a %.1fs video that decodes on past it (to %.1fs and on) - rescan" % (len(rows), last, dur, at))
            else:
                f.add("combo", path, "short footage", "last %.1fs of %.1fs declared, and the video stops decoding there (%s) - a rescan gives the same" % (
                    last, dur, "nothing decodes after the seek" if at is None else "last frame %.1fs" % at))


def check_reports(f):
    """The loops' resume reports and the ledgers under work/: they load, and a SHIP row's candidate
    is there to commit."""
    for path in sorted(glob.glob(os.path.join(WORK, "*.json")) + glob.glob(os.path.join(WORK, "extract-loop", "*.json"))
                       + glob.glob(os.path.join(WORK, "tick-loop", "*.json"))):
        name = os.path.basename(path)
        f.checked["reports"] += 1
        if os.path.getsize(path) == 0:
            f.add("reports", path, "0 bytes"); continue
        doc = A.load_json(path, quiet=True)
        if doc is None:
            f.add("reports", path, "unloadable", "not JSON (a report written when its writer was killed?)"); continue
        if re.match(r"(extract|tick)-loop-report", name) and isinstance(doc, list):
            for r in doc:
                if r.get("verdict") == "SHIP" and not r.get("commit") and r.get("candidate"):
                    cand = os.path.join(ROOT, *r["candidate"].replace("\\", "/").split("/"))
                    if not os.path.exists(cand) or os.path.getsize(cand) == 0:
                        f.add("reports", path, "missing candidate", "%s: %s" % (r.get("chart"), r["candidate"]))
    for d in ("extract-loop", "tick-loop"):
        for path in sorted(glob.glob(os.path.join(WORK, d, "*"))):
            name = os.path.basename(path)
            if not common(f, "reports", path, name):
                continue
            if name.endswith(".ssc") and os.path.getsize(path) == 0:
                f.add("reports", path, "0 bytes", "an empty candidate")
    for path in sorted(glob.glob(os.path.join(WORK, ".*.tmp"))):
        common(f, "reports", path, os.path.basename(path))


AREAS = dict(spritepass=check_spritepass, receptor=check_receptor, combo=check_combo, reports=check_reports)


def quarantine(f, run):
    """Move every broken file (and its sidecars) into work/quarantine/<run>/, keeping its path."""
    qroot = os.path.join(WORK, "quarantine", run)
    moved = []
    for r in f.rows:
        if r["kind"] not in MOVE:
            continue
        src = os.path.join(WORK, *r["path"].split("/"))
        for p in (src, src + ".meta.json", A.done_path(src)):
            if not os.path.exists(p):
                continue
            dst = os.path.join(qroot, os.path.relpath(p, WORK))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(p, dst)
            moved.append(dict(r, moved=os.path.relpath(p, WORK).replace(os.sep, "/")))
    if moved:
        A.write_json(os.path.join(qroot, "manifest.json"), dict(run=run, moved=moved), encoding="utf-8", indent=1, ensure_ascii=False)
    return moved


def main():
    only = (sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else list(AREAS))
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    move = "--quarantine" in sys.argv
    if not move:
        A.forbid_writes(allow=[out] if out else [])
    t0 = time.time()
    f = Findings()
    for a in only:
        AREAS[a](f)
    by = defaultdict(lambda: defaultdict(list))
    for r in f.rows:
        by[r["area"]][r["kind"]].append(r)
    print("fsck of %s (%s) in %.0fs%s" % (WORK, ", ".join(only), time.time() - t0, "" if move else " - report only"))
    for a in only:
        kinds = by.get(a, {})
        print("\n%-10s %d files checked%s" % (a, f.checked[a], "" if kinds else ": nothing wrong"))
        for kind, rows in sorted(kinds.items(), key=lambda kv: (kv[0] not in MOVE, kv[0])):
            print("  %-4s %-22s %5d  %s" % ("BAD" if kind in MOVE else "", kind, len(rows),
                                            "" if kind in MOVE else "(reported, not moved)"))
            for r in rows[:6]:
                print("         %s%s" % (r["path"], (" - " + r["detail"]) if r["detail"] else ""))
            if len(rows) > 6:
                print("         ... and %d more" % (len(rows) - 6))
    bad = [r for r in f.rows if r["kind"] in MOVE]
    print("\n%d broken file(s)%s" % (len(bad), "" if bad else " - clean"))
    if out:
        A.write_json(out, dict(generated=time.strftime("%Y-%m-%dT%H:%M:%S"), checked=dict(f.checked), findings=f.rows),
                     encoding="utf-8", indent=1, ensure_ascii=False)
    if move:
        run = "fsck-" + time.strftime("%Y%m%d-%H%M%S")
        moved = quarantine(f, run)
        print("quarantined %d file(s) into work/quarantine/%s/" % (len(moved), run) if moved else "nothing to quarantine")
    return 1 if bad and not move else 0


if __name__ == "__main__":
    sys.exit(main())
