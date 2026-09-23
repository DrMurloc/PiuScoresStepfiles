# Checks the PACKAGED zip - the thing that gets uploaded - rather than the release folder it
# was built from. verify_release reads the release folder; packaging then rewrites keys
# (the '*' restoration), walks simfiles/ a second time and stamps a version, and nothing
# looked at the result.
#
#   python -X utf8 tools/verify_zip.py snapshots/piucenter-snapshot-<MMDDYY>.zip [--old <previous.zip>]
#
# It checks that:
#   - version.txt is a decimal stamp, equal to the one in the file name, above --old's
#   - page-content carries its three files and chart-table names exactly the chart entries
#   - stepfiles/ is simfiles/ at HEAD's working tree, byte for byte, nothing missing or extra
#   - every chart json names a stepfile that is in the zip (the import joins on that path)
#   - every repair in sources/repairs.json ships its tick total: the chart json's
#     "Hold ticks" sums to the manifest's figure
#   - against --old: no chart dropped, and the added ones listed by song
#   - with --ticks: every chart's "Hold ticks", segment by segment, is what the installed
#     converter (the tick lattice) derives from the stepfile the zip banks - a release built
#     across a converter change carries the new arithmetic on every chart, not only the repairs
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$-_.+!*(),")


def true_key(meta):
    # package_snapshot.true_key: the chart key with '*' kept
    raw = "_".join([f'{meta["TITLE"]} - {meta["ARTIST"]}', meta["DESCRIPTION"], meta["SONGTYPE"]])
    return "".join(c for c in raw.replace(" ", "_").replace("/", "_") if c in OK)


def charts_of(z):
    return {n[:-5] for n in z.namelist() if "/" not in n and n.endswith(".json")}


def main():
    path = sys.argv[1]
    old_path = sys.argv[sys.argv.index("--old") + 1] if "--old" in sys.argv else None
    problems = []

    def check(ok, text):
        print(f"{'ok' if ok else '!!'}  {text}")
        if not ok:
            problems.append(text)

    z = zipfile.ZipFile(path)
    names = z.namelist()
    charts = charts_of(z)

    version = z.read("version.txt").decode().strip()
    stamp = re.search(r"(\d{6})\.zip$", os.path.basename(path))
    check(version.isdigit(), f"version.txt = {version!r} parses as a decimal")
    check(bool(stamp) and stamp.group(1) == version, "version.txt matches the stamp in the file name")

    pages = sorted(n for n in names if n.startswith("page-content/"))
    check(pages == ["page-content/chart-table.json", "page-content/stepchart-skills.json", "page-content/tierlists.json"],
          f"page-content has its three files ({len(pages)})")
    table = {r["name"] for r in json.loads(z.read("page-content/chart-table.json"))}
    check(table == charts, f"chart-table names exactly the {len(charts)} chart entries "
                           f"(table-only {len(table - charts)}, entry-only {len(charts - table)})")

    # stepfiles/ against the working tree
    shipped = {n[len("stepfiles/"):]: n for n in names if n.startswith("stepfiles/") and not n.endswith("/")}
    tree = {}
    sim = os.path.join(ROOT, "simfiles")
    for root, _, files in os.walk(sim):
        for f in files:
            if f.lower().endswith(".ssc"):
                full = os.path.join(root, f)
                tree[os.path.relpath(full, sim).replace(os.sep, "/")] = full
    check(set(shipped) == set(tree), f"stepfiles/ holds the same {len(tree)} files as simfiles/ "
                                     f"(missing {len(set(tree) - set(shipped))}, extra {len(set(shipped) - set(tree))})")
    differ = [rel for rel in set(shipped) & set(tree)
              if hashlib.sha1(z.read(shipped[rel])).digest() != hashlib.sha1(open(tree[rel], "rb").read()).digest()]
    check(not differ, f"every shipped stepfile is byte-identical to simfiles/ ({len(differ)} differ)")
    for rel in sorted(differ)[:10]:
        print(f"        {rel}")

    # every chart json: key rebuilds from its own metadata, and its stepfile is in the zip
    orphans, wrong_key, ticks_of = [], [], {}
    for key in charts:
        meta = json.loads(z.read(key + ".json"))[2]
        rel = meta["ssc_file"].replace("\\", "/").split("simfiles/")[-1]
        if rel not in shipped:
            orphans.append((key, rel))
        if true_key(meta) != key:
            wrong_key.append(key)
        ticks_of[key] = sum(int(round(t[2])) for t in (meta.get("Hold ticks") or []))
    check(not orphans, f"every chart json's ssc_file is in stepfiles/ ({len(orphans)} orphans)")
    for key, rel in orphans[:10]:
        print(f"        {key} -> {rel}")
    check(not wrong_key, f"every entry name is the key its own metadata rebuilds ({len(wrong_key)} differ)")
    for key in wrong_key[:10]:
        print(f"        {key}")

    # the repairs, read out of the zip
    repairs = json.load(open(os.path.join(ROOT, "sources", "repairs.json"), encoding="utf-8"))
    star = {k.replace("*", ""): k for k in charts if "*" in k}
    bad = []
    for r in repairs:
        key = r["key"] if r["key"] in charts else star.get(r["key"])
        if key is None:
            bad.append(f"{r['chart']}: not in the zip")
        elif ticks_of[key] != r["ticks"]:
            bad.append(f"{r['chart']}: zip ships {ticks_of[key]} ticks, manifest says {r['ticks']}")
    check(not bad, f"all {len(repairs)} repairs ship their tick total ({len(bad)} do not)")
    for b in bad[:10]:
        print(f"        {b}")

    if "--ticks" in sys.argv:
        # every chart's hold ticks, re-derived from the stepfile the zip banks with the installed
        # converter (which must count by the tick lattice): the release carries the arithmetic
        # the repairs were graded with, on every chart and not only the repaired ones
        sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
        from piu_annotate.formats import ssc_to_chartstruct as C
        from piu_annotate.formats.sscfile import StepchartSSC
        if getattr(C, "HOLD_TICK_MODEL", "legacy") != "lattice":
            sys.exit("--ticks needs piu-annotate's converter to count by the tick lattice")
        mismatch, failed, cache = [], [], {}
        for n, key in enumerate(sorted(charts), 1):
            meta = json.loads(z.read(key + ".json"))[2]
            rel = meta["ssc_file"].replace("\\", "/").split("simfiles/")[-1]
            tag = meta["DESCRIPTION"] + "_" + meta["SONGTYPE"]
            try:
                sc = StepchartSSC.from_song_ssc_file(tree[rel], tag)
                _, ht, _ = C.stepchart_ssc_to_chartstruct(sc)
                want = [[round(float(s), 4), round(float(e), 4), int(round(t))] for s, e, t in ht]
            except Exception as ex:
                failed.append(f"{key}: {type(ex).__name__}: {ex}"[:120])
                continue
            got = [[round(float(s), 4), round(float(e), 4), int(round(t))] for s, e, t in (meta.get("Hold ticks") or [])]
            if got != want:
                mismatch.append(f"{key}: zip {sum(t for _, _, t in got)} ticks in {len(got)} segments, "
                                f"converter {sum(t for _, _, t in want)} in {len(want)}")
            if n % 500 == 0:
                print(f"    ... {n} charts re-derived", flush=True)
        check(not mismatch and not failed, f"every chart's hold ticks are the converter's own, segment by segment "
                                           f"({len(mismatch)} differ, {len(failed)} could not be converted)")
        for m in (mismatch + failed)[:10]:
            print(f"        {m}")

    if old_path:
        oz = zipfile.ZipFile(old_path)
        old_charts, old_version = charts_of(oz), oz.read("version.txt").decode().strip()
        check(int(version) > int(old_version), f"version {version} exceeds the previous {old_version}")
        dropped, added = old_charts - charts, charts - old_charts
        check(not dropped, f"no chart dropped against {os.path.basename(old_path)} ({len(dropped)} dropped)")
        for k in sorted(dropped)[:10]:
            print(f"        {k}")
        by_song = defaultdict(int)
        for k in added:
            by_song[k.split("_-_")[0]] += 1
        print(f"    added {len(added)}: " + ", ".join(f"{s} {n}" for s, n in sorted(by_song.items())))

    print(f"\n{os.path.basename(path)}: {len(names)} entries, {len(charts)} charts, {len(shipped)} stepfiles, "
          f"{os.path.getsize(path) / 1048576:.1f} MB  -  {'CLEAN' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
