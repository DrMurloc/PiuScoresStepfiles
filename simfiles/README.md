# simfiles/ — the source of truth

This tree is the **canonical stepfile corpus for PIU Scores chart analysis**. The annotation
pipeline reads it; nothing else is truth. External material — community packs, chart videos,
game patches — is *evidence* used to change these files or add new ones, and every change lands
as a commit that names its evidence.

## What's here

The 658 .ssc files (pack-relative layout, `<pack>/<song>/<file>.ssc`) that the current
annotation corpus reads — every file referenced by the p2-082626 chartstruct release, covering
all 4,574 matched official charts (Phoenix 1 ∪ Phoenix 2). Enumerated in
`../sources/corpus-manifest.json`.

**Seed provenance**: imported unmodified from the public community repo
[rayden-61/PIU-Simfiles](https://github.com/rayden-61/PIU-Simfiles) (branch `stepp1-phoenix`,
commit `cff495bd`) — packs `01 - 1ST~3RD` through `17 - PHOENIX 2` (the Phoenix 2 files are the
Resistance's, published through that same repo). The community's work is the seed; thanks to
The Resistance and rayden. From this point the trees diverge deliberately: theirs stays faithful
to its own history, ours converges on what the game ships.

## Changing a file

- **Fixes are in-place edits** so `git diff` shows exactly what changed per chart. A file
  carries a whole song's difficulty blocks — untouched blocks diffing clean is part of the
  review guarantee.
- **Evidence in the commit message**: the footage/source a change was transcribed from. The
  first wave (the 121 audit-failing charts, `../sources/ssc-map.json`) works from per-chart
  certified videos (`../sources/certification-2026-08-30.json` — the video's result screen sums
  to the game's judged note count).
- **The gate**: a corrected block's implied judged total (tap rows + tick sum) must reconcile
  with `ChartMix.NoteCount` — within 1%, exact where the footage certifies exact.
- **New charts** (game patches) get new files here, evidence cited, same layout.

After edits: re-run the annotation pipeline over THIS tree (P1+P2 together — badges are
corpus-relative), package, drop the new zip in `../snapshots/`, upload on `/Admin/PiuCenter`.
