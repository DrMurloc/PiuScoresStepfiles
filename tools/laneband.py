# The median receptor band of every cached video, decoded once, so a lane-fit rule is arithmetic.
#
# receptors.field() fits a video's lanes from ONE picture: the per-pixel median of 64 frames seeked
# evenly through the video, grey, cut to the receptor band's rows. Everything after that picture is
# a few milliseconds of arithmetic; getting the picture is 64 seeks (10-25 s on h264, 2-4 minutes on
# AV1). So a candidate fit rule re-fitted directly over the 2,019 cached videos costs the decode
# every time, about 35 CPU-hours a candidate; over this cache it costs minutes.
#
# The cache is that picture, taller than the band so a rule may look above and below it:
#   work/lanes/medband/<vid>.k<digest>.medband.npz
#     med2       uint16 [rows, w]  twice the per-pixel median (the median of 64 uint8 values is
#                                  a whole or half number, so this is lossless)
#     Y          [Y0, Y1]          which frame rows the picture holds (int(h*0.02), int(h*0.30))
#     band       [y0, y1]          the field band's rows (int(h*0.07), int(h*0.21)), as receptors
#     ok         bool [n]          which of the n seeks decoded a frame
#     md5        S32 [n]           md5 of each decoded frame's field band (grey), for drift checks
#     shape      [h, w], fps, frame_count, dur, n
# The digest is over the parameters and the code stamp of _decode_median (tools/cachekey.py): a
# change to how the picture is made gives it new files and never hands back an old one.
#
# The median of a taller crop is, row for row, the median of the band: np.median works per pixel.
# fit_field_from() is receptors._fit_field's arithmetic applied to the band rows, and must give the
# cached .inset fit byte for byte (preflight, and lanefit.py's census, check exactly that).
#
#   laneband.py build --vids <vid> ... | --vids-file F     decode what is not cached (one slot)
#   laneband.py preflight [--no-codecs]                     re-fit 8 known videos and probe AV1 + VP9; exit 2 on any drift
#   laneband.py status                                      how much of the cache exists
import argparse
import hashlib
import json
import os
import sys
import time

import cv2
import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import atomicio as A                                  # noqa: E402
import cachekey                                       # noqa: E402
import receptors as R                                 # noqa: E402

N = 64
ROWS = (0.02, 0.30)          # the stored picture, as fractions of the frame height
MEDBAND_DIR = os.path.join(ROOT, "work", "lanes", "medband")
VIDEOS = os.path.join(ROOT, "videos")
FIELD_DIR = os.path.join(ROOT, "work", "receptor")

# Eight videos whose .inset fits were re-fitted byte for byte on 2026-09-26 (research
# determinism.json): five in band, three misfits, singles and doubles, both sides, L and C bands.
PREFLIGHT = [("gxXqbXvzKOU", "L", 5, "1p"), ("x_d68CYJioE", "C", 10, "1p"), ("VyNEwu1XUjs", "C", 10, "1p"),
             ("b75q1UXkaKI", "C", 5, "2p"), ("nhAI_6qN6gs", "C", 10, "1p"), ("X14P1SjDza8", "C", 10, "1p"),
             ("9B2roORF9Zc", "C", 10, "2p"), ("1EdGrclHG_I", "C", 10, "1p")]
# The eight are all h264; every PHOENIX 2 official upload (the held-out stratum) is AV1, and four
# official uploads are VP9. No AV1 or VP9 video has a cached .inset fit, so these are checked without
# one: production _fit_field against the arithmetic on the same fresh decode (the same fit, or the
# same exception), and the cached picture against the fresh one. Both carry only tune charts.
PREFLIGHT_CODECS = [("1Ez5gpvFDyE", "C", 10, "1p", "AV01"), ("Pa8PBY5zdKM", "C", 10, "1p", "VP90")]


def stored_rows(h):
    return int(h * ROWS[0]), int(h * ROWS[1])


def _decode_median(cap, n):
    """receptors._fit_field's frames, exactly: n seeks at (k + 0.5) / n of the declared duration,
    each frame converted to grey whole (then cut), the per-pixel median over the frames that decoded.
    Returns the taller picture and what it was made of."""
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    crops, ok_mask, md5 = [], [], []
    h = w = None
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, (dur * (k + 0.5) / n) * 1000)
        ok, fr = cap.read()
        ok_mask.append(bool(ok))
        if not ok:
            md5.append(b"")
            continue
        if h is None:
            h, w = fr.shape[:2]
            Y0, Y1 = stored_rows(h)
            y0, y1 = int(h * 0.07), int(h * 0.21)
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        crops.append(g[Y0:Y1, :])
        md5.append(hashlib.md5(np.ascontiguousarray(g[y0:y1, :]).tobytes()).hexdigest().encode())
    if not crops:
        return None
    med = np.median(np.stack(crops), axis=0)
    return dict(med=med, h=h, w=w, dur=dur, ok=ok_mask, md5=md5)


def params(n=N):
    return dict(cache="medband", n=n, rows=list(ROWS), field_rows=[0.07, 0.21],
                code=cachekey.code_stamp(_decode_median, stored_rows))


def medband_path(vid, n=N):
    return os.path.join(MEDBAND_DIR, "%s.k%s.medband.npz" % (vid, cachekey.digest(params(n))))


def fail_path(vid, n=N):
    return medband_path(vid, n)[:-len(".npz")] + ".fail.json"


def open_video(vid):
    return cv2.VideoCapture(os.path.join(VIDEOS, vid + ".mp4"))


def decode(vid, n=N):
    """The picture from the video (no cache). None when the video does not open or no seek decodes."""
    cap = open_video(vid)
    try:
        if not cap.isOpened():
            return None, "does not open"
        fps = cap.get(cv2.CAP_PROP_FPS)
        fc = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or not fc:
            return None, "no frame rate or frame count (fps %r, frames %r)" % (fps, fc)
        d = _decode_median(cap, n)
        if d is None:
            return None, "no seek decoded a frame"
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        d.update(fps=float(fps), frame_count=float(fc),
                 fourcc="".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)))
        return d, None
    finally:
        cap.release()


def pack(d):
    med2 = np.rint(2.0 * d["med"]).astype(np.uint16)
    if not np.array_equal(med2.astype(np.float64) / 2.0, d["med"]):
        raise AssertionError("median is not a whole or half number - the lossless store would lie")
    h, w = d["h"], d["w"]
    Y0, Y1 = stored_rows(h)
    return dict(med2=med2, Y=np.array([Y0, Y1]), band=np.array([int(h * 0.07), int(h * 0.21)]),
                ok=np.array(d["ok"], dtype=bool), md5=np.array(d["md5"], dtype="S32"),
                shape=np.array([h, w]), fps=np.array(d["fps"]), frame_count=np.array(d["frame_count"]),
                dur=np.array(d["dur"]), n=np.array(len(d["ok"])))


def load(vid, n=N, quiet=True):
    """The cached picture as a dict (med = float64 median, exactly np.median's values), or None."""
    z = A.load_npz(medband_path(vid, n), required=("med2", "Y", "band", "ok", "shape"), quiet=quiet)
    if z is None:
        return None
    Y0, Y1 = (int(v) for v in z["Y"])
    y0, y1 = (int(v) for v in z["band"])
    h, w = (int(v) for v in z["shape"])
    med = z["med2"].astype(np.float64) / 2.0
    return dict(vid=vid, full=med, Y0=Y0, Y1=Y1, y0=y0, y1=y1, h=h, w=w, ok=z["ok"], md5=z["md5"],
                fps=float(z["fps"]), dur=float(z["dur"]), n_ok=int(z["ok"].sum()),
                field=med[y0 - Y0:y1 - Y0, :])


def build_one(vid, n=N, retry_failed=False):
    """'cached' | 'built' | 'failed: <why>' for one video."""
    ck = medband_path(vid, n)
    if A.load_npz(ck, required=("med2", "Y", "band", "ok", "shape"), quiet=True) is not None:
        return "cached"
    fp = fail_path(vid, n)
    if os.path.exists(fp) and not retry_failed:
        f = A.load_json(fp, quiet=True) or {}
        return "failed: %s (recorded)" % f.get("why", "?")
    t = time.time()
    d, why = decode(vid, n)
    if d is None:
        os.makedirs(MEDBAND_DIR, exist_ok=True)
        A.write_json(fp, dict(vid=vid, why=why, when=time.strftime("%Y-%m-%dT%H:%M:%S"), **params(n)),
                     encoding="utf-8", indent=1)
        return "failed: " + why
    arrays = pack(d)
    os.makedirs(MEDBAND_DIR, exist_ok=True)
    A.write_npz(ck, compressed=True, **arrays)
    A.write_meta(ck, vid=vid, fourcc=d["fourcc"], n_ok=int(sum(d["ok"])), seconds=round(time.time() - t, 1),
                 cv2=cv2.__version__, numpy=np.__version__, **params(n))
    return "built %d/%d frames, %s, %.1fs" % (sum(d["ok"]), n, d["fourcc"], time.time() - t)


# ---------------------------------------------------------------- the fit, as arithmetic

def fit_field_from(med, w, band, ncols, side, y0, y1):
    """receptors._fit_field after its decode, applied to a cached picture's band rows. Same
    arithmetic, same types, same dict, same exception on a pitch out of range."""
    prof = cv2.GaussianBlur(med.astype(np.float32), (0, 0), 3).mean(axis=0)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 3).ravel()
    prof = prof - np.percentile(prof, 30)
    lo_x, hi_x = (0, w // 2) if band == "L" else (w // 2, w) if band == "R" else (0, w)
    top = prof[lo_x:hi_x].max()
    peaks = [x for x in range(max(8, lo_x), min(w - 8, hi_x))
             if prof[x] == prof[x - 8:x + 9].max() and prof[x] > 0.6 * top]
    groups = [[peaks[0]]]
    gaps = np.diff(peaks)
    wide = 2.5 * float(np.median(gaps)) if len(gaps) else 1e9
    for x, g in zip(peaks[1:], gaps):
        (groups[-1] if g <= wide else groups.append([]) or groups[-1]).append(x)
    groups = [g for g in groups if len(g) >= 3]
    if len(groups) >= 2:
        groups.sort(key=lambda g: g[0])
        pick = groups[0] if side == "1p" else groups[-1]
    else:
        pick = peaks
    lo, hi = min(pick), max(pick)
    c, sym = R._mirror_axis(med, (lo + hi) / 2.0, (hi - lo) / 2.0, w)
    if sym >= 0.8 and abs((lo + hi) / 2.0 - c) > 2.0:
        p0 = (hi - lo) / ncols
        loose = [x for x in range(max(8, lo_x, int(lo - 1.5 * p0)), min(w - 8, hi_x, int(hi + 1.5 * p0)))
                 if prof[x] == prof[x - 8:x + 9].max() and prof[x] > 0.35 * top]
        pairs = [(b - a, a, b) for a in loose for b in loose
                 if a < c < b and abs((a + b) / 2.0 - c) <= 2.0
                 and 0.035 <= (b - a) / ncols / w <= 0.080]
        if pairs:
            _, lo, hi = max(pairs)
    p = (hi - lo) / (ncols - 2 * R.INSET)
    if not 0.035 <= p / w <= 0.080:
        raise ValueError("lane pitch %.0fpx is %.1f%% of a %dpx frame, which is not a %d-lane field"
                         % (p, 100 * p / w, w, ncols))
    xs = [int(round(lo + (k + 0.5 - R.INSET) * p)) for k in range(ncols)]
    return dict(y0=y0, y1=y1, xs=xs, pitch=round(p, 1), band=band, side=side,
                fields=len(groups), axis=c, symmetry=round(sym, 3))


def fit_from_cache(mb, band, ncols, side):
    return fit_field_from(mb["field"], mb["w"], band, ncols, side, mb["y0"], mb["y1"])


def fit_bytes(fit):
    """The bytes receptors.field() writes for a fit (atomicio.write_json -> json.dump defaults)."""
    return json.dumps(fit)


def inset_path(vid, band, ncols, side):
    return os.path.join(FIELD_DIR, "%s.%s.%d.%s.inset.field.json" % (vid, band, ncols, side))


def inset_text(vid, band, ncols, side):
    """The cached .inset fit's text, read only, or None."""
    p = inset_path(vid, band, ncols, side)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- invariants

def _corr(a, b):
    a = a.ravel().astype(np.float64)
    b = b.ravel().astype(np.float64)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def crops(med, xs, p):
    """The receptor crop under each lane (half-width 0.45 lane), or None if one leaves the frame."""
    h = int(p * 0.45)
    if h < 4 or min(xs) - h < 0 or max(xs) + h > med.shape[1]:
        return None
    return [med[:, x - h:x + h] for x in xs]


def twin(med, xs, p):
    """Doubles: the two pads' receptor rows are the same picture, so lane k and lane k+5 agree.
    Mean correlation over the five pairs (misfits 0.32-0.48, right fits 0.93-0.98 in research).
    Not mirror symmetry - that is 0.91-0.99 on good and bad fits alike."""
    cr = crops(med, xs, p)
    if cr is None or len(xs) != 10:
        return None
    return float(np.mean([_corr(cr[k], cr[k + 5]) for k in range(5)]))


def pad_twin(med, xs_a, xs_b, p):
    """Singles on a split screen: the other field's receptors are the same picture, lane for lane."""
    ca, cb = crops(med, xs_a, p), crops(med, xs_b, p)
    if ca is None or cb is None or len(xs_a) != len(xs_b):
        return None
    return float(np.mean([_corr(a, b) for a, b in zip(ca, cb)]))


def mirror(med, xs, p):
    cr = crops(med, xs, p)
    if cr is None:
        return None
    n = len(xs)
    return float(np.mean([_corr(cr[k], cr[n - 1 - k][:, ::-1]) for k in range(n // 2)]))


def adjacent(med, xs, p):
    cr = crops(med, xs, p)
    if cr is None:
        return None
    return float(np.mean([_corr(cr[k], cr[k + 1]) for k in range(len(xs) - 1)]))


LIB_W = 48     # a receptor crop resampled to this many columns, whatever the pitch it was cut at


def canon(med, xs, p):
    """Each lane's receptor crop resampled to LIB_W columns and normalised (zero mean, unit
    variance), so crops cut at different pitches compare; None if a crop leaves the frame."""
    cr = crops(med, xs, p)
    if cr is None:
        return None
    out = []
    for c in cr:
        z = cv2.resize(c.astype(np.float32), (LIB_W, c.shape[0]), interpolation=cv2.INTER_AREA)
        out.append((z - z.mean()) / (z.std() + 1e-6))
    return out


def ncc(med, xs, p, lib):
    """Singles: how much a fit's five receptor crops look like the receptor library's five (lane k
    against library lane k mod 5), mean correlation. The library is built from doubles fits that
    passed twin agreement, never from a singles fit and never by the rule it grades."""
    cz = canon(med, xs, p)
    if cz is None or lib is None:
        return None
    return float(np.mean([_corr(c, lib[k % 5]) for k, c in enumerate(cz)]))


# ---------------------------------------------------------------- CLI

def cmd_build(a):
    vids = list(a.vids or [])
    if a.vids_file:
        with open(a.vids_file, encoding="utf-8-sig") as f:
            vids += [ln.strip() for ln in f if ln.strip()]
    import guards
    bad = 0
    for vid in vids:
        try:
            r = build_one(vid, retry_failed=a.retry_failed)
        except Exception as ex:                                  # one video never stops the batch
            r = "error: %s: %s" % (type(ex).__name__, ex)
        if r.startswith(("failed", "error")):
            bad += 1
            why = guards.footage_corrupt_reason(vid)
            if why:
                r += " [%s]" % why.split(" - ")[0]
        print("%s %s" % (vid, r), flush=True)
    print("VERDICT: %s" % ("OK" if not bad else "SOME_FAILED"), flush=True)
    return 0


def _fit_or_error(fn):
    """A fit's bytes, or its exception as text, so a raise compares like a fit."""
    try:
        return fit_bytes(fn())
    except Exception as ex:
        return "raised %s: %s" % (type(ex).__name__, ex)


def cmd_preflight(a):
    """Re-fit the 8 known videos from a fresh decode, through receptors._fit_field itself and through
    fit_field_from(); both must give the cached .inset bytes, and a cached picture must equal the
    fresh one. Then the codec probes (PREFLIGHT_CODECS): the codec is the one named, production and
    the arithmetic agree on the fresh decode, and the cached picture (which must exist) equals it.
    Catches a cv2/ffmpeg drift and a copy of the arithmetic that has come apart."""
    import supervise
    bad = []
    with supervise.decode_slot():
        for vid, band, ncols, side in PREFLIGHT[:a.limit]:
            want = inset_text(vid, band, ncols, side)
            if want is None:
                bad.append("%s: no cached .inset fit to compare with" % vid)
                continue
            t = time.time()
            cap = open_video(vid)
            prod = R._fit_field(cap, vid, band, ncols, side, N)
            cap.release()
            d, why = decode(vid)
            if d is None:
                bad.append("%s: %s" % (vid, why))
                continue
            y0, y1 = int(d["h"] * 0.07), int(d["h"] * 0.21)
            Y0, _ = stored_rows(d["h"])
            pure = fit_field_from(d["med"][y0 - Y0:y1 - Y0, :], d["w"], band, ncols, side, y0, y1)
            ok = [fit_bytes(prod) == want, fit_bytes(pure) == want]
            mb = load(vid)
            if mb is not None:
                ok.append(bool(np.array_equal(mb["full"], d["med"])))
            print("%s %s %d %s  production %s  arithmetic %s%s  %.1fs" % (
                vid, band, ncols, side, "same" if ok[0] else "DIFFERS", "same" if ok[1] else "DIFFERS",
                "" if mb is None else "  cached picture " + ("same" if ok[2] else "DIFFERS"),
                time.time() - t), flush=True)
            if not all(ok):
                bad.append("%s %s %d %s: %s" % (vid, band, ncols, side, ok))
        for vid, band, ncols, side, codec in ([] if a.no_codecs else PREFLIGHT_CODECS):
            t = time.time()
            cap = open_video(vid)
            prod = _fit_or_error(lambda: R._fit_field(cap, vid, band, ncols, side, N))
            cap.release()
            d, why = decode(vid)
            if d is None:
                bad.append("%s: %s" % (vid, why))
                continue
            y0, y1 = int(d["h"] * 0.07), int(d["h"] * 0.21)
            Y0, _ = stored_rows(d["h"])
            pure = _fit_or_error(lambda: fit_field_from(d["med"][y0 - Y0:y1 - Y0, :], d["w"], band, ncols, side, y0, y1))
            mb = load(vid)
            cached = None if mb is None else _fit_or_error(lambda: fit_from_cache(mb, band, ncols, side))
            ok = [d["fourcc"] == codec, prod == pure, mb is not None and bool(np.array_equal(mb["full"], d["med"])),
                  cached == prod]
            print("%s %s %d %s  %s  production %s arithmetic: %s  cached picture %s  cached arithmetic %s  %.1fs" % (
                vid, band, ncols, side, d["fourcc"], prod[:60], "same" if ok[1] else "DIFFERS",
                "not cached" if mb is None else "same" if ok[2] else "DIFFERS", "same" if ok[3] else "DIFFERS",
                time.time() - t), flush=True)
            if not all(ok):
                bad.append("%s %s %d %s (%s): codec/arithmetic/picture/cached %s" % (vid, band, ncols, side, codec, ok))
    if bad:
        print("PREFLIGHT FAILED: %s" % "; ".join(bad))
        print("VERDICT: DRIFT")
        return 2
    print("preflight: %d videos re-fitted byte for byte, %d codec probes (%s) agree (cv2 %s)" % (
        min(a.limit, len(PREFLIGHT)), 0 if a.no_codecs else len(PREFLIGHT_CODECS),
        ", ".join(c[-1] for c in PREFLIGHT_CODECS), cv2.__version__))
    print("VERDICT: OK")
    return 0


def cmd_status(a):
    vids = sorted(f[:-4] for f in os.listdir(VIDEOS) if f.endswith(".mp4"))
    have = sum(1 for v in vids if os.path.exists(medband_path(v)))
    failed = sum(1 for v in vids if os.path.exists(fail_path(v)))
    size = sum(os.path.getsize(medband_path(v)) for v in vids if os.path.exists(medband_path(v)))
    print("medband %s: %d of %d videos cached, %d failed, %.1f MB" % (cachekey.digest(params()), have, len(vids),
                                                                     failed, size / 1e6))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # A YouTube id may start with "-" (-5NBR2TjE0E), which argparse takes for an option: everything
    # after `build --vids` is a video id, read here rather than by argparse.
    if argv[:1] == ["build"] and "--vids" in argv:
        i = argv.index("--vids")
        vids, argv = argv[i + 1:], argv[:i]
        a = argparse.Namespace(cmd="build", vids=vids, vids_file=None, retry_failed="--retry-failed" in argv)
        return cmd_build(a)
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--vids", nargs="*")
    b.add_argument("--vids-file")
    b.add_argument("--retry-failed", action="store_true")
    p = sub.add_parser("preflight")
    p.add_argument("--limit", type=int, default=len(PREFLIGHT))
    p.add_argument("--no-codecs", action="store_true", help="skip the AV1/VP9 probes (minutes of decode)")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    return {"build": cmd_build, "preflight": cmd_preflight, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
