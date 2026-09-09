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

def main():
    failed = []
    for name, fn in CASES:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as e:
            failed.append((name, e))
            print(f"  FAIL  {name}\n          {e}")
    print(f"\n{len(CASES) - len(failed)} of {len(CASES)} passed")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
