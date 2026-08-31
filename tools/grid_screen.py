# Does the file's TAP GRID agree with the chart the player actually played?
#
# A tick repair can only work when the file's note grid matches the video. When it
# does not -- a different chart revision -- the combo counter falls progressively
# behind the file's own tap schedule, and no tick authoring can fix that; the chart
# needs re-stepping from footage. This is the check that disqualified Another Truth
# D21, Can-can D17, Extravaganza D16, Conflict S22 and Naissance S20.
#
# It reads the assembled cumulative anchors, so run it AFTER assembly with the offset
# fit2/align settled on. Do not let it choose its own offset: sweeping for the offset
# that minimises drift will always find one, and the answer becomes self-fulfilling.
#
# The invariant is one-sided. slack = combo - taps-so-far counts the hold ticks the
# counter has banked, so on a tick-heavy chart it RISES steadily and that is healthy --
# judging the trend alone calls a good chart broken (Emperor S16 climbs to +270 and is
# verified correct). What cannot happen is slack going negative: that says the file
# scheduled taps the counter never registered, and a tap the game does not judge is
# not a tick problem. So the signal is the MINIMUM, and its depth is roughly how many
# events the file carries that the game never judged.
#
#   python -X utf8 tools/grid_screen.py <chartName> <videoId> <band> <offset>
import bisect
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def main():
    name, vid, band, a = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key = smap[name]["key"]
    anchors = json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json"), encoding="utf-8"))

    taps = []
    with open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n = sum(1 for ch in r["Line"].lstrip("`") if ch == "1")
            if n:
                taps.append((float(r["Time"]), n))
    times, cum, s = [t for t, _ in taps], [], 0
    for _, n in taps:
        s += n
        cum.append(s)
    def taps_before(ct):
        i = bisect.bisect_right(times, ct)
        return cum[i - 1] if i else 0

    zones = {}
    for t0, _, c in anchors:
        ct = t0 - a
        zones.setdefault(int(ct // 15) * 15, []).append(c - taps_before(ct))
    print(f"{name}  (offset {a}, {len(anchors)} anchors, {cum[-1]} taps in file)")
    print(f"{'chart secs':>12}  {'slack min':>9} {'max':>6}  n")
    ks = sorted(zones)
    mins = []
    for k in ks:
        v = zones[k]
        mins.append(min(v))
        print(f"{k:>7}-{k+15:<4}  {min(v):>9} {max(v):>6}  {len(v)}")
    worst = min(mins + [0])
    # Where the negativity sits decides what it means. A blind stretch of the counter
    # curve starves one early zone and then recovers once reads resume -- Tales of
    # Pumpnia D21 dips to -31 in its unread head and is a verified exact fix. A wrong
    # grid never recovers: every unjudged tap the file schedules is still owed, so the
    # deficit only deepens (Can-can D17 walks -9 -> -48, Naissance S20 -15 -> -255).
    head = max(1, len(mins) // 5)
    tail_worst = min(mins[head:]) if len(mins) > head else 0
    if worst >= -15:
        verdict = "GRID OK - tick repair is valid"
    elif tail_worst >= -35:
        verdict = (f"GRID OK past the head - dips to {worst} early then recovers, which reads as a "
                   "blind stretch of the counter rather than a bad grid; check that zone has reads")
    elif tail_worst > min(mins[head:][:max(1, (len(mins) - head) // 2)] or [0]):
        verdict = (f"GRID SUSPECT - stays negative to {tail_worst} without deepening; assemble more "
                   "of the curve before trusting a repair")
    else:
        verdict = (f"GRID MISMATCH - deficit deepens to {worst} and never recovers; the file carries "
                   f"~{-worst} taps the game never judged. RE-STEP, do not re-tick")
    print(f"\nworst slack {worst:+d} (past head: {tail_worst:+d})  =>  {verdict}")

if __name__ == "__main__":
    main()
