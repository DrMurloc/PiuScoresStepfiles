# Re-survey the extraction loop's parks under the extractor as it stands, from cached sprite passes
# only, into a directory of its own - the step bucket #5 takes after the extractor changes (an
# accepted post-decode rule sees fewer extras, so charts the first run parked may now close).
#
#   python -X utf8 -B tools/park_resurvey.py survey --out work/<dir> [--from work] [--shard i/n] [--only "<chart>"] [--redo]
#   python -X utf8 -B tools/park_resurvey.py summary --out work/<dir>
#
# WHAT IT RUNS. extract_repair.survey_chart, unchanged, over every chart a run-1 report under
# --from parked (verdict PARK), with three things held down:
#   - nothing decodes: every frame read is refused (bench.no_decode), and a chart whose sprite pass
#     is not cached is NO_PASS before anything is read;
#   - nothing is written outside --out (atomicio.forbid_writes), and receptors.save_scan, which
#     shares a read's scan with the other tools, is a no-op here;
#   - only tail moves and tap->hold are ever applied. The plan's additions (add-tap, add-hold) are
#     withheld from the candidate and recorded; none is backed by the combo counter unless it sits
#     on one of the counter-backed notes bench.py knows (a +1/+2 counter step at the tap), and even
#     a backed one is not applied here. A chart whose candidate closes on the certified count
#     with tail/tap->hold edits alone is a SHIP_CANDIDATE; a chart the plan would only close with
#     additions goes to the needs-owner list (NEEDS_OWNER, with whether all the plan's edits
#     together would close it).
# Every record carries the git blob hash of tools/note_extract.py and the extractor's stamp
# (bench.extractor_stamp), so a record says which extractor read it.
#
# Nothing here commits. A ship candidate still goes through the loop's commit path and the gate
# (extract_repair.py commit re-runs tick_verify in place; corpus_grade's gate audits every ship),
# and a stepfile pass is refused while the gate's code (note_extract among it) differs from main's.
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import atomicio as A          # noqa: E402
import bench as B             # noqa: E402  (no_decode, BACKED, extractor_stamp)
import extract_repair as X    # noqa: E402
import guards                 # noqa: E402
import note_extract as NX     # noqa: E402
import receptors as R         # noqa: E402

ALLOWED = ("tail", "tap->hold")
ADDITIONS = ("add-tap", "add-hold")


def blob_hash(rel):
    r = subprocess.run(["git", "hash-object", rel], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def head():
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def parks(src):
    """chart -> its run-1 record, for every PARK in the extract-loop reports under `src`."""
    out = {}
    for f in sorted(os.listdir(src)):
        if f.startswith("extract-loop-report") and f.endswith(".json"):
            for r in json.load(open(os.path.join(src, f), encoding="utf-8")):
                if r.get("verdict") == "PARK":
                    out[r["chart"]] = r
    return out


def cached_pass(name):
    """(pass file from the repo root, None) when this chart's sprite pass is cached, else (None, why).
    Frame reads are refused, so asking never decodes."""
    try:
        vid, band, ncols, side, dur = NX.footage_of(name)
        ck = NX._pass_for(vid, band, ncols, side, dur)[4]
    except B.DecodeRefused:
        return None, "the read's templates or field fit are not cached (would decode)"
    except Exception as ex:
        return None, "%s: %s" % (type(ex).__name__, str(ex)[:120])
    if not os.path.exists(ck):
        return None, "no cached sprite pass"
    return os.path.relpath(ck, ROOT).replace(os.sep, "/"), None


def backed(chart, e):
    return any(n == chart and c == e["col"] and abs(t - e["head_t"]) <= 0.045 for n, t, c in B.BACKED)


def survey_one(entry):
    """extract_repair.survey_chart with the plan's additions withheld from what is applied."""
    withheld = []
    real_plan = X.plan

    def limited(notes, blk, a, b, flashes=None):
        edits, stats = real_plan(notes, blk, a, b, flashes)
        withheld[:] = [e for e in edits if e["kind"] not in ALLOWED]
        return [e for e in edits if e["kind"] in ALLOWED], stats
    X.plan = limited
    try:
        rec = X.survey_chart(entry)
    finally:
        X.plan = real_plan
    adds = [dict(e, backed=backed(entry["chart"], e)) for e in withheld if e["kind"] in ADDITIONS]
    rec["withheld"] = adds
    rec["verdict_run"] = rec["verdict"]
    if rec["verdict"] == "FAIL" and "DecodeRefused" in (rec.get("reason") or ""):
        return dict(rec, verdict="NO_PASS")
    x = rec.get("extraction")
    if rec["verdict"] in ("EXACT", "FAIL", "FOOTAGE_CORRUPT") or x is None:
        return rec
    if len(adds) > X.ADD_SHARE * x["file_notes"]:
        # the survey's own cap, on the plan as a whole: this many additions says the extraction is
        # not to be believed about this chart, whatever the rest of it closes on
        return dict(rec, verdict="PARK", reason="%d additions against %d notes - more than %.0f%% of the chart, not believed" % (
            len(adds), x["file_notes"], 100 * X.ADD_SHARE))
    if rec["verdict"] == "SHIP":
        return dict(rec, verdict="SHIP_CANDIDATE")
    below = x["recall"] < X.RECALL_BAR or x["precision"] < X.PRECISION_BAR
    if adds and not below:
        rec["full"] = full_plan(entry, rec, adds)
        return dict(rec, verdict="NEEDS_OWNER", reason="%d addition(s) withheld (%d unbacked by the counter); without them: %s" % (
            len(adds), sum(1 for e in adds if not e["backed"]), rec.get("reason")))
    return rec


def full_plan(entry, rec, adds):
    """Whether every edit the plan made, the withheld additions with them, would close the chart."""
    tag = X.block_tag(entry["key"])
    ssc = os.path.join(ROOT, "simfiles", *entry["ssc_rel"].split("/"))
    blk = X.load_block(ssc, tag)
    text = open(ssc, encoding="utf-8", newline="").read()
    pad = (blk["ncols"] - blk["width"]) // 2
    plan = [e for e in rec.get("edits", [])] + [{k: v for k, v in e.items() if k != "backed"} for e in adds]
    new_text, done, skipped, cleared = X.apply(text, tag, plan, pad, blk["width"])
    cand = os.path.join(X.OUT, "full-" + entry["key"] + ".ssc")
    A.write_text(cand, new_text, encoding="utf-8", newline="")
    after = X.load_block(cand, tag)
    if not after or after.get("error"):
        return dict(applied=len(done), skipped=len(skipped), error=(after or {}).get("error", "no block"))
    return dict(applied=len(done), skipped=len(skipped), implied=after["implied"], closes=after["implied"] == rec["expected"],
                off=after["implied"] - rec["expected"])


def report_path(out, shard):
    return os.path.join(out, "park-resurvey%s.json" % (("." + shard.split("/")[0]) if shard else ""))


def cmd_survey(args):
    out = os.path.abspath(args.out)
    if os.path.normcase(out) == os.path.normcase(os.path.join(ROOT, "work")):
        sys.exit("--out must be a directory of its own, never work/ itself (the extraction loop's reports live there)")
    os.makedirs(os.path.join(out, "extract-loop"), exist_ok=True)
    B.no_decode()
    A.forbid_writes([out])
    R.save_scan = lambda *a, **k: None
    NX.CACHE = True
    X.OUT_ROOT, X.OUT = out, os.path.join(out, "extract-loop")
    stamp = dict(note_extract_blob=blob_hash("tools/note_extract.py"), extractor_stamp=B.extractor_stamp(), head=head())
    src = os.path.abspath(args.src)
    run1 = parks(src)
    allc = X.charts()
    names = sorted(run1)
    if args.only:
        names = [n for n in names if n == args.only]
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        names = names[i::n]
    path = report_path(out, args.shard)
    prior = {} if args.redo or not os.path.exists(path) else {r["chart"]: r for r in json.load(open(path, encoding="utf-8"))}
    t0 = time.time()
    for k, name in enumerate(names, 1):
        if name in prior:
            continue
        t1 = time.time()
        entry = allc.get(name)
        base = dict(chart=name, run1_reason=run1[name].get("reason"), run1_diff=run1[name].get("diff"), **stamp)
        if entry is None:
            rec = dict(base, verdict="GONE", reason="no longer a certified chart in the map")
        elif guards.owner_revisit_skip(name, entry["key"]):
            rec = dict(base, verdict="SKIP", reason=guards.owner_revisit_skip(name, entry["key"]))
        else:
            ck, why = cached_pass(name)
            if ck is None:
                rec = dict(base, verdict="NO_PASS", reason=why)
            else:
                try:
                    rec = dict(base, pass_file=ck, **survey_one(entry))
                except B.DecodeRefused as ex:
                    rec = dict(base, verdict="NO_PASS", reason="a frame read was refused: %s" % ex)
                except Exception as ex:
                    rec = dict(base, verdict="FAIL", reason="%s: %s" % (type(ex).__name__, str(ex)[:160]))
        rec["seconds"] = round(time.time() - t1, 1)
        prior[name] = rec
        A.write_json(path, list(prior.values()), encoding="utf-8", ensure_ascii=False, indent=1)
        print("[%d/%d] %-14s %-46s %s (%ss)" % (k, len(names), rec["verdict"], name[:46], (rec.get("reason") or "")[:80],
                                                rec["seconds"]), flush=True)
    c = Counter(r["verdict"] for r in prior.values())
    print("\n%d charts in %.0fs; verdicts %s" % (len(names), time.time() - t0, dict(c)))
    print("VERDICT: %s" % " ".join("%s=%d" % kv for kv in sorted(c.items())))
    return 0


def cmd_summary(args):
    out = os.path.abspath(args.out)
    recs = []
    for f in sorted(os.listdir(out)):
        if f.startswith("park-resurvey") and f.endswith(".json") and f != "park-resurvey-summary.json":
            recs += json.load(open(os.path.join(out, f), encoding="utf-8"))
    by = Counter(r["verdict"] for r in recs)
    blobs = Counter(r.get("note_extract_blob") for r in recs)
    ships = sorted((r for r in recs if r["verdict"] == "SHIP_CANDIDATE"), key=lambda r: r["chart"])
    owner = sorted((r for r in recs if r["verdict"] == "NEEDS_OWNER"), key=lambda r: r["chart"])
    print("%d parks re-surveyed: %s" % (len(recs), dict(by)))
    print("note_extract blobs: %s" % dict(blobs))
    kinds = Counter()
    for r in ships:
        kinds.update(e["kind"] for e in X.applied(r))
    print("\nSHIP_CANDIDATE %d (edits applied: %s; with additions withheld: %d)" % (
        len(ships), dict(kinds), sum(1 for r in ships if r.get("withheld"))))
    for r in ships:
        print("  %-46s %s%s" % (r["chart"][:46], r["reason"][:90], " [%d additions withheld]" % len(r["withheld"]) if r.get("withheld") else ""))
    print("\nNEEDS_OWNER %d (additions unbacked: %d, backed: %d; the whole plan would close %d of them)" % (
        len(owner), sum(sum(1 for e in r["withheld"] if not e["backed"]) for r in owner),
        sum(sum(1 for e in r["withheld"] if e["backed"]) for r in owner), sum(1 for r in owner if (r.get("full") or {}).get("closes"))))
    for r in owner:
        f = r.get("full") or {}
        print("  %-46s %d add-tap %d add-hold%s; the whole plan: %s; file %d, certified %d" % (
            r["chart"][:46], sum(1 for e in r["withheld"] if e["kind"] == "add-tap"), sum(1 for e in r["withheld"] if e["kind"] == "add-hold"),
            " (%d backed)" % sum(1 for e in r["withheld"] if e["backed"]) if any(e["backed"] for e in r["withheld"]) else "",
            "closes" if f.get("closes") else ("off %+d" % f["off"] if "off" in f else f.get("error", "?")),
            (r.get("file") or {}).get("implied", -1), r.get("expected") or -1))
    summary = dict(total=len(recs), verdicts=dict(by), note_extract_blobs=dict(blobs),
                   ship_candidates=[dict(chart=r["chart"], key=r["key"], candidate=r.get("candidate"), reason=r["reason"],
                                         edits=dict(Counter(e["kind"] for e in X.applied(r))), withheld=len(r.get("withheld") or []),
                                         note_extract_blob=r.get("note_extract_blob")) for r in ships],
                   needs_owner=[dict(chart=r["chart"], key=r["key"], reason=r.get("reason"), additions=r["withheld"],
                                     full=r.get("full"), note_extract_blob=r.get("note_extract_blob")) for r in owner])
    A.write_json(os.path.join(out, "park-resurvey-summary.json"), summary, encoding="utf-8", ensure_ascii=False, indent=1)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="park_resurvey.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("survey")
    p.add_argument("--out", required=True)
    p.add_argument("--from", dest="src", default=os.path.join(ROOT, "work"))
    p.add_argument("--shard")
    p.add_argument("--only")
    p.add_argument("--redo", action="store_true")
    p = sub.add_parser("summary")
    p.add_argument("--out", required=True)
    args = ap.parse_args()
    os.chdir(ROOT)
    return dict(survey=cmd_survey, summary=cmd_summary)[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
