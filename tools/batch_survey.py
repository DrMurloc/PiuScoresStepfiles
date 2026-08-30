# Surveys a list of census charts end-to-end up to the authoring step: scans the
# video's combo counter (band by chart type + certified side), assembles anchors,
# fits the schedule offset, and reports fit quality + closure. The report classifies
# each chart: OK (patch-ready), PINS (blind windows need manual frame pins),
# SUSPECT (offset violations — arrows may be a different cut; park for re-step).
#
#   python tools/batch_survey.py "<chart>" ["<chart>" ...]
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

def band_for(chart_row, side):
    return "C" if chart_row["p1"].startswith("D") else {"1p": "L", "2p": "R"}[side]

def main():
    census = {r["chart"]: r for r in json.load(open(os.path.join(ROOT, "sources", "census-final.json"), encoding="utf-8"))}
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    led = json.load(open(os.path.join(ROOT, "work", "certification.json"), encoding="utf-8"))
    report = []
    for name in sys.argv[1:]:
      try:
        r = census[name]
        vid = r["video"].rsplit("/", 1)[1]
        cert = (led.get(vid, {}).get("charts") or {}).get(name, {})
        if cert.get("verdict") != "CERTIFIED":
            report.append((name, "NOT-CERTIFIED", "")); continue
      # noqa
        side = cert["side"]
        band = band_for(r, side)
        jsonl = os.path.join(ROOT, "work", "combo", vid + ".jsonl")
        band_mark = jsonl + f".band-{band}"
        if not (os.path.exists(jsonl) and os.path.exists(band_mark)):
            print(f"[scan] {name} ({vid}, band {band})", flush=True)
            subprocess.run([PY, os.path.join(ROOT, "tools", "combo_reader.py"), "--scan", vid, f"side={band}"], check=True)
            for p in [band_mark] + [jsonl + f".band-{b}" for b in "CLR" if b != band]:
                if p.endswith(f"band-{band}"):
                    open(p, "w").write("")
                elif os.path.exists(p):
                    os.remove(p)
        subprocess.run([PY, os.path.join(ROOT, "tools", "curve_assembler.py"), vid], check=True, capture_output=True)
        out = subprocess.run([PY, os.path.join(ROOT, "tools", "align_schedule.py"), vid, smap[name]["key"], str(r["judged"])],
                             capture_output=True, text=True).stdout
        fit = viol = total = None
        for line in out.splitlines():
            if line.startswith("offset fit"):
                fit = line.split("a = ")[1].split("s")[0]
                viol = float(line.rsplit("score", 1)[1])
            if line.startswith("total observed ticks"):
                total = int(line.split(":")[1].split()[0])
        expect = r["judged"] - r["file_taps"]
        status = "SUSPECT" if viol and viol > 2 else ("OK" if total == expect else "PINS")
        report.append((name, status, f"offset {fit} viol {viol} observed {total} expect {expect}"))
        print(f"[{status}] {name}: offset {fit}, violations {viol}, ticks {total}/{expect}", flush=True)
      except Exception as e:
        report.append((name, "ERROR", str(e)[:80]))
        print(f"[ERROR] {name}: {e}", flush=True)
    print("\n=== SURVEY ===")
    for name, status, detail in report:
        print(f"{status:<14} {name:<48} {detail}")

if __name__ == "__main__":
    main()
