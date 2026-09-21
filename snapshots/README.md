# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-092126.zip` | 2026-09-21 (release `p2-092126`, a full clean rebuild) | 4,641 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `stepfiles/` (the 664-file `.ssc` corpus) + `version.txt` = `092126` | **Adds the six Phoenix 2 v1.01 songs — 59 charts** (Ghost Bloody Train 9, The Stranger 13, CALL ME BACK 11, DIE ANOTHER DAY 10, L (PIU Edit) 7, Can I friend you on Bassbook? lol 9), the first analysis those charts have had. Carries all **106** census repairs, verified file == shipped == judged by `tools/verify_release.py`, and the zip itself is clean under `tools/verify_zip.py`: zero dropped against `090326`, 59 added, `stepfiles/` byte-identical to `simfiles/`. Of the 4,582 charts shared with `090326`, **17 changed and no others**: the 14 repairs landed since (9 census, 5 from the tail loop) and The Resistance's three v1.01.0 fixes — Fracture Temporelle D26 (the missing note; the file now converts to the game's 1500), Digitalis D24 and 404 (New Era) S16 (arrows on the wrong panels). On every other shared chart the rebuild reproduced `090326` exactly, limb labels included. A simulation of `PiuCenterCrawlSaga.TryMatch` over the uploaded catalog batch auto-matches all 59 new keys ("ONF (온앤오프)" through the trailing-parenthetical fallback), so no alias work is expected. 32.6 MB. `*`-restoring key fix applied (73 keys). ⚠ The importer matches every key against the **Phoenix 2** catalog, so the six songs must be in production's chart list before this is uploaded — they are the 2026-09-03 catalog batch, which the owner uploaded on 2026-09-12. |

`090326` was uploaded on 2026-09-05, which is why this batch carries a new stamp:
`version.txt` is what `/Admin/PiuCenter` compares. (`083126` never was uploaded, and was
repackaged in place twice at the same stamp for that reason.)

Rules: exactly one current zip at HEAD; when a new batch is packaged, add the new zip, update
this table, delete the old one from HEAD (git history keeps it). The version string must parse
as a decimal and exceed the previous (MMDDYY convention: 083126 > 082626 > 050726).

## Rebuilding

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
