# Charts whose answer we know, re-derived from the footage every time the process changes.
#
# `rebuild_repairs` proves the FILES still convert to their note count. This proves the
# ANALYSIS still reaches the same conclusion about them - the offset it fits, the drift it
# measures, the rails it prices, and the verdict the gate reaches. The two are different
# failures: a repair can sit correct in the tree while a change to the reader quietly stops
# being able to derive it, and the next batch then parks everything.
#
# The set deliberately holds more PARKS than ships. A gate that loosens is the failure that
# actually costs something - it ships a guessed distribution that looks right forever - and
# only a chart that must NOT ship can catch that.
#
#   python -X utf8 tools/golden.py [--only "<chart>"]     check against sources/golden-charts.json
#   python -X utf8 tools/golden.py --record               re-measure and rewrite the expectations
#
# Needs the footage in videos/ and the certification ledgers; it is an operator test, like
# every other tool here.
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch_repair as B   # noqa: E402
import corpus_map          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "sources", "golden-charts.json")
# what has to stay the same. Anything not listed is free to change without failing a run.
FIELDS = ["verdict", "route", "cause", "offset", "flash_match", "miss", "drift",
          "owed", "rail_regions", "regions_priced", "rails_total", "implied", "file_taps"]

def cause_of(rec):
    """The park reason boiled down to the thing that caused it, so wording can change."""
    r = rec.get("reason", "")
    if rec["verdict"] != "PARK":
        return None
    for needle, tag in [("they agree, and the catalog", "older revision"),
                        ("contradictory evidence", "three-way disagreement"),
                        ("no result screen", "no result screen"),
                        ("no offset fits", "no offset fits"),
                        ("grid drifts", "re-step"),
                        ("hold regions unpriced", "region unpriced"),
                        ("no rail is visible", "no rail visible"),
                        ("the events are not where", "priced total disagrees"),
                        ("carry a measured hold", "game holds where the file does not"),
                        ("more tap rows", "more taps than judged")]:
        if needle in r:
            return tag
    return r[:40]

def measure(name, target):
    cert = next((e for e in corpus_map.certification().values()
                 if name in (e.get("charts") or {})), {})
    rec = B.survey_chart(name, dict(judged=target, chartId=None, shape=None), cert)
    rec["cause"] = cause_of(rec)
    # A repaired chart stops at "already exact" and never reaches the pricing it was repaired
    # by, so the path that produced it would go unguarded. Measure it anyway: the offset the
    # flashes fit and the rails the counter prices are the evidence the repair was made from.
    if rec["verdict"] == "SKIP":
        sw = B.parse_sweep(B.tool("flash_grid", name, "--sweep"))
        if sw:
            rec["offset"], rec["flash_match"] = sw["offset"], sw["rate"]
            rl = B.parse_rails(B.tool("rail_ticks", name, sw["offset"], "--min-len", "0.15"))
            regs = B.cluster_rails(rl["rails"])
            priced = [c for c in regs if c["ticks"] is not None]
            rec.update(owed=rl["owed"], rail_regions=len(regs), regions_priced=len(priced),
                       rails_total=sum(c["ticks"] for c in priced))
    return rec

def main():
    doc = json.load(open(GOLDEN, encoding="utf-8"))
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    record = "--record" in sys.argv
    charts = [c for c in doc["charts"] if not only or c["chart"] == only]
    bad = 0
    for c in charts:
        got = measure(c["chart"], c["target"])
        if record:
            c["expect"] = {k: got.get(k) for k in FIELDS if got.get(k) is not None}
            print(f'  recorded {c["chart"]:<44} {got["verdict"]:<5} {got.get("cause") or got.get("route") or ""}')
            continue
        diffs = [(k, c["expect"].get(k), got.get(k)) for k in FIELDS
                 if k in c["expect"] and c["expect"][k] != got.get(k)]
        if diffs:
            bad += 1
            print(f'  FAIL  {c["chart"]}   ({c["why"]})')
            for k, want, gotv in diffs:
                print(f'          {k}: expected {want!r}, got {gotv!r}')
            if got.get("reason"):
                print(f'          it now says: {got["reason"][:96]}')
        else:
            print(f'  ok    {c["chart"]:<44} {got["verdict"]:<5} {got.get("cause") or got.get("route") or ""}')
    if record:
        json.dump(doc, open(GOLDEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\nrecorded {len(charts)} charts -> {os.path.relpath(GOLDEN, ROOT)}")
        return 0
    print(f"\n{len(charts) - bad} of {len(charts)} charts still analyse the same way")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
