# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-090326.zip` | 2026-09-04 (release `p2-090326`; the stamp matches the release folder, named when the run started) | 4,582 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `stepfiles/` (the 658-file `.ssc` corpus) + `version.txt` = `090326` | Carries all **97** repaired charts (`sources/repairs.json`), every one verified file == shipped == judged by `tools/verify_release.py`. Coverage is identical to `083126` — 4,582 keys, zero dropped, zero added — and hold-tick totals moved on exactly 53 charts, all of them repairs, none outside. The other two repairs since `083126` are the phantom charts (Slam S5, Set me up S10), whose fix is a deleted arrow rather than a tick total: their `.ssc` inside the zip carries 192 and 274 tap rows, matching what the game judges. 32.2 MB. `*`-restoring key fix applied (73 keys). ⚠ The importer matches every key in this zip against the **Phoenix 2** catalog (`PiuCenterCrawlSaga.MatchCatalog`), because a key carries the chart's level and levels move between mixes — so the site's P2 chart list has to be current in production or keys silently fail to resolve. That constant shipped on 2026-08-26 (`86e4371a`); there is no separate step to perform. This upload is also the one that owes the hold-share and step-chart-failure-map features their data. |

`083126` was never uploaded, so it is superseded rather than followed: it was repackaged in
place twice at the same stamp for the same reason. Once a version *has* been uploaded, a
further batch needs a new stamp — `version.txt` is what `/Admin/PiuCenter` compares.

Rules: exactly one current zip at HEAD; when a new batch is packaged, add the new zip, update
this table, delete the old one from HEAD (git history keeps it). The version string must parse
as a decimal and exceed the previous (MMDDYY convention: 083126 > 082626 > 050726).

## Rebuilding

```
cd ../piu-annotate
SIMFILES=/c/Users/jonec/repos/PiuScoresStepfiles/simfiles/ ./run-pipeline-union.sh p2-<MMDDYY> \
    artifacts/accessible-stepcharts/050726-arroweclipse.json \
    artifacts/accessible-stepcharts/p2-phoenix2-082626.json
python package_snapshot.py p2-<MMDDYY> <MMDDYY> \
    C:\Users\jonec\repos\PiuScoresStepfiles\snapshots\piucenter-snapshot-<MMDDYY>.zip
```

Two things that are easy to get wrong, both learned the hard way on 2026-08-31:

- **Ingest the union of charts lists, not one list.** A release's coverage is every
  accessible-stepcharts list ever ingested into its folder. `p2-082626` shipped 4,574 charts
  while its own run log says its ingest matched 4,382 — the folder already held the Phoenix 1
  corpus and the P2 run layered onto it. Rebuilding from the P2 list alone silently drops 192
  charts (the licensed K-pop songs live only in the older list). `run-pipeline-union.sh` exists
  for this and prints its coverage after ingest; compare it against the previous release before
  packaging.
- **A fresh folder re-predicts every limb.** The old run finished in ~44 minutes because it
  reused cached predictions; a clean rebuild is ~75 minutes, most of it in stages 2-3.

Then verify before shipping it — the check reads the packaged release's own chart JSON:

```
cd ../PiuScoresStepfiles
python -X utf8 tools/verify_release.py p2-<MMDDYY> --old p2-<previous>
```
