# Regenerate one chart's chartstruct CSV from the .ssc in this tree, after a note-grid edit.
# Every tool here reads the chartstruct (Time / Beat / Line / Line with active holds), and the
# pipeline only rewrites it on a full ingest, so an edited hold is invisible until this runs.
# The previous CSV is kept as <key>.csv.pre-edit the first time. Extra pipeline columns
# (Comment, Limb annotation, Metadata) are carried over by row when the row count matches,
# otherwise left blank - none of the repair tools read them.
#
#   python -X utf8 tools/regen_chartstruct.py "<ssc path>" <BLOCK> <key>
import csv
import os
import shutil
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def main():
    path, block, key = sys.argv[1], sys.argv[2], sys.argv[3]
    out = os.path.join(CS_DIR, key + ".csv")
    sc = StepchartSSC.from_song_ssc_file(path, block)
    df, holdticks, msg = stepchart_ssc_to_chartstruct(sc)
    old_rows, old_cols = [], []
    if os.path.exists(out):
        with open(out, encoding="utf-8", newline="") as f:
            r = csv.reader(f); old_cols = next(r); old_rows = list(r)
        if not os.path.exists(out + ".pre-edit"):
            shutil.copy(out, out + ".pre-edit")
    cols = old_cols or list(df.columns)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for i, row in df.iterrows():
            rec = []
            for c in cols:
                if c in df.columns: rec.append(row[c])
                elif i < len(old_rows) and len(old_rows) == len(df): rec.append(old_rows[i][cols.index(c)])
                else: rec.append("")
            w.writerow(rec)
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    print(f"{key}: {len(df)} rows (was {len(old_rows)}), taps {taps}, hold segments {len(holdticks)}, "
          f"naive ticks {sum(round(t[2]) for t in holdticks)} -> {out}")

if __name__ == "__main__":
    main()
