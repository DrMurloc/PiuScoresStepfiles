# Surgical note-grid edits for evidence-determined chart repairs: add a hold or move
# a hold release inside one #NOTEDATA block, appending/subdividing measures as needed.
# Beats follow the SSC convention (4 beats per measure, row r of R = beat 4m + 4r/R).
#
#   python -X utf8 tools/edit_notes.py add-hold <ssc> <descTag> <col> <startBeat> <endBeat>
#   python -X utf8 tools/edit_notes.py move-release <ssc> <descTag> <col> <oldBeat> <newBeat>
import re
import sys

def find_block(text, desc_tag):
    code = desc_tag.rsplit("_", 1)[0]
    sections = text.split("#NOTEDATA:;")
    for i in range(1, len(sections)):
        if re.search(rf"#DESCRIPTION:{re.escape(code)};", sections[i]):
            return sections, i
    raise SystemExit(f"block {code} not found")

def parse_notes(section):
    m = re.search(r"#NOTES:\n?(.*?)\n?;", section, re.S)
    body = m.group(1)
    measures = []
    for chunk in body.split(","):
        rows = [r.strip() for r in chunk.strip().splitlines() if r.strip() and not r.strip().startswith("//")]
        measures.append(rows)
    return m.span(1), measures

def beat_to_pos(measures, beat, cols):
    mi = int(beat // 4)
    while mi >= len(measures):
        measures.append(["0" * cols] * 4)
    rows = measures[mi]
    frac = (beat - 4 * mi) / 4.0
    r = frac * len(rows)
    if abs(r - round(r)) > 1e-6:
        # subdivide to make the beat representable
        for need in (8, 12, 16, 24, 32, 48, 64, 96, 192):
            if need % len(rows) == 0 and abs(frac * need - round(frac * need)) < 1e-6:
                factor = need // len(rows)
                new = []
                for row in rows:
                    new.append(row)
                    new.extend(["0" * cols] * (factor - 1))
                measures[mi] = new
                rows = new
                r = frac * len(rows)
                break
        else:
            raise SystemExit(f"beat {beat} not representable")
    return mi, int(round(r))

def set_char(measures, beat, col, ch, cols):
    mi, r = beat_to_pos(measures, beat, cols)
    row = measures[mi][r]
    # a half-double block is SIX columns wide, and python slicing would silently APPEND
    # rather than fail when the column is out of range - which is how First Love D15 got a
    # hold on a seventh panel that does not exist (it crashed the pipeline's featurizer)
    if col >= len(row):
        raise SystemExit(f"column {col} is outside this block's {len(row)} panels (row {row!r} "
                         f"at beat {beat}). Chartstruct columns are PADDED for narrow styles: "
                         f"file column = chartstruct column - (10 - width) // 2.")
    measures[mi][r] = row[:col] + ch + row[col + 1:]

def main():
    op, path, tag, col = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    b1 = float(sys.argv[5])
    b2 = float(sys.argv[6]) if len(sys.argv) > 6 else b1
    text = open(path, encoding="utf-8", newline="").read()
    sections, i = find_block(text, tag)
    span, measures = parse_notes(sections[i])
    cols = len(measures[0][0])
    if op == "add-hold":
        set_char(measures, b1, col, "2", cols)
        set_char(measures, b2, col, "3", cols)
        # a column cannot tap inside its own hold: the old file wrote this hold as repeated
        # taps, and the converter refuses a hold laid over them - clear them
        cleared = 0
        for mi, rows in enumerate(measures):
            for r, row in enumerate(rows):
                beat = 4 * mi + 4 * r / len(rows)
                if len(row) > col and b1 + 1e-6 < beat < b2 - 1e-6 and row[col] != "0":
                    measures[mi][r] = row[:col] + "0" + row[col + 1:]
                    cleared += 1
        if cleared:
            print(f"  cleared {cleared} note(s) on col {col} inside the hold")
    elif op == "move-release":
        mi, r = beat_to_pos(measures, b1, cols)
        row = measures[mi][r]
        assert row[col] == "3", f"no release at beat {b1} col {col} (row {row})"
        measures[mi][r] = row[:col] + "0" + row[col + 1:]
        set_char(measures, b2, col, "3", cols)
    elif op == "remove":
        # a phantom: a note the file has that the game never judges (Slam S5's 193rd tap)
        mi, r = beat_to_pos(measures, b1, cols)
        row = measures[mi][r]
        assert len(row) > col and row[col] != "0", f"no note at beat {b1} col {col} (row {row})"
        measures[mi][r] = row[:col] + "0" + row[col + 1:]
    else:
        raise SystemExit("unknown op")
    body = "\n,\n".join("\n".join(rows) for rows in measures)
    sections[i] = sections[i][:span[0]] + body + sections[i][span[1]:]
    open(path, "w", encoding="utf-8", newline="").write("#NOTEDATA:;".join(sections))
    print(f"{op} col {col} {b1} -> {b2} done ({len(measures)} measures)")

if __name__ == "__main__":
    main()
