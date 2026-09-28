# Certification coverage for result-screen skins the ledgers could not read: the invariance diff a
# result_reader profile change must pass, the per-(video, side) gate, the blind contact sheets, and
# the ledger the new certifications land in (sources/certification-skins-<date>.json, merged by
# tools/corpus_map.py). Bucket #12 of the 2026-09-26 loop proposal.
#
#   read --out <file> [--baseline <rev>] [--unknown-dir <dir>] -- <vid>   (a video id may start with -)
#       One video, read twice on the SAME decoded frames: by this tree's result_reader
#       (result_reader.read_one: the read, the confirming reads at least 1.1 s away, the on-screen
#       checks) and by <rev>'s result_reader (default main), loaded from git. Writes one JSON file
#       atomically; never a ledger. The loops run it as one supervised job per video (300 s each).
#   batch --list <vids.tsv> --reads-dir <dir> [--baseline <rev>] [--timeout 300]
#       Many videos in one supervised job: one worker subprocess reads them in turn (`worker`), each
#       with its own timeout - a read that overruns kills the worker and is recorded as
#       <vid>.timeout.json - so the interpreter and cv2 start once per batch, not per video.
#   jobs --reads-dir <dir> --out <jobs.jsonl> [--vids <file>] [--baseline <rev>] [--batch 40] [--seq-batch 6]
#       The supervise jobs file: `batch` jobs over every video in the committed certification ledgers
#       (sources/certification-corpus-2026-09-10.json and the census's), or over the ids in --vids.
#   diff --reads-dir <dir> --out <report.json> [--scope xx2p|newskins] [--from base|step1] [--to step1|new]
#       The full-ledger invariance diff. For every entry of every committed certification ledger
#       it compares each field (status, t, skin, scale, the six cells and judged of each side) of
#       the ledger, of the baseline code's read today and of this tree's read, and classes every
#       difference: PRE-EXISTING (the baseline code already reads it differently from the ledger;
#       not this change's doing), INTENDED (what the change is for, per --scope) or UNINTENDED (a
#       change this code makes that it was not meant to - the profile does not land while there is
#       one). Also: the certification set-diff on (vid, chart, side, matched value), and the band
#       manifest (a certified chart whose reader band moves because its video gains a read of the
#       other side).
#   sheet ... / land ...  (below)
#
# The reads never write into work/unknown-glyphs (--unknown-dir) or into any ledger.
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import types

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import atomicio     # noqa: E402
import corpus_map   # noqa: E402

LABELS = ["perfect", "great", "good", "bad", "miss", "maxcombo"]
FIELDS = ("status", "t", "skin", "scale")
LEDGERS = {"corpus": "sources/certification-corpus-2026-09-10.json",
           "census": "sources/certification-2026-08-30.json"}
VIDEO_MAPS = ("work/corpus-video-map.json", "sources/video-map.json", "work/pilot-video-map.json")
# The reads are taken three ways on the same frames: the baseline revision's code ("base"), this
# tree's code with only the profiles STEP1 names ("step1": the XX 2P column alone), and this tree's
# code entire ("new": the Prime and DANCE GRADE profiles too), so each profile change is diffed on
# its own: base -> step1 is the 2P column, step1 -> new is the two new skins.
STEP1 = ("phoenix", "xx")
READS = {"base": lambda d: d["base"], "step1": lambda d: d.get("step1"), "new": lambda d: d["new"]["read"]}


# ---------------------------------------------------------------- reading one video, two codes

def load_baseline(rev):
    """<rev>'s tools/result_reader.py as a module (its atlases are this tree's, which the change
    under test must not touch). Returns (module, sha256 of its source)."""
    src = subprocess.run(["git", "show", "%s:tools/result_reader.py" % rev], cwd=ROOT, capture_output=True,
                         check=True).stdout
    mod = types.ModuleType("result_reader_base")
    mod.__file__ = os.path.join(TOOLS, "result_reader.py")      # ROOT, the atlases and videos/ resolve here
    exec(compile(src, "result_reader@%s" % rev, "exec"), mod.__dict__)
    return mod, hashlib.sha256(src).hexdigest()


def sequential_frames(rr, vid, backs=None):
    """The frames read_result asks for (t = dur - back, back = 1.5 .. 44.5), from ONE forward decode of
    the video's tail instead of 44 seeks: {round(t, 6): (frame, pts)}. Each t gets the frame whose
    timestamp is nearest; a t with no frame within 0.5 s (a stream that stops decoding) gets
    (None, None). Checked on 2026-09-27 on an official upload and two result-screen videos: the
    nearest frame is byte-identical to what cv2's seek returns for all 33 t tried. For videos whose
    seeks are slow (the official uploads: ~2 s a seek, about half that decoding forward)."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(rr.video_path(vid))
    if not cap.isOpened():
        return {}
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    targets = [dur - b for b in (backs if backs is not None else np.arange(1.5, 45, 1.0))]
    best = {round(float(t), 6): (0.5, None, None) for t in targets}
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, min(targets) - 1.0) * 1000)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        p = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        for t in targets:
            k = round(float(t), 6)
            d = abs(p - t)
            if d < best[k][0]:
                best[k] = (d, f, p)
    cap.release()
    return {k: (f, p) for k, (d, f, p) in best.items()}


class TwoCodes:
    """This tree's result_reader and <baseline>'s, loaded once and patched so that, per video, both
    read the same decoded frames (the new code decodes, the baseline reuses them) and each anchor
    search - a full-frame template match, most of a read's time - is computed once per (frame
    content, template content): both codes ask the same questions, and read_frame asks again what
    read_result just asked. Keyed by content, never by address."""

    def __init__(self, baseline, unknown_dir=None, crops_dir=None):
        import cv2
        self.crops_dir = crops_dir
        if crops_dir:
            os.makedirs(os.path.join(crops_dir, "crops"), exist_ok=True)
        import result_reader as new
        self.cv2, self.new, self.baseline = cv2, new, baseline
        self.base, base_sha = load_baseline(baseline)
        self.base_code = base_sha[:16]
        if unknown_dir:
            new.UNKNOWN_DIR = unknown_dir
        self.base.classify = new.classify    # same matcher; only where an unknown glyph is dumped differs
        self.memo, self.matches = {}, {}
        real, real_match = new.frame_at, new.match_anchor

        def frame_pos(cap, t):
            k = round(float(t), 6)
            if k not in self.memo:
                f = real(cap, t)
                self.memo[k] = (f, cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 if f is not None else None)
            return self.memo[k]

        def frame_at(cap, t):
            return frame_pos(cap, t)[0]

        def match_anchor(f, anchor):
            k = (f.shape, hashlib.blake2b(f.tobytes(), digest_size=16).digest(),
                 anchor.shape, hashlib.blake2b(anchor.tobytes(), digest_size=16).digest())
            if k not in self.matches:
                self.matches[k] = real_match(f, anchor)
            return self.matches[k]
        new.frame_pos = frame_pos
        new.frame_at = frame_at
        self.base.frame_at = frame_at
        new.match_anchor = match_anchor
        self.base.match_anchor = match_anchor
        self.base_profiles = self.base.load_profiles()

    def read(self, vid, sequential=False, confirm=True):
        self.memo.clear()
        self.matches.clear()
        if sequential:
            self.memo.update(sequential_frames(self.new, vid))
        doc = self.new.read_one(vid, confirm=confirm)
        step1 = self.new.read_result(vid, [q for q in self.new.load_profiles() if q["name"] in STEP1])
        b = self.base.read_result(vid, self.base_profiles)
        crops = self.save_crops(vid, (step1, doc["read"])) if self.crops_dir else []
        self.memo.clear()
        self.matches.clear()
        return dict(vid=vid, new=doc, step1=step1, base=b, base_rev=self.baseline, base_code=self.base_code,
                    step1_profiles=list(STEP1), sequential=bool(sequential), crops=crops)

    def save_crops(self, vid, reads):
        """Crops of every read side of an XX / Prime / DANCE GRADE screen, cut from the hit frame
        this read already decoded (so the blind sheets need no second decode)."""
        import cert_land
        saved = []
        for r in reads:
            if r.get("status") != "ok" or r.get("skin") not in ("xx", "prime", "dancegrade"):
                continue
            frames = [(abs(k - float(r["t"])), f) for k, (f, _p) in self.memo.items() if f is not None]
            if not frames:
                continue
            d, f = min(frames, key=lambda x: x[0])
            if d > 0.06:
                continue
            for side in ("1p", "2p"):
                if (r.get(side) or {}).get("judged") is None:
                    continue
                path = cert_land.crop_path(self.crops_dir, vid, r["skin"], side)
                if path in saved:
                    continue
                png = cert_land.crop_frame(f, r, side)
                if png:
                    atomicio.write_bytes(path, png)
                    saved.append(path)
        return [os.path.basename(p) for p in saved]


def summary(out):
    r, b = out["new"]["read"], out["base"]
    return "%s new %s %s %s | base %s %s %s" % (
        out["vid"], r.get("status"), r.get("skin"), {s: (r.get(s) or {}).get("judged") for s in ("1p", "2p")},
        b.get("status"), b.get("skin"), {s: (b.get(s) or {}).get("judged") for s in ("1p", "2p")})


def cmd_read(a):
    out = TwoCodes(a.baseline, a.unknown_dir).read(a.vid, a.sequential)
    atomicio.write_json(a.out, out, encoding="utf-8", ensure_ascii=False, indent=1)
    print("VERDICT: %s" % out["new"]["read"]["status"].upper().replace("-", "_"))
    print(summary(out))


def cmd_worker(a):
    """Reads `<vid>TAB<0|1 sequential>TAB<0|1 confirm>` lines from stdin, one video at a time, writing
    <reads-dir>/<vid>.json and answering `DONE <vid>` on stdout. `batch` drives it."""
    two = TwoCodes(a.baseline, a.unknown_dir, crops_dir=a.reads_dir)
    print("READY", flush=True)
    for line in sys.stdin:
        vid, seq, conf = line.rstrip("\n").split("\t")
        out = two.read(vid, seq == "1", conf == "1")
        atomicio.write_json(os.path.join(a.reads_dir, vid + ".json"), out, encoding="utf-8", ensure_ascii=False, indent=1)
        print("DONE %s" % summary(out), flush=True)


def cmd_batch(a):
    """Several videos in one supervised job, each still read in a subprocess with its own timeout
    (--timeout, 300 s): one worker process serves them in turn, so the interpreter, cv2 and the
    baseline load once instead of per video. A read that overruns its timeout kills the worker (the
    whole tree), is recorded as <vid>.timeout.json, and a fresh worker takes the rest. A video whose
    read file is already there is skipped."""
    import queue
    import threading
    vids = [l.split("\t") for l in (x.strip() for x in open(a.list, encoding="utf-8")) if l]
    vids = [x + ["1"] * (3 - len(x)) for x in vids]            # an old two-column list: confirm every read
    todo = [tuple(x) for x in vids if not os.path.exists(os.path.join(a.reads_dir, x[0] + ".json"))]
    print("%d of %d videos to read" % (len(todo), len(vids)), flush=True)
    timeouts = 0
    while todo:
        cmd = [sys.executable, "-X", "utf8", "-B", os.path.abspath(__file__), "worker", "--reads-dir", a.reads_dir,
               "--baseline", a.baseline] + (["--unknown-dir", a.unknown_dir] if a.unknown_dir else [])
        w = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        q = queue.Queue()

        def pump(stream=w.stdout, q=q):
            for l in stream:
                q.put(l)
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()
        try:
            if not (q.get(timeout=300) or "").startswith("READY"):
                raise RuntimeError("the worker did not start")
            while todo:
                vid = todo[0][0]
                w.stdin.write("\t".join(todo[0]) + "\n")
                w.stdin.flush()
                line = q.get(timeout=a.timeout)
                if line is None or not line.startswith("DONE " + vid + " "):
                    raise RuntimeError("the worker answered %r for %s" % (line, vid))
                print(line.rstrip(), flush=True)
                todo.pop(0)
        except queue.Empty:
            vid = todo.pop(0)[0]
            timeouts += 1
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(w.pid)], capture_output=True)
            atomicio.write_json(os.path.join(a.reads_dir, vid + ".timeout.json"),
                                dict(vid=vid, timeout_s=a.timeout), encoding="utf-8")
            print("TIMEOUT %s after %d s" % (vid, a.timeout), flush=True)
            continue
        finally:
            try:
                w.stdin.close()
            except OSError:
                pass
        w.wait(timeout=60)
    print("VERDICT: %s" % ("OK" if not timeouts else "TIMEOUTS_%d" % timeouts))


def ledger_vids():
    vids = set()
    for p in LEDGERS.values():
        vids |= set(corpus_map.ledger_entries(json.load(open(os.path.join(ROOT, p), encoding="utf-8"))))
    return sorted(vids)


def cmd_jobs(a):
    """Batches of videos for `batch` (a video the ledger found no result screen on is read from one
    forward decode of its last 45 s - its seeks are slow - and goes in smaller batches). Only the
    videos a change can certify something on get the confirming second-frame read (--confirm-skins:
    the ledger's XX videos, and every video without a result screen); for the rest the read is
    only compared."""
    vids = [v.strip() for v in open(a.vids, encoding="utf-8") if v.strip()] if a.vids else ledger_vids()
    merged = corpus_map.merge_certification([corpus_map.ledger_entries(json.load(open(os.path.join(ROOT, p), encoding="utf-8")))
                                             for p in (LEDGERS["corpus"], LEDGERS["census"])])
    rd = a.reads_dir.replace("\\", "/")
    os.makedirs(os.path.join(a.reads_dir, "unknown"), exist_ok=True)
    os.makedirs(os.path.join(a.reads_dir, "batches"), exist_ok=True)
    batches, cur, cur_seq = [], [], None
    for v in vids:
        e = merged.get(v, {})
        seq = "1" if e.get("status") != "ok" else "0"
        conf = "1" if (seq == "1" or e.get("skin") in a.confirm_skins.split(",")) else "0"
        size = a.seq_batch if seq == "1" else a.batch
        if cur and (seq != cur_seq or len(cur) >= size):
            batches.append(cur)
            cur = []
        cur.append((v, seq, conf))
        cur_seq = seq
    if cur:
        batches.append(cur)
    lines = []
    for i, b in enumerate(batches):
        lst = os.path.join(a.reads_dir, "batches", "b%04d.tsv" % i)
        atomicio.write_text(lst, "".join("\t".join(x) + "\n" for x in b), encoding="utf-8")
        cmd = ["{py}", "{tools}/cert_skins.py", "batch", "--list", "%s/batches/b%04d.tsv" % (rd, i),
               "--reads-dir", rd, "--baseline", a.baseline, "--unknown-dir", "%s/unknown" % rd]
        lines.append(json.dumps(dict(id="b%04d" % i, cmd=cmd, timeout=300 * len(b) + 300, slot=True,
                                     meta=dict(n=len(b), sequential=b[0][1] == "1"))))
    atomicio.write_text(a.out, "\n".join(lines) + "\n", encoding="utf-8")
    print("%d videos in %d batch jobs -> %s" % (len(vids), len(lines), a.out))


# ---------------------------------------------------------------- the invariance diff

def side_of(entry, s):
    x = (entry or {}).get(s) or {}
    return {**{k: x.get(k, "") for k in LABELS}, "judged": x.get("judged")}


def flat(entry):
    """Every compared field of a read or a ledger entry, as {field: value}."""
    e = entry or {}
    out = {f: e.get(f) for f in FIELDS}
    if out["scale"] is None:
        out["scale"] = 1.0 if e.get("status") == "ok" else None
    for s in ("1p", "2p"):
        for k, v in side_of(e, s).items():
            out["%s.%s" % (s, k)] = v
    return out


def empty_side(entry, s):
    x = side_of(entry, s)
    return x["judged"] is None and all(x[k] == "" for k in LABELS)


def intended_xx2p(base, new):
    """The XX 2P column change: what it may do to a read, and nothing else. Returns a class or None."""
    if base.get("status") == "no-result-screen" and new.get("status") == "corrupt-video":
        return "corrupt-video status (was no-result-screen)"
    if new.get("skin") != "xx" or new.get("status") != "ok":
        return None
    if base.get("status") == "ok" and base.get("skin") == "xx":
        same = all(flat(base)[f] == flat(new)[f] for f in flat(new) if not f.startswith("2p."))
        if same and empty_side(base, "2p") and not empty_side(new, "2p"):
            return "new 2P read" if side_of(new, "2p")["judged"] is not None else "new 2P cells, incomplete"
        return None
    if base.get("status") == "no-result-screen" and empty_side(new, "1p") and side_of(new, "2p")["judged"] is not None:
        return "new XX screen read on the 2P side alone"
    return None


def intended_newskins(base, new):
    """The Prime and DANCE GRADE profiles: a screen read where the earlier code found none."""
    if base.get("status") in ("no-result-screen",) and new.get("status") == "ok" and new.get("skin") in ("prime", "dancegrade"):
        return "new %s read" % new["skin"]
    return None


SCOPES = {"xx2p": intended_xx2p, "newskins": intended_newskins}


def video_maps():
    vm = {}
    for p in VIDEO_MAPS:
        path = os.path.join(ROOT, p)
        if os.path.exists(path):
            for e in json.load(open(path, encoding="utf-8")):
                for c in e["charts"]:
                    vm.setdefault((e["vid"], c["chart"]), c)
    return vm


def certify(read, charts, vid, vm):
    """What result_reader.main would record for these charts from this read: {chart: (side, value)}."""
    totals = {s: (read.get(s) or {}).get("judged") for s in ("1p", "2p")} if read.get("status") == "ok" else {}
    out = {}
    for name, c in (charts or {}).items():
        alt = vm.get((vid, name), {}).get("judged_alt")
        expect = [c.get("expected")] + ([alt] if alt else [])
        side = next((s for s, j in totals.items() if j is not None and j in expect), None)
        if side:
            out[name] = (side, totals[side])
    return out


def ledger_certs(entries):
    """{(vid, chart, side, value)} a ledger records as CERTIFIED (value = the total on that side)."""
    out = set()
    for vid, e in entries.items():
        for name, c in (e.get("charts") or {}).items():
            if c.get("verdict") == "CERTIFIED":
                side = c.get("side")
                out.add((vid, name, side, (e.get(side) or {}).get("judged")))
    return out


def band(entry, side):
    other = (entry or {}).get("2p" if side == "1p" else "1p") or {}
    return "C" if not other.get("judged") else ("L" if side == "1p" else "R")


def cmd_diff(a):
    intended = SCOPES[a.scope]
    get_from, get_to = READS[a.frm], READS[a.to]
    reads = {}
    for p in glob.glob(os.path.join(a.reads_dir, "*.json")):
        d = atomicio.load_json(p)
        if d and "new" in d:
            reads[d["vid"]] = d
    vm = video_maps()
    rows, counts = [], {}
    missing = []

    def bump(k):
        counts[k] = counts.get(k, 0) + 1
    ledgers = {name: corpus_map.ledger_entries(json.load(open(os.path.join(ROOT, p), encoding="utf-8")))
               for name, p in LEDGERS.items()}
    for lname, entries in ledgers.items():
        for vid, led in sorted(entries.items()):
            d = reads.get(vid)
            if not d:
                missing.append((lname, vid))
                bump("%s: NOT READ" % lname)
                continue
            new, base = get_to(d), get_from(d)
            if new is None or base is None:
                missing.append((lname, vid))
                bump("%s: NOT READ (no %s read)" % (lname, a.frm if base is None else a.to))
                continue
            fl, fb, fn = flat(led), flat(base), flat(new)
            changed = sorted(f for f in fn if fn[f] != fb[f])            # the --to code vs the --from code
            drift = sorted(f for f in fb if fb[f] != fl[f])              # the --from code vs the ledger
            cls = intended(base, new) if changed else None
            if not changed and not drift:
                bump("%s: unchanged" % lname)
                continue
            kind = ("INTENDED: " + cls) if (changed and cls) else ("UNINTENDED" if changed else None)
            if kind:
                bump("%s: %s" % (lname, kind))
            if drift:
                bump("%s: PRE-EXISTING drift (%s)" % (lname, ",".join(sorted({f.split(".")[0] for f in drift}))))
            rows.append(dict(ledger=lname, vid=vid, kind=kind, changed={f: [fb[f], fn[f]] for f in changed},
                             drift={f: [fl[f], fb[f]] for f in drift}))
    # the certification set-diff: the committed ledgers as they stand vs the same charts certified from
    # this code's reads (and, for scale, from the baseline code's reads)
    merged = corpus_map.merge_certification([ledgers["corpus"], ledgers["census"]])
    before = ledger_certs(merged)
    by_code = {"base": set(), "new": set()}
    for vid, e in merged.items():
        d = reads.get(vid)
        if not d:
            continue
        for code, read in (("base", get_from(d)), ("new", get_to(d))):
            for name, (side, val) in certify(read or {}, e.get("charts"), vid, vm).items():
                by_code[code].add((vid, name, side, val))
    # the band manifest: a chart the ledgers certify whose video gains (or loses) a read of the other side
    bands = []
    for vid, name, side, val in sorted(before):
        d = reads.get(vid)
        if not d:
            continue
        if get_from(d) is None or get_to(d) is None:
            continue
        b0, b1 = band(get_from(d), side), band(get_to(d), side)
        if b0 != b1:
            bands.append(dict(vid=vid, chart=name, side=side, value=val, band_before=b0, band_after=b1,
                              other_side=side_of(get_to(d), "2p" if side == "1p" else "1p")))
    rep = dict(
        scope=a.scope, compared="%s -> %s" % (a.frm, a.to), reads=len(reads), counts=dict(sorted(counts.items())), not_read=missing,
        certset=dict(ledger=len(before), base_code=len(by_code["base"]), new_code=len(by_code["new"]),
                     ledger_minus_base=sorted(before - by_code["base"]), base_minus_ledger=sorted(by_code["base"] - before),
                     removed_by_change=sorted(by_code["base"] - by_code["new"]),
                     added_by_change=sorted(by_code["new"] - by_code["base"])),
        bands=bands, rows=rows)
    atomicio.write_json(a.out, rep, encoding="utf-8", ensure_ascii=False, indent=1)
    for k, v in rep["counts"].items():
        print("%6d  %s" % (v, k))
    cs = rep["certset"]
    print("certified (vid, chart, side, value): ledger %d, baseline code %d, this code %d" % (
        cs["ledger"], cs["base_code"], cs["new_code"]))
    print("  ledger - baseline %d, baseline - ledger %d | removed by the change %d, added by the change %d" % (
        len(cs["ledger_minus_base"]), len(cs["base_minus_ledger"]), len(cs["removed_by_change"]), len(cs["added_by_change"])))
    print("band changes on certified charts: %d" % len(bands))
    print("-> %s" % a.out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read")
    p.add_argument("vid")
    p.add_argument("--out", required=True)
    p.add_argument("--baseline", default="main")
    p.add_argument("--unknown-dir")
    p.add_argument("--sequential", action="store_true",
                   help="decode the tail once instead of seeking (for videos whose seeks are slow)")
    p = sub.add_parser("worker")
    p.add_argument("--reads-dir", required=True)
    p.add_argument("--baseline", default="main")
    p.add_argument("--unknown-dir")
    p = sub.add_parser("batch")
    p.add_argument("--list", required=True)
    p.add_argument("--reads-dir", required=True)
    p.add_argument("--baseline", default="main")
    p.add_argument("--unknown-dir")
    p.add_argument("--timeout", type=int, default=300)
    p = sub.add_parser("jobs")
    p.add_argument("--reads-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--vids")
    p.add_argument("--baseline", default="main")
    p.add_argument("--batch", type=int, default=40)
    p.add_argument("--seq-batch", type=int, default=6)
    p.add_argument("--confirm-skins", default="xx")
    p = sub.add_parser("diff")
    p.add_argument("--reads-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--scope", default="xx2p", choices=sorted(SCOPES))
    p.add_argument("--from", dest="frm", default="base", choices=sorted(READS))
    p.add_argument("--to", default="step1", choices=sorted(READS))
    a = ap.parse_args()
    {"read": cmd_read, "worker": cmd_worker, "batch": cmd_batch, "jobs": cmd_jobs, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
