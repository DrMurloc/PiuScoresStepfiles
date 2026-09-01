# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-083126.zip` | 2026-08-31 (rebuilt, release `p2-083126b`) | 4,582 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `stepfiles/` (the 658-file `.ssc` corpus) + `version.txt` = `083126` | **First batch built from this repo's `simfiles/` as the stepfile source of truth**, so it carries all 42 repaired hold-tick schedules (`sources/repairs.json`; every one verified file == shipped == judged by `tools/verify_release.py`, and re-checked inside the packaged zip). Hold-tick totals are identical to `082626` for all 4,532 other charts — the diff is exactly the repairs. Adds 8 charts the previous folder had never re-ingested (Come to Me S4/S6/S11, PANDORA S2/S4/S7/D6, STEP S7); drops none. `*`-restoring key fix applied (73 keys). ⚠ Upload order per the tracker project: the P2 chart-list switch (Chunk A) must be live first, and this upload is the one that owes the hold_share / arrows-payload features their data — it supersedes the never-uploaded `082626-stepfiles` zip. |

This zip was repackaged in place at the same version after seven more repairs landed. That
is only safe because it had not been uploaded: `version.txt` is what `/Admin/PiuCenter`
compares, a same-day rebuild cannot produce a higher MMDDYY, and re-importing an already-live
version would be a no-op. Once a version has been uploaded, a further batch needs a new stamp.

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
