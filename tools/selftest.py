# The parts of the pipeline that can be checked without footage, pinned against the exact
# outputs they are supposed to read. Every case here is a bug that actually shipped once - the
# point is that the next change to a regex or a rule trips over the same stone in a second
# rather than in a batch of eighty charts.
#
# Runs in about a second and needs no videos, no database and no network.
#
#   python -X utf8 tools/selftest.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch_repair as B          # noqa: E402
import video_freshness as F       # noqa: E402

CASES = []

def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco

def eq(got, want, what):
    assert got == want, f"{what}: got {got!r}, wanted {want!r}"

# ------------------------------------------------------------------ reading the tools' output

@case("rail_ticks output: priced, reset and unbracketed rails are told apart")
def _():
    out = r"""Leather D22: 7NSEVRpGnG0 band C, offset 11.3, judged 1450, owed 620 hold events
  col 7: video  23.52- 23.85  chart  12.22- 12.55  beats 40.000-41.083  head new note | counter 44@23.40 -> 51@24.00: +7 incl. 3 taps -> 4 ticks
  col 5: video  30.75- 30.92  chart  19.45- 19.62  beats 64.083-64.625  head new note | counter DROPS between the reads (106@30.30 -> 15@31.15) - a reset inside or just before, frames needed
  col 6: video  59.83- 60.93  chart  48.53- 49.63  beats 161.000-164.688  head new note | no bracket read (after) - frames work\frames\rails\x.png
  col 2: video 169.28-169.47  chart 157.98-158.17  beats 525.875-526.500  head new note | counter 5@169.18 -> 6@170.00: +1 incl. 5 taps -> -4 ticks
  priced from brackets: 325 of 620 owed"""
    r = B.parse_rails(out)
    eq(r["owed"], 620, "owed")
    eq(r["priced"], 2, "rails priced")
    eq([x["why"] for x in r["rails"]], [None, "reset", "no bracket", None], "why each rail failed")
    eq(r["rails"][3]["ticks"], -4, "a negative price is still a price, and the gate judges it")

@case("run_drift output: only hold-FREE runs count toward the drift")
def _():
    out = """Leather D22: 7NSEVRpGnG0 band C, judged 1450, file taps 830, file holds 227, play has 17 miss / 20 bad
  run (video)      counter   file taps   drift   holds in span
    17.1-  28.2   +   82      +   56     +26   14
    77.0-  87.8   +   83      +   86      -3   2
    90.2-  97.5   +   30      +   26      +4   -
    98.6-  99.7   +    9      +   11      -2   -
   101.2- 102.8   +   13      +   13      +0   -
  across runs with NO hold: counter +84, taps +84, drift +0"""
    eq(B.parse_drift(out), dict(free_runs=3, drift=0, counter=84, miss=17, bad=20), "drift")

@case("flash_grid sweep: the best offset wins, not the first")
def _():
    out = """  best offsets (matched of 1137 file notes):
    a =  11.30   matched   881  (77.5%)
    a =  11.35   matched   880  (77.4%)"""
    eq(B.parse_sweep(out), dict(offset=11.30, matched=881, notes=1137, rate=77.5), "sweep")

@case("tick_verify output: overlapping holds merge into one region")
def _():
    out = """taps 830 + ticks 1444 = implied 2274  (expected 1450: off +824)
  hold   10.00..  11.00s  ticks 5
  hold   10.50..  12.00s  ticks 7
  hold   30.00..  31.00s  ticks 9"""
    r = B.parse_tick_verify(out)
    eq((r["holds"], r["regions"], r["match"]), (3, 2, False), "holds, regions, match")
    eq(r["spans"], [[10.0, 12.0], [30.0, 31.0]], "merged spans")

@case("a MATCH is recognised")
def _():
    r = B.parse_tick_verify("taps 441 + ticks 389 = implied 830  (expected 830: MATCH)\n"
                            "  hold   82.50..  82.85s  ticks 389")
    eq((r["taps"], r["ticks"], r["regions"], r["match"]), (441, 389, 1, True), "exact chart")

# ------------------------------------------------------------------------------ the pair rule

@case("a pair shares one bracket, so it is priced ONCE (Smells Like A Chocolate read 27 for 13)")
def _():
    rails = [dict(col=2, head=88.5, tail=93.1, ticks=141, why=None),
             dict(col=7, head=88.5, tail=93.1, ticks=141, why=None),
             dict(col=0, head=120.0, tail=121.0, ticks=None, why="reset")]
    cs = B.cluster_rails(rails)
    eq(len(cs), 2, "regions")
    eq([c["ticks"] for c in cs], [141, None], "one price per region, unpriced stays unpriced")
    eq(sum(c["ticks"] for c in cs if c["ticks"]), 141, "the pair is not counted twice")

@case("rails that merely touch are still one region; a real gap is two")
def _():
    eq(len(B.cluster_rails([dict(col=0, head=10.0, tail=11.0, ticks=5, why=None),
                            dict(col=1, head=11.02, tail=12.0, ticks=6, why=None)])), 1, "touching")
    eq(len(B.cluster_rails([dict(col=0, head=10.0, tail=11.0, ticks=5, why=None),
                            dict(col=1, head=11.5, tail=12.0, ticks=6, why=None)])), 2, "apart")

# --------------------------------------------------------------- reading a Nevsister title

@case("the rerate note is in parentheses and is NOT a chart code (1949 D22 got a side once)")
def _():
    song, codes, stype = F.codes_and_name("1949 D22 (pre D21 → D22 / Phoenix Modified ver.)")
    eq(codes, [("D", 22)], "one code, not three")
    eq(song, "1949", "song name")
    eq(stype, None, "arcade")

@case("a split screen gives two codes, and the song name stops at the first")
def _():
    song, codes, stype = F.codes_and_name("Slam(슬램) S18 & S20 (pre S19 → S20 / Phoenix Modified ver.)")
    eq(codes, [("S", 18), ("S", 20)], "both codes")
    eq(song, "slam", "the Korean gloss is not part of the name")

@case("a full song is not the arcade song of the same name (8 6 took the arcade's video)")
def _():
    a = F.codes_and_name("8 6(86) - FULL SONG - S15 & S21 (pre ...)")
    b = F.codes_and_name("8 6 (86) S16 & S20 | S20 GIMMICK LV.7 TITLE")
    eq(a[2], "FullSong", "full song marker")
    eq(b[2], None, "arcade has no marker")
    eq(a[0], b[0], "the names normalise the same - only the song type separates them")

@case("only the eras that are our catalog are read at all")
def _():
    eq(F.MIX_OF["PHOENIX 2"], "Phoenix2", "phoenix 2 maps to its mix")
    assert "RISE" not in F.ERA_RANK, "RISE is a different game on 5K/6K pads"
    assert F.ERA_RANK["PHOENIX 2"] > F.ERA_RANK["PHOENIX"] > F.ERA_RANK["XX"], "era order"

@case("an untagged upload is not a chart run")
def _():
    eq(F.TAG.match("EXC의 의도를 개무시하고 졸렬하게 클리어만 한 Legendary Dominion S25"), None, "player clip")
    assert F.TAG.match("[PUMP IT UP PHOENIX] 1949 D22"), "produced series"

# ------------------------------------------------------------- the plumbing every loop leans on

def _scratch():
    import tempfile
    return tempfile.TemporaryDirectory(prefix="piu-selftest-")

@case("an atomic write is byte for byte the plain write it replaced (CRLF, indent, unicode)")
def _():
    import json
    import atomicio as A
    doc = [{"chart": "Séance D21", "t": 0.1 + 0.2, "rows": [1, None, "x"]}, {"n": 10 ** 20}]
    with _scratch() as d:
        a, b = os.path.join(d, "a.json"), os.path.join(d, "b.json")
        for kw in (dict(), dict(indent=1), dict(indent=0), dict(ensure_ascii=False, indent=1)):
            json.dump(doc, open(a, "w", encoding="utf-8"), **kw)
            A.write_json(b, doc, encoding="utf-8", **kw)
            eq(open(b, "rb").read(), open(a, "rb").read(), "bytes with %s" % kw)
        json.dump(doc, open(a, "w"), indent=1)
        A.write_json(b, doc, indent=1)
        eq(open(b, "rb").read(), open(a, "rb").read(), "bytes with no encoding named")
        eq([f for f in os.listdir(d) if f.endswith(".tmp")], [], "no temp file left behind")

@case("a 0-byte, truncated or cut-short cache loads as MISSING, so the reader rebuilds it")
def _():
    import pickle
    import atomicio as A
    with _scratch() as d:
        p = os.path.join(d, "c.json")
        open(p, "w").close()
        eq(A.load_json(p, quiet=True), None, "0 bytes (the receptor field cache that broke Another Truth D19)")
        open(p, "w").write('{"y0": 50, "y1": 151, "xs": [1, 2')
        eq(A.load_json(p, quiet=True), None, "truncated JSON")
        open(p, "w").write('{"y0": 50, "y1": 151}')
        eq(A.load_json(p, required=("xs",), quiet=True), None, "no lanes")
        s = os.path.join(d, "s.jsonl")
        open(s, "w").write('[0.0, null, -1.0]\n[0.0167, 12, 0.9]\n[0.03')
        eq(A.read_jsonl(s, quiet=True), None, "a scan whose last line a kill cut short")
        open(s, "w").write('[0.0, null, -1.0]\n[0.0167, 12, 0.9]\n')
        eq(len(A.read_jsonl(s, quiet=True)), 2, "a legacy scan with no sidecar is trusted when it parses")
        k = os.path.join(d, "p.pkl")
        open(k, "wb").write(pickle.dumps((1, 2, 3))[:-3])
        eq(A.load_pickle(k, quiet=True), None, "a truncated pickle")

@case("a stream appears under its name only complete, sealed by a sidecar it must match")
def _():
    import atomicio as A
    with _scratch() as d:
        p = os.path.join(d, "v.C.jsonl")
        try:
            with A.StreamWriter(p, encoding="utf-8") as out:
                out.write("[0.0, 5, 0.9]\n")
                raise KeyError("killed")
        except KeyError:
            pass
        eq((os.path.exists(p), os.path.exists(p + ".partial")), (False, False), "an interrupted stream leaves nothing")
        with A.StreamWriter(p, encoding="utf-8", tool="selftest") as out:
            out.write("[0.0, 5, 0.9]\n[0.1, 6, 0.9]\n")
        side = A.load_json(A.done_path(p))
        eq((side["lines"], side["complete"], side["tool"]), (2, True, "selftest"), "sidecar")
        eq(A.jsonl_status(p), ("ok", "sealed"), "sealed scan")
        open(p, "a").write("[0.2, 7, 0.9]\n")
        eq(A.jsonl_status(p)[0], "broken", "a scan changed after its sidecar")

@case("a cache key keeps its old name until a parameter moves, then gets its own")
def _():
    import cachekey as K
    legacy, p = "work/x/v.C.10.pkl", dict(floor0=0.36, top=20, code="abc")
    eq(K.keyed(legacy, ".pkl", p, dict(p)), legacy, "today's parameters keep today's name")
    moved = K.keyed(legacy, ".pkl", dict(p, floor0=0.30), p)
    assert moved.startswith("work/x/v.C.10.k") and moved.endswith(".pkl"), moved
    eq(moved, K.keyed(legacy, ".pkl", dict(p, floor0=0.30), p), "the same parameters, the same name")
    assert K.keyed(legacy, ".pkl", dict(p, floor0=0.31), p) != moved, "different parameters, different names"

@case("a code stamp moves with what the code does, not with its comments or docstrings")
def _():
    import ast
    import cachekey as K

    def dump(src):
        return ast.dump(K._strip_docstrings(ast.parse(src)), annotate_fields=True, include_attributes=False)
    a = dump("def f(x):\n    'doc'\n    return x + 1  # one\n")
    eq(a, dump("def f(x):\n    '''another doc'''\n    # a comment\n\n    return x + 1\n"), "comments and docstrings")
    assert a != dump("def f(x):\n    return x + 2\n"), "a change in behaviour moves it"

# The code stamps the caches are keyed by, as this tree has them. A change that moves one re-keys
# that cache: every file of it is rebuilt on next use (the sprite passes are ~7 hours of decode).
# If that is what you meant, update THIS table - never the *_LEGACY constants in the tools, which
# name the code that built the files already on disk.
STAMPS = {"sprite pass": "07ad33cd18424a1f", "sprite pass (REFINE)": "4a282a4304ba5a4f",
          "receptor templates": "649e1dd5d2df7ffd", "field fit": "627dede7f324b0d4",
          "geometry fit": "bdff825d611c5d9d", "counter scan": "803798f1465b18f4"}

@case("no change re-keys a cache without saying so (the stamps the caches were built under)")
def _():
    import cachekey as K
    import combo_reader as C
    import note_extract as N
    import receptors as R
    import sprites as S
    refine = N.REFINE
    try:
        N.REFINE = False
        now = {"sprite pass": N._pass_code()}
        N.REFINE = True
        now["sprite pass (REFINE)"] = N._pass_code()
    finally:
        N.REFINE = refine
    now.update({"receptor templates": K.code_stamp(S._anchor_templates, S.crop, S.highpass),
                "field fit": K.code_stamp(R._fit_field, R._mirror_axis),
                "geometry fit": K.code_stamp(R._fit_geometry),
                "counter scan": K.code_stamp(C._frames, C.read_frame, C.find_label, C.digit_boxes,
                                             C.norm_glyph, C.classify, C.load_atlas)})
    eq(now, STAMPS, "code stamps")

@case("today's parameters reproduce the old cache names exactly; a moved floor, box or band does not")
def _():
    import note_extract as N
    import receptors as R
    import sprites as S
    xs = [301, 369, 437, 505, 573, 641, 709, 777, 845, 913]
    tw, th = S.size_for(68.0)
    p = N._pass_params("-1XV99_DVrc", "C", "1p", 10, 236.9, 1.0, round(0.36 * 1.0, 3), 50, 151, xs, th, tw, "", 720)
    eq(os.path.basename(N.pass_path(p)), "-1XV99_DVrc.C.1p.10.0.50.0.50.50.h0.00.r0.00.s1.00.236.9.x301-913.pkl",
       "sprite pass name")
    uneven = xs[:4] + [xs[4] + 6] + xs[5:]
    for moved in (dict(floor0=0.30), dict(top=24), dict(th=th + 2, tw=tw + 2), dict(y0=48), dict(field="x.field.json"),
                  dict(xs=uneven), dict(frame_h=1080), dict(reference=60.0)):
        assert ".k" in os.path.basename(N.pass_path(dict(p, **moved))), "pass keyed on %s" % moved
    eq(os.path.basename(S.anchors_path("-1XV99_DVrc.1p", "C", 50, 151, xs, th, tw)),
       "-1XV99_DVrc.1p.C.10.p50.h0.00.r0.00.x301-913.sprites.npz", "template name")
    assert ".k" in S.anchors_path("-1XV99_DVrc.1p", "C", 50, 151, xs, th + 2, tw + 2), "templates keyed on the box"
    assert ".k" in S.anchors_path("-1XV99_DVrc.1p", "C", 40, 141, xs, th, tw), "templates keyed on the band's rows"
    assert ".k" in S.anchors_path("-1XV99_DVrc.1p", "C", 50, 151, uneven, th, tw), "templates keyed on the inner lanes"
    assert ".k" in S.anchors_path("-1XV99_DVrc.1p", "C", 50, 151, xs, th, tw, field_key="x"), "keyed on the field fit"
    eq(os.path.basename(R.field_path("-1XV99_DVrc", "C", 10, "1p")), "-1XV99_DVrc.C.10.1p.inset.field.json", "field name")
    eq(R.field_key("-1XV99_DVrc", "C", 10, "1p"), "", "today's field fit is the plain one")
    assert ".k" in R.field_path("-1XV99_DVrc", "C", 10, "1p", n=32), "a field fit on other frames is keyed"

@case("a commit is checked: exactly the declared file, HEAD one commit on, and a refusal stops the pass")
def _():
    import subprocess
    import gitcommit as G
    with _scratch() as d:
        def run(*a):
            return subprocess.run(["git"] + list(a), cwd=d, capture_output=True, text=True, check=True)
        run("init", "-q")
        run("config", "user.email", "selftest@example.invalid")
        run("config", "user.name", "selftest")
        run("config", "commit.gpgsign", "false")
        for n in ("a.txt", "b.txt"):
            open(os.path.join(d, n), "w").write("one\n")
        run("add", "a.txt", "b.txt")
        run("commit", "-q", "-m", "seed")
        open(os.path.join(d, "a.txt"), "w").write("two\n")
        open(os.path.join(d, "b.txt"), "w").write("two\n")
        run("add", "b.txt")                                   # someone else's staged change
        G.commit_exactly(d, [os.path.join(d, "a.txt")], "Fix a\n")
        eq(run("show", "--name-only", "--format=", "HEAD").stdout.split(), ["a.txt"], "the commit carries a.txt alone")
        try:
            G.commit_exactly(d, ["a.txt"], "nothing to commit\n")
            raise AssertionError("a commit git refused was taken for a commit")
        except G.CommitError:
            pass

@case("a read-only phase cannot open a file for writing")
def _():
    import subprocess
    with _scratch() as d:
        target = os.path.join(d, "cache.json")
        open(target, "w").write("{}")
        code = ("import sys; sys.path.insert(0, %r); import atomicio; atomicio.forbid_writes()\n"
                "try:\n    open(%r, 'w')\nexcept PermissionError:\n    sys.exit(7)\n") % (
                    os.path.dirname(os.path.abspath(__file__)), target)
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
        eq(r.returncode, 7, "the open was refused")
        eq(open(target).read(), "{}", "and the file was not truncated")

def main():
    failed = []
    for name, fn in CASES:
        try:
            fn()
            print(f"  ok    {name}")
        except Exception as e:                      # noqa: BLE001 - an error is a failure too
            failed.append((name, e))
            print(f"  FAIL  {name}\n          {type(e).__name__ if not isinstance(e, AssertionError) else ''} {e}")
    print(f"\n{len(CASES) - len(failed)} of {len(CASES)} passed")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
