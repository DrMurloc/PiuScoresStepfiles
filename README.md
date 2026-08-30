# PiuScoresStepfiles

Custody repo for the PIU Scores chart-analysis inputs and outputs that previously lived in
Downloads folders and scratch checkouts. Two jobs:

1. **Our stepfile corrections, kept separate from The Resistance.** `overrides/` holds .ssc
   files we authored or corrected ourselves (transcribed from Phoenix-era-or-newer footage).
   The Resistance / rayden-61 packs stay in their own checkout (`../PIU-Simfiles`) and are
   **never committed here** — this repo is exactly the diff we own.
2. **The current annotated snapshot.** `snapshots/` holds the zip that `/Admin/PiuCenter`
   uploads consume (the full piucenter-format batch our pipeline generates), so the live
   batch isn't a single file in someone's Downloads folder.

## Layout

| Path | What |
|---|---|
| `overrides/` | Corrected .ssc files, pack-relative paths mirroring the PIU-Simfiles checkout (e.g. `overrides/13 - PRIME/1401 - Slam/1401 - Slam.ssc`). Baseline = the unmodified pack files for the audited charts (see overrides/README.md); fixes edit them in place so git diff shows exactly what changed per chart. |
| `snapshots/` | The current upload zip + its provenance note. Exactly one "current" zip; superseded ones are deleted from HEAD (history keeps them). |
| `sources/` | The census that drives the repair project: which footage each corrected chart was transcribed from (`stepfile-video-census-*.csv`), and the download worklist (`video-map.json`). |
| `tools/` | Operator scripts: footage downloader, extraction/transcription tooling. Run with the `../piu-annotate/.venv` Python. |
| `videos/` | Downloaded source footage. **Gitignored** — footage is never committed. |
| `work/` | Extraction scratch (frames, intermediate JSON). Gitignored. |

## The repair loop

Census (which footage per chart) → download to `videos/` → extract/transcribe → corrected .ssc
into `overrides/` → re-run the piu-annotate pipeline over pack + overrides (P1+P2 together —
badges are corpus-relative) → `package_snapshot.py` → new zip into `snapshots/` → upload on
`/Admin/PiuCenter`. The gate for any corrected file: implied judged total (tap rows + tick sum)
within 1% of the game's `ChartMix.NoteCount`.

## Ground rules

- Resistance/rayden pack files are never committed (their release says do not redistribute);
  only files **we** made from footage land in `overrides/`.
- Downloaded footage is never committed.
- The snapshot zip is derived analysis data in the piucenter format (the same shape
  piucenter.com has published for years), regenerated on demand by the pipeline.
