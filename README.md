# PiuScoresStepfiles

**The source of truth for the stepfiles behind PIU Scores chart analysis.** The annotation
pipeline reads `simfiles/`; external sources — community packs, chart videos, game patches —
are *evidence* for changing these files (or adding new charts), never truth themselves. Every
change is a commit that names its evidence, so the whole corpus has a reviewable history.

Also the custody home for the current annotated snapshot, so the live `/Admin/PiuCenter` batch
isn't a single file in someone's Downloads folder.

## Layout

| Path | What |
|---|---|
| `simfiles/` | **The canonical .ssc corpus** (658 files, pack-relative `<pack>/<song>/<file>.ssc`, covering all 4,574 matched official charts P1∪P2). Seeded unmodified from public [rayden-61/PIU-Simfiles](https://github.com/rayden-61/PIU-Simfiles) @ `cff495bd` (packs 01–17; the Phoenix 2 files are the Resistance's, published through that repo). Fixes edit in place — `git diff` is the review surface. See `simfiles/README.md`. |
| `snapshots/` | The current upload zip + its provenance note. Exactly one "current" zip; superseded ones are deleted from HEAD (history keeps them). |
| `sources/` | Evidence and worklists: the corpus manifest, the 121-chart repair census (`stepfile-video-census-*.csv`, `ssc-map.json`), footage worklist (`video-map.json`), and the per-chart certification ledger. |
| `tools/` | Operator scripts: footage downloader, result-screen certifier, extraction tooling. Run with the `../piu-annotate/.venv` Python. |
| `videos/` | Downloaded source footage. **Gitignored** — footage is never committed. |
| `work/` | Extraction scratch (frames, intermediate JSON). Gitignored. |

## The repair loop

Evidence (certified footage per chart) → transcribe/correct the block in `simfiles/` → commit
citing the evidence → re-run the piu-annotate pipeline over `simfiles/` (P1+P2 together —
badges are corpus-relative) → `package_snapshot.py` → new zip into `snapshots/` → upload on
`/Admin/PiuCenter`. The gate for any corrected block: implied judged total (tap rows + tick
sum) reconciles with the game's `ChartMix.NoteCount` (within 1%; exact where footage certifies
exact).

## Ground rules

- Downloaded footage is never committed.
- Corpus changes always cite evidence in the commit message.
- The snapshot zip is derived analysis data in the piucenter format (the same shape
  piucenter.com has published for years), regenerated on demand by the pipeline.
