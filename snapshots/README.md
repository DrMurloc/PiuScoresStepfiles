# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-092326.zip` | 2026-09-23 (release `p2-092326`, built on `p2-092226`'s predictions with the 89 changed charts re-done, **the first release whose hold ticks are counted by the tick lattice** - piu-annotate `piuscores-windows-port` commit `e01246d`) | 4,641 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `stepfiles/` (the 664-file `.ssc` corpus) + `version.txt` = `092326` | Every chart's `Hold ticks` is now the game's arithmetic ([docs/EVIDENCE-RULES.md](../docs/EVIDENCE-RULES.md), "A staggered release is not a tick"): hold-tick totals moved on 1,778 charts, 1,766 of them by the converter alone (1,423 down, 343 up, median -2; Conflict D26 from 23,477 ticks inside a BPM gimmick to 402, exact). Of the 992 certified charts whose shipped ticks changed, 634 now derive their judged count exactly, 273 are closer, 84 are farther (files short on ticks that the old over-count had hidden). It also carries the 72 re-authored and 12 reverted repairs, and the loops' ten new fixes (eight extraction, two tick loop). Arrows and limbs changed only on the 13 charts whose notes were edited; eNPS on 9; skills on one chart-table row; `tierlists.json` identical. Verified: `blast_radius` 72 of 4,641 moved, none without an edit (the 11 edited files that moved nothing are schedules re-authored to keep their counts, re-ingested and checked); `verify_release` 107/107; `verify_zip --ticks` CLEAN - every chart's hold ticks equal the lattice converter's own derivation from the banked stepfile, segment by segment. 32.6 MB, 73 `*` keys restored. Built in 48 minutes via `tools/snapshot_reuse.py`. |

`092226` (2026-09-21, the old hold-tick arithmetic) is superseded by `092326`; whichever of them
went up last, `092326`'s stamp exceeds it. `092126` (the morning's full clean rebuild, 2 h 52 min) was pushed and superseded the same
day; whether it was uploaded in between is not known here, so `092226` carries a higher stamp
rather than a rebuild in place — `version.txt` is what `/Admin/PiuCenter` compares, and it
must exceed whatever went up last. `090326` was uploaded on 2026-09-05. (`083126` never was,
and was repackaged in place twice at the same stamp for that reason.)

Rules: exactly one current zip at HEAD; when a new batch is packaged, add the new zip, update
this table, delete the old one from HEAD (git history keeps it). The version string must parse
as a decimal and exceed the previous (MMDDYY convention: 083126 > 082626 > 050726).

## Rebuilding

Build from the `piuscores-windows-port` branch of the owner's fork of piu-annotate,
https://github.com/DrMurloc/piu-annotate (setup: docs/SNAPSHOT.md, "Setting up the clone"). Since `092326` the
converter counts hold ticks by the tick lattice, and a release built from upstream piu-annotate would carry the old
arithmetic on every chart.
`tools/snapshot_reuse.py` prepares a release that reuses the previous one's predictions (docs/SNAPSHOT.md).

```
cd ../piu-annotate
SIMFILES=/c/Users/jonec/repos/PiuScoresStepfiles/simfiles/ ./run-pipeline-union.sh p2-<MMDDYY> \
    artifacts/accessible-stepcharts/050726-arroweclipse.json \
    artifacts/accessible-stepcharts/p2-phoenix2-082626.json \
    artifacts/accessible-stepcharts/p2-phoenix2-v101-092126.json
python package_snapshot.py p2-<MMDDYY> <MMDDYY> \
    C:\Users\jonec\repos\PiuScoresStepfiles\snapshots\piucenter-snapshot-<MMDDYY>.zip
```

Three things that are easy to get wrong — the first two learned the hard way on 2026-08-31,
the third on 2026-09-21. The full runbook is [docs/SNAPSHOT.md](../docs/SNAPSHOT.md).

- **Ingest the union of charts lists, not one list.** A release's coverage is every
  accessible-stepcharts list ever ingested into its folder. `p2-082626` shipped 4,574 charts
  while its own run log says its ingest matched 4,382 — the folder already held the Phoenix 1
  corpus and the P2 run layered onto it. Rebuilding from the P2 list alone silently drops 192
  charts (the licensed K-pop songs live only in the older list). `run-pipeline-union.sh` exists
  for this and prints its coverage after ingest; compare it against the previous release before
  packaging.
- **A fresh folder re-predicts every limb.** The old run finished in ~44 minutes because it
  reused cached predictions; a clean rebuild is ~75 minutes, most of it in stages 2-3.
- **New songs need a charts list of their own.** The ingest converts only what a list names,
  so a stepfile added to `simfiles/` with no list row is skipped without a word. Each content
  update adds one small list (`p2-phoenix2-v101-092126.json` is the first).

Then verify before shipping it — the release folder, the blast radius, and the zip itself:

```
cd ../PiuScoresStepfiles
python -X utf8 tools/blast_radius.py p2-<MMDDYY> p2-<previous> <previous snapshot commit>
python -X utf8 tools/verify_release.py p2-<MMDDYY> --old p2-<previous>
python -X utf8 tools/verify_zip.py snapshots/piucenter-snapshot-<MMDDYY>.zip --old <previous zip>
```
