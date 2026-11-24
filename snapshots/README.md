# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-112426.zip` | 2026-11-24 (release `p2-112426`, built on `p2-092326`'s predictions via `tools/snapshot_reuse.py`, piu-annotate `piuscores-windows-port` at `e01246d`, the tick lattice) | 4,691 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `stepfiles/` (the 670-file `.ssc` corpus) + `version.txt` = `112426` | Adds the six Phoenix 2 v1.02 songs - Mephitz 9, Falling Stars 8, Until Defined 7, NEMONEMO 11, PHYSALIS 8, Assault TAXI 7, 50 charts, their first analysis anywhere - ingested through their own charts list (`sources/charts-lists/p2-phoenix2-v102-112426.json`), and one chart from The Resistance's Phoenix Recompilation Pack, K.O.A: Alice in Wonderworld - SHORT CUT - S9 (262 -> 502, the catalog count; the one whose trace audit is FLAT, docs/STATUS.md "Upstream, as of 2026-11-24"). Verified: `blast_radius` 1 of 4,641 shared charts moved (that one, ticks 76 -> 316, taps unchanged), 0 dropped, 50 added, nothing moved without an edit; `verify_release` 107/107, no census repair's tick total changed; `verify_zip --ticks` CLEAN. Zip against `092326`: notes, holds and limb labels identical on every shared chart but K.O.A S9; the corpus-relative fields move with fifty new charts in the corpus - "Similar charts" on 1,024 charts, "Segment metadata" (closest sections) on 2,201, the three-skill summary on 138; `tierlists.json` identical. 33.0 MB, 82 `*` keys restored (73 + Mephitz's nine, artist "litmus*"). Built in 38 minutes. |

`092326` (2026-09-23, the first tick-lattice release: hold-tick totals moved on 1,778 charts, the
72 re-authored and 12 reverted repairs, the loops' ten fixes) is superseded by `112426`; whether
it was uploaded is not known here, and `112426`'s stamp exceeds it either way. `092226`
(2026-09-21, the old hold-tick arithmetic) was superseded by `092326`. `092126` (the morning's full clean rebuild, 2 h 52 min) was pushed and superseded the same
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
    artifacts/accessible-stepcharts/p2-phoenix2-v101-092126.json \
    artifacts/accessible-stepcharts/p2-phoenix2-v102-112426.json
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
  update adds one small list (`p2-phoenix2-v101-092126.json` is the first, `p2-phoenix2-v102-112426.json`
  the second).

Then verify before shipping it — the release folder, the blast radius, and the zip itself:

```
cd ../PiuScoresStepfiles
python -X utf8 tools/blast_radius.py p2-<MMDDYY> p2-<previous> <previous snapshot commit>
python -X utf8 tools/verify_release.py p2-<MMDDYY> --old p2-<previous>
python -X utf8 tools/verify_zip.py snapshots/piucenter-snapshot-<MMDDYY>.zip --old <previous zip>
```
