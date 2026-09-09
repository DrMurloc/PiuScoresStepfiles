# Walk a batch of charts through the whole repair chain unattended, and SHIP only what the
# evidence proves. Everything else parks with a machine-readable reason, for a human to look
# at later or never.
#
#   python -X utf8 tools/batch_repair.py <video-map.json> --survey [--limit N] [--only "<chart>"]
#   python -X utf8 tools/batch_repair.py <video-map.json> --author [--limit N] [--commit]
#
# --survey measures and classifies, touching nothing. --author edits, verifies and (with
# --commit) commits the charts the survey called shippable. Both write work/<tag>-report.json.
#
# THE GATE. Hitting the target total is necessary and NOT sufficient - Conflict S22 closed
# exactly on a distribution that was wrong (docs/EVIDENCE-RULES.md). A chart ships only when
# the total is exact AND the distribution is evidenced:
#
#   1. CERTIFIED   a result screen's P+G+Gd+B+M equals the catalog count, so the footage is
#                  provably this chart, and the play's miss/bad/maxcombo are known. When the
#                  screen instead agrees with the FILE and not the catalog, the .ssc is a
#                  faithful copy of an older revision - a footage problem, never an edit.
#   2. GRID CLEAN  run_drift is not NEGATIVE past the play's own misses - the file carries no
#                  taps the game refuses to judge. The test is ONE-SIDED on purpose: positive
#                  drift is the missing holds themselves, and a dropped hundred in the counter
#                  reads as +100, so a positive number is never evidence of a bad grid.
#   3. EVIDENCED   the rails on screen account for what the chart owes. rail_ticks prices each
#                  rail from the counter reads bracketing it, and the priced total must equal
#                  `judged - tap rows` within a few events. One region takes the remainder by
#                  closure; several regions must each carry their own measured price. An
#                  unpriced rail parks the chart - a remainder split by guess is not a repair.
#   4. EXACT       tick_verify re-runs the real converter: taps + ticks == the catalog count.
#
# The gate is deliberately biased to park. A parked chart costs nothing; a shipped chart with
# an invented interior looks right forever.
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"
LEDGER = os.path.join(ROOT, "work", "certification-tail.json")
TRAILER = "\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

def run(args, timeout=1800):
    """A tool run. Returns its stdout; tools print, they do not return values."""
    try:
        p = subprocess.run([PY, "-X", "utf8"] + args, cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return p.stdout or ""
    except subprocess.TimeoutExpired:
        return "TIMEOUT"

def tool(name, *rest, timeout=1800):
    return run([os.path.join("tools", name + ".py")] + [str(r) for r in rest], timeout=timeout)

# ---------------------------------------------------------------- reading the tools' output

def parse_tick_verify(out):
    m = re.search(r"taps (\d+) \+ ticks (\d+) = implied (\d+)", out)
    if not m:
        return None
    holds = [(float(a), float(b), int(t)) for a, b, t in
             re.findall(r"hold\s+([\d.]+)\.\.\s*([\d.]+)s\s+ticks (\d+)", out)]
    regs = []
    for t0, t1, _ in sorted(holds):
        if regs and t0 <= regs[-1][1] + 1e-6:
            regs[-1][1] = max(regs[-1][1], t1)
        else:
            regs.append([t0, t1])
    return dict(taps=int(m.group(1)), ticks=int(m.group(2)), implied=int(m.group(3)),
                holds=len(holds), regions=len(regs), spans=regs, match="MATCH" in out)

def parse_sweep(out):
    hits = [(int(m.group(2)), float(m.group(1)))
            for m in re.finditer(r"a =\s*([\d.]+)\s+matched\s+(\d+)", out)]
    total = int(m.group(1)) if (m := re.search(r"matched of (\d+) file notes", out)) else 0
    if not hits or not total:
        return None
    best, offset = max(hits)
    return dict(offset=offset, matched=best, notes=total, rate=round(100 * best / total, 1))

def parse_drift(out):
    rows = re.findall(r"^\s+[\d.]+-\s*[\d.]+\s+\+\s*\d+\s+\+\s*\d+\s+([+-]\d+)\s+(\S+)\s*$",
                      out, re.M)
    free = [int(d) for d, holds in rows if holds == "-"]
    m = re.search(r"across runs with NO hold: counter \+(\d+), taps \+(\d+), drift ([+-]\d+)", out)
    miss = int(m2.group(1)) if (m2 := re.search(r"play has (\d+) miss / (\d+) bad", out)) else None
    return dict(free_runs=len(free), drift=int(m.group(3)) if m else None,
                counter=int(m.group(1)) if m else 0, miss=miss,
                bad=int(m2.group(2)) if m2 else None)

def parse_rails(out):
    rails, priced = [], 0
    for m in re.finditer(r"^\s+col (\d+): video\s+([\d.]+)-\s*([\d.]+).*?\|\s*(.*)$", out, re.M):
        col, s0, e0, what = int(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)
        t = re.search(r"-> (-?\d+) ticks", what)
        rails.append(dict(col=col, head=s0, tail=e0, ticks=int(t.group(1)) if t else None,
                          why=None if t else ("reset" if "DROPS" in what else "no bracket")))
        priced += 1 if t else 0
    owed = int(m.group(1)) if (m := re.search(r"owed (-?\d+) hold events", out)) else None
    return dict(rails=rails, priced=priced, owed=owed)

def cluster_rails(rails):
    """Group rails that are held at the same time into one region.

    Two columns held together are ONE hold region and share one pair of bracketing counter
    reads, so rail_ticks reports the same tick count against each of them. Adding those up
    counts the region twice - Smells Like A Chocolate S3 reads 27 against the 13 it owes, and
    Solitary D17 reads 282 against 122. The region is the unit that gets priced, exactly as
    finale_ticks pins one, so a region takes ONE price and a region with no price at all is
    what parks a chart."""
    out = []
    for r in sorted(rails, key=lambda x: x["head"]):
        if out and r["head"] <= out[-1]["tail"] + 0.05:
            out[-1]["tail"] = max(out[-1]["tail"], r["tail"])
            out[-1]["members"].append(r)
        else:
            out.append(dict(head=r["head"], tail=r["tail"], members=[r]))
    for c in out:
        priced = [m["ticks"] for m in c["members"] if m["ticks"] is not None]
        c["ticks"] = max(priced) if priced else None
        c["why"] = None if priced else Counter(m["why"] for m in c["members"]).most_common(1)[0][0]
    return out

# --------------------------------------------------------------------------- prerequisites

def band_for(cert, side, name):
    """The reader's band: a split-screen video gives each side half the screen."""
    other = cert.get("2p" if side == "1p" else "1p") or {}
    return "C" if not other.get("judged") else ("L" if side == "1p" else "R")

def ensure_combo(vid, band):
    """The counter scan every pricing tool reads. Expensive, so it is cached on disk."""
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    if os.path.exists(path):
        return True
    tool("combo_reader", "--scan", vid, f"side={band}", timeout=3600)
    return os.path.exists(path)

def certify(vmap_path):
    """Certify every downloaded video in the batch. Ledger-cached; re-runs only what failed."""
    out = tool("result_reader", "--all", "--map", vmap_path, "--ledger", LEDGER, timeout=7200)
    m = re.search(r"certified (\d+) charts; open (\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

# ---------------------------------------------------------------------------- the gate

def survey_chart(name, entry, cert):
    """Measure one chart and say what would happen to it. Touches nothing."""
    r = dict(chart=name, chartId=entry.get("chartId"), shape=entry.get("shape"),
             target=entry["judged"], vid=cert.get("vid"), skin=cert.get("skin"))

    # the file first: it costs nothing, and it is what makes an uncertified chart legible
    tv = parse_tick_verify(tool("tick_verify", name, r["target"]))
    if not tv:
        return {**r, "verdict": "PARK", "reason": "converter could not read the block"}
    r.update(file_taps=tv["taps"], file_ticks=tv["ticks"], implied=tv["implied"],
             regions=tv["regions"], deficit=r["target"] - tv["implied"])

    ch = (cert.get("charts") or {}).get(name) or {}
    if ch.get("verdict") != "CERTIFIED":
        screen = max([v for v in (cert.get("1p", {}).get("judged"), cert.get("2p", {}).get("judged"))
                      if v] or [0])
        if cert.get("status") != "ok":
            why = f"no result screen in the footage ({cert.get('status', 'no read')})"
        elif abs(screen - tv["implied"]) <= 1:
            # the play and our file agree, and only the catalog dissents: the .ssc is a faithful
            # copy of an OLDER revision of this chart, which is a footage problem, not a repair
            why = (f"the footage judges {screen} and the file implies {tv['implied']} - they agree, "
                   f"and the catalog's {r['target']} does not. This file is an older revision and "
                   f"needs {'Phoenix-era' if r['skin'] == 'xx' else 'newer'} footage")
        else:
            why = (f"contradictory evidence: the footage judges {screen}, the file implies "
                   f"{tv['implied']}, the catalog says {r['target']}")
        return {**r, "verdict": "PARK", "screen": screen or None, "reason": why}
    r["side"] = ch.get("side")
    r["band"] = band_for(cert, ch.get("side") or "1p", name)

    if tv["match"]:
        return {**r, "verdict": "SKIP", "reason": "already exact"}
    if tv["taps"] > r["target"]:
        return {**r, "verdict": "PARK", "reason": f"more tap rows ({tv['taps']}) than the game judges"}

    if not ensure_combo(r["vid"], r["band"]):
        return {**r, "verdict": "PARK", "reason": "the combo counter would not scan (font or layout)"}

    sw = parse_sweep(tool("flash_grid", name, "--sweep"))
    if not sw or sw["rate"] < 55:
        return {**r, "verdict": "PARK", "reason": f"no offset fits the flashes ({sw['rate'] if sw else 0}% matched)"}
    r.update(offset=sw["offset"], flash_match=sw["rate"])

    dr = parse_drift(tool("run_drift", name, sw["offset"]))
    r.update(miss=dr["miss"], bad=dr["bad"], hold_free_runs=dr["free_runs"], drift=dr["drift"])
    # one-sided: only a file carrying taps the game never judged is a grid failure
    if dr["drift"] is not None and dr["drift"] < -((dr["miss"] or 0) + 3):
        return {**r, "verdict": "PARK",
                "reason": f"grid drifts {dr['drift']:+d} on {dr['miss']} misses - the file carries "
                          f"taps the game never judges, so this is a re-step"}

    owed = r["target"] - tv["taps"]              # every hold event the game judges
    rl = parse_rails(tool("rail_ticks", name, sw["offset"], "--min-len", "0.15"))
    regions = cluster_rails(rl["rails"])
    priced = [c for c in regions if c["ticks"] is not None]
    unpriced = [c for c in regions if c["ticks"] is None]
    total = sum(c["ticks"] for c in priced)
    tol = max(3, round(0.03 * owed))
    r.update(owed=owed, rails=len(rl["rails"]), rail_regions=len(regions), regions_priced=len(priced),
             rails_total=total, tol=tol)
    if not regions:
        return {**r, "verdict": "PARK", "reason": f"owes {owed} hold events and no rail is visible"}
    if unpriced:
        why = Counter(c["why"] for c in unpriced)
        return {**r, "verdict": "PARK",
                "reason": f"{len(unpriced)} of {len(regions)} hold regions unpriced ({dict(why)}) - "
                          f"the remainder would be split by guess"}
    if abs(total - owed) > tol:
        return {**r, "verdict": "PARK",
                "reason": f"the rails price to {total}, the chart owes {owed} - the events are not "
                          f"where the file's holds are"}
    if tv["regions"] == 1 and len(priced) == 1:
        return {**r, "verdict": "SHIP", "route": "closure",
                "reason": f"one hold region, its rail prices to {total} of {owed} owed"}
    if tv["regions"] == 0:
        return {**r, "verdict": "SHIP", "route": "rails",
                "reason": f"file has no holds; {len(priced)} hold regions priced from their own "
                          f"brackets, {total} of {owed} owed",
                "rail_list": [dict(col=m["col"], head=m["head"], tail=m["tail"], ticks=c["ticks"])
                              for c in priced for m in c["members"]]}
    # Several file regions, each needing its own price. The mapping is only allowed to be
    # mechanical: a measured hold must land in exactly ONE of the file's regions, and every
    # region must get one. Anything else - a hold the file does not have, or one that straddles
    # two - is a note-placement question, and pinning through it would write a distribution
    # that verifies and is still wrong.
    pins, unmapped = [], 0
    for c in priced:
        hit = [sp for sp in tv["spans"]
               if min(sp[1], c["tail"] - sw["offset"]) - max(sp[0], c["head"] - sw["offset"]) > -0.15]
        if len(hit) != 1:
            unmapped += 1
        else:
            pins.append(dict(t0=c["head"] - sw["offset"], t1=c["tail"] - sw["offset"], ticks=c["ticks"]))
    covered = {i for i, sp in enumerate(tv["spans"])
               for p in pins if min(sp[1], p["t1"]) - max(sp[0], p["t0"]) > -0.15}
    if unmapped or len(covered) < len(tv["spans"]):
        return {**r, "verdict": "PARK",
                "reason": f"{tv['regions']} hold regions: {len(covered)} carry a measured hold and "
                          f"{unmapped} measured holds match no single region - the rest would be "
                          f"a guess"}
    return {**r, "verdict": "SHIP", "route": "pins",
            "reason": f"{len(tv['spans'])} hold regions, each priced from its own rails "
                      f"({total} of {owed} owed)",
            "pins": pins}

# --------------------------------------------------------------------------------- authoring

def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True).stdout

def author_chart(rec, smap, commit):
    """Do the edit the survey called for, verify it, and keep it only if the converter agrees."""
    name = rec["chart"]
    ssc = os.path.join("simfiles", smap[name]["ssc_rel"].replace("/", os.sep))
    if rec["route"] == "closure":
        tool("finale_ticks", name, timeout=3600)
    elif rec["route"] == "pins":
        pp = os.path.join(ROOT, "work", "rails", f"{rec['vid']}-{name.replace(' ', '_').replace('/', '_')}-pins.json")
        os.makedirs(os.path.dirname(pp), exist_ok=True)
        json.dump(rec["pins"], open(pp, "w", encoding="utf-8"))
        tool("finale_ticks", name, "--pins-json", os.path.relpath(pp, ROOT), timeout=3600)
    else:
        rails = [dict(col=x["col"], head=x["head"], tail=x["tail"], ticks=x["ticks"]) for x in rec["rail_list"]]
        rp = os.path.join(ROOT, "work", "rails", f"{rec['vid']}-{name.replace(' ', '_').replace('/', '_')}.json")
        os.makedirs(os.path.dirname(rp), exist_ok=True)
        json.dump(rails, open(rp, "w", encoding="utf-8"))
        tool("apply_rails", name, rec["offset"], os.path.relpath(rp, ROOT), timeout=3600)
    out = tool("tick_verify", name, rec["target"])
    tv = parse_tick_verify(out)
    if not tv or not tv["match"]:
        git("checkout", "HEAD", "--", ssc)
        return {**rec, "verdict": "PARK", "authored": False,
                "reason": f"authored but the converter did not agree ({tv['implied'] if tv else '?'} "
                          f"vs {rec['target']}) - reverted"}
    rec = {**rec, "authored": True, "final_taps": tv["taps"], "final_ticks": tv["ticks"]}
    if commit:
        title = (f"{name}: {rec['reason']} "
                 f"(taps {tv['taps']} + ticks {tv['ticks']} = implied {tv['implied']})")
        git("add", ssc)
        git("commit", "-q", "-m", title + TRAILER)
        rec["commit"] = git("rev-parse", "--short", "HEAD").strip()
    return rec

def main():
    vmap_path = sys.argv[1]
    tag = os.path.basename(vmap_path).replace("-video-map.json", "")
    vmap = json.load(open(vmap_path, encoding="utf-8"))
    ledger = json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}
    if "--no-certify" not in sys.argv:
        n_cert, n_open = certify(vmap_path)
        print(f"certification: {n_cert} charts certified, {n_open} open\n", flush=True)
        ledger.update(json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {})
    only, limit = arg("--only"), arg("--limit")
    jobs = [(c["chart"], c, ledger.get(e["vid"], dict(vid=e["vid"])))
            for e in vmap for c in e["charts"] if not only or c["chart"] == only]
    if limit:
        jobs = jobs[:int(limit)]
    report_path = os.path.join(ROOT, "work", f"{tag}-report.json")
    authoring = "--author" in sys.argv
    prior = {r["chart"]: r for r in json.load(open(report_path, encoding="utf-8"))}         if authoring and os.path.exists(report_path) else {}
    smap = corpus_map.chart_map()
    out, t0 = [], time.time()
    for i, (name, entry, cert) in enumerate(jobs, 1):
        t1 = time.time()
        if authoring:
            rec = prior.get(name)
            if not rec or rec.get("verdict") != "SHIP":
                continue
            rec = author_chart(rec, smap, "--commit" in sys.argv)
        else:
            rec = survey_chart(name, entry, cert)
        rec["seconds"] = round(time.time() - t1, 1)
        out.append(rec)
        print(f"[{i}/{len(jobs)}] {rec['verdict']:<5} {name[:48]:<48} {rec.get('reason', '')[:70]} "
              f"({rec['seconds']}s)", flush=True)
        merged = {**prior, **{x["chart"]: x for x in out}} if authoring else {x["chart"]: x for x in out}
        json.dump(list(merged.values()), open(report_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print(f"\n{len(out)} charts in {time.time() - t0:.0f}s")
    print("verdicts:", dict(Counter(r["verdict"] for r in out)))
    print("park reasons:", dict(Counter(r["reason"].split(" (")[0].split(" - ")[0]
                                        for r in out if r["verdict"] == "PARK")))

if __name__ == "__main__":
    main()
