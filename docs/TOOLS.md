# Tools

All run on the piu-annotate virtualenv with `-X utf8`:

```
C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe -X utf8 tools/<script>.py ...
```

Scratch output lands in `work/` (gitignored). Scripts are operator tools, not a library —
they print what they did and expect a human reading the output.

## Reading footage

**`combo_reader.py --scan <vid> side=<L|R|C>`**
OCRs the in-game combo counter frame by frame into `work/combo/<vid>.<band>.jsonl` as
`[time, value, confidence]`. Finds the COMBO *label* first and hangs the digit window off it,
which is what stops a BGA's own numbers being read as combo (Tales of Pumpnia's RPG damage
popups). A digit-sized unknown glyph voids the read rather than truncating it; only
sub-digit-width edge fragments are dropped. Unknown glyphs are dumped to `work/combo-unknown/`
for atlas work.

**`cell_reader.py --calibrate|--bootstrap|--scan <vid> <side> ...`**
Fixed-cell OCR for videos whose digit font the shared atlas cannot read (Imagination S18) or
whose counter sits mid-field under the notes (2P doubles, Love is a Danger Zone pt. 2). Cells
are fixed boxes hung off the COMBO label; `--calibrate` fits the geometry from frames,
`--bootstrap` learns a per-video atlas from eye-read frames (`<t>=<digits>`, `?` for an
occluded cell), `--scan` writes the usual `work/combo/<vid>.<side>.jsonl`. Atlases live in
`tools/atlas-cell/<vid>/`. Never label a frame you have not looked at.

**`result_reader.py`**
Certifies a video from its result screen — the `P/G/Gd/B/M` and `maxcombo` that make a video
usable as evidence. Output is the certification ledger in `sources/`.

## Deciding whether a chart is fixable

**`grid_screen.py "<chart>" <vid> <band> <offset>`**
Re-tick versus re-step. Reports the slack profile (`cum − taps`) by 15-second zone and a
verdict. **Takes the offset as an argument on purpose** — sweeping for the offset that
minimises drift always finds one, and the answer becomes self-fulfilling. Calibrated against
eight charts of known outcome. See [EVIDENCE-RULES.md](EVIDENCE-RULES.md) for why the
invariant is one-sided.

**`triage.py "<chart>" ...`**
Rough-assembles a curve and screens it, for sorting a pile before spending forensics on it.
Three verdicts: OK, MISMATCH, and **FORENSICS** — the last means the naive peaks already
exceed `P + G`, so a counted "reset" is a misread and the curve built on it is fiction.
Deliberately crude: good enough to sort, never good enough to author from.

## Building the curve

**`curve_tools.py`** (library)
`continuity_repair` restores dropped hundreds and decides resets with lookahead; `lis_chain`
keeps the longest monotone chain of a segment; `build_anchors(pts, offsets, total)` turns raw
reads plus a descending list of `(boundary_time, cumulative_offset)` run boundaries into the
anchors file. The run boundaries are the operator's call, made from frames — the tools only
assemble what has been decided.

**`fit2.py <vid> <band> <key>`**
Two-sided offset fit, scored only inside tap-only windows where the observed combo delta must
equal the tap count exactly. Reports the window count — under ~15 windows, distrust it.

**`align_schedule.py <vid> <key> <judged> <band> [offset]`**
Aligns the curve to the chart's schedule; reports violation score, observed-versus-expected
tick coverage, and a per-anchor accrual map flagging whether the file has a hold there.
Reading its output honestly is covered in [EVIDENCE-RULES.md](EVIDENCE-RULES.md).

**`hold_observe.py <vid> "<key>" <offset> <judged> <band> [pins.json]`**
Per-hold tick brackets from the anchors, splitting merged spans at gap midpoints. Emits
`work/combo/<vid>.holds.json` with pinned holds, unpinned holds and the closure remainder.

**`storm_fill.py <vid> <band> <w0> <w1> [runOffset] [conf]`**
For windows ticking faster than persistence-based anchoring can follow: keeps the maximal
isotonic subset of single-frame reads and emits synthetic pins.

**`solve_holds.py`** — per-hold events as a bounded linear system over pin intervals.

## Authoring

**`make_targets.py <vid> <out.json>`**
Turns observations into targets: pinned holds keep their observed counts, the remainder
distributes over unpinned holds by beat weight, largest becomes the tuner. **Its beat-weight
distribution is a guess and must be checked** — see step 5 of
[REPAIR-WORKFLOW.md](REPAIR-WORKFLOW.md).

**`window_targets.py <vid> <band> <key> <offset> <judged> <out.json> [windowSec] [clusterGap] [t0-t1=N ...] [spread=length]`**
For drill charts — hundreds of tenth-second holds the curve cannot bracket one at a time.
Clusters the file's holds, tiles each cluster into ~2s windows (never cutting a hold), reads
each window's ticks straight off the curve, pins any window the frames settled (`t0-t1=N`),
and spreads the closure remainder over the unpinned windows by what the curve saw there or,
with `spread=length`, by hold length (the right choice when a player dropped holds: a window
that read zero because of a BAD still owes the ticks the chart judges there).

**`windows_to_holds.py <key> <windows.json> <out.json>`**
Splits window targets into converter regions — overlapping and tail-sharing holds merged
first, globally — because `author_ticks` converges on regions and cycles on multi-hold
windows. A window's ticks go to the regions inside it by overlap length.

**`wall_targets.py <vid> <band> <key> <offset> <judged> <out.json> [windowSec]`**
Alternative for wall-class charts: tiles observed hold spans into fixed windows read straight
off the anchor curve, so the interior is observation-driven rather than profile-driven. Only
usable where the curve actually has reads through the span.

**`author_ticks.py "<ssc>" <BLOCK> <targets.json> <judged>`**
Patches the block's `#TICKCOUNTS` and iterates against the real converter until
`taps + ticks == judged`, with a brute-force two-segment finisher for the rounding plateaus
the incremental loop cannot cross. Restores the file if it cannot converge — but **`git
checkout` the `.ssc` after any failure**, since a failed run can leave a partial schedule.
Aggregates converter segments into target regions by **maximum overlap**; the older midpoint
rule silently starved regions on drill charts and made the loop diverge.

**Read its closing report.** A converged *total* says nothing about the interior: the tuner
absorbs whatever the other regions could not reach, and on Bad Apple D20 a "CONVERGED" run
had parked 182 ticks on one 0.2s hold. The tool now prints authored-versus-target per region
and the count of regions over and under; a tuner more than a handful off its target means the
targets were unreachable as given, not that the file is right. Every region under two beats is
nudged to exact (the old "within ±1" slack pooled 41 ticks onto one hold on Desaparecer), a
region that flips sign every step is locked at its closer grid value, and the finisher starts
from the best state seen rather than the last.

**`edit_notes.py add-hold|move-release <ssc> <BLOCK> <col> <startBeat> <endBeat>`**
Surgical note-grid edits, for content the file is genuinely missing rather than mis-ticking.
Used three times: Pop The Track's truncated finale, Like Me's missing tail, Exceed2's
uncharted 2.2-second intro.

## Verifying

**`tick_verify.py "<chart>" [expected]`**
The acceptance gate. Runs piu-annotate's converter over the block in our tree and reports
`taps + ticks = implied`. A repair is not real until this matches.

**`verify_release.py <release> [--old <release>]`**
Checks a packaged release actually carries the repairs: the `.ssc` through the converter, the
`Hold ticks` in the release's chart JSON, and the judged count must all agree.

**`rebuild_repairs.py`**
Regenerates `sources/repairs.json` from the tree — any census chart whose file now converts to
exactly its judged count is a repaired one. Never hand-edit the manifest; run this.

**`audit_repair.py` [chart ...]**
Re-audits a shipped repair without trusting how it was made: re-derives the offset with the
two-sided fitter, screens the grid at that offset, and compares the file's per-hold ticks
against what the combo curve says happened there. The total is already guaranteed by
`tick_verify`, so this checks the *interior*.

Its comparator refuses to answer more often than it answers, on purpose. A hold is only
compared when the curve genuinely resolves it: at least three distinct anchor values spanning
60% of the hold, and a tick rate under ~30/s. Above that rate no combo value persists long
enough to anchor, so comparing reports the reader's blindness rather than the file's accuracy
— before those guards were added it invented a 485-tick "disagreement" against a 386/s bomb
and a *negative* observed count on a hold the curve had barely read.

The consequence is worth knowing: on the 13 charts audited in 2026-09 only 0–3 holds per
chart were verifiable at all. **These repairs' totals are proven and their interiors are
largely not**, which is a standing argument for note extraction rather than more curve work.
