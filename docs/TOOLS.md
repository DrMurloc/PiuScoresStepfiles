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

**`receptor_reader.py <vid> <t0> <t1> [key] [offset]`** — note extraction
Reads the *receptors* instead of the counter: a judgement flashes its column's receptor
white for a few frames, and a hold's rail is a saturated *and bright* bar in the lane just
beneath it (the BGA that fools a saturation-only test is saturated but dark). Per column it
reports judged-event onsets (prominent peaks of the receptor's white level over its rolling
floor, so a 16th-note drill re-peaks per hit) and hold spans (lane occupancy ≥ 0.3s). With a
key it matches onsets against the file's taps and reports the best offset and the
file-only / video-only events per column. Geometry — receptor band and column centres — is
fitted once per video from the temporal median of the band (the receptors are the only
static thing there) and cached in `work/receptor/<vid>.geometry.json`; the centres come from
the field's extent (outermost strong profile peaks are the outer borders; `ncols` equal
receptors fill the span), because every comb fit tried locked onto a harmonic of the
receptors' inner ridges. `RR_COLS=5` for singles; `RR_THRESH` (flash, default 40; 60–70 on
bright BGA) and `RR_OCC` (rail occupancy, 0.45) tune it. Known limit: through a drill the
white level clips and hits merge, so it under-counts drills — the taps are already in the
file; what this tool is for is the holds.

**`receptors.py`** (library) — the reader's functions (`geometry`, `scan`, `onsets`, `rails`,
`chartstruct`, `match_offset`, `snap_beat`), used by the two drivers below.

**`extract_holds.py "<chart>" [offset]`**
The per-chart extraction survey: scans the whole certified video, derives the offset from the
flashes, lists every rail inside the chart with its head flash (the head *is* a judged event,
so its flash is the exact head time), converts to snapped beats, says whether the head lands
on a file tap, shows what the counter accrued across the rail, and prints the `add-hold`
commands. Then a grid line: file events without a flash and flashes without a file event.
Layout comes from the certification (full-screen → band C; split → L/R by side; 5 or 10
columns by chart type). Prints only.

**`rail_ticks.py "<chart>" <offset> [--lag 0.2]`**
Prices every rail **locally**, with no run structure: the combo read just before the head
and the read just after the tail bracket the hold, and `after − before − taps inside` is its
ticks - *every* file tap between the two reads is subtracted, not just the taps inside the
rail's span, and the head's own row stays in (the converter counts a hold's head as its first
tick, whether or not the old file wrote a tap there). Works wherever the counter
is readable at both ends; a drop anywhere between the two reads is reported as a reset,
never priced - a reset just *before* the head hides when the bomb outruns it (Naissance
S20 read 110 before a MISS and 457 after the finale); a missing bracket read writes the two frames to `work/frames/rails/<vid>/` for eye
reading. Dr. M D18's nine rails and Mr. Larpus D18's four all priced this way — including the
"reset" that was a leading 1 (151 for 51) and the "+143" that was a covered hundred.

**`apply_rails.py "<chart>" <offset> <rails.json> [--burst ...]`**
Turns a rail list (`[{"col", "head", "tail", "ticks"|null}]`, video seconds) into the file:
the head goes on the file's own row for that column when one sits within 120ms (the old
files wrote hold heads as taps), else on the snapped beat; the tail on the snapped beat;
then `regen_chartstruct` and `finale_ticks` with `--pin` for every rail whose ticks were
read and closure for the `null` ones. One run per chart.

**`excess_scan.py "<chart>" <offset> [--conf 0.8] [--min 2]`**
Where does the counter outrun the file's taps? Between consecutive persisting reads inside
one run, the counter's rise minus the file's taps in that span is accrual; clusters are
holds the file lacks. Structure-free, and the way to see that a chart's whole deficit sits
on one finale (Pump me Amadeus D15's +86 = its 86 owed). Its numbers are still read-noisy -
dropped hundreds show as +100 and a covered counter as +1xx - so it points, it does not price.

**`phantom_scan.py "<chart>" <offset>|--fit [--until <video s>] [--conf 0.85] [--tail]`**
The phantom hunt for a (near-)perfect play — taps the file has that the game never judges.
Raw high-confidence reads only: at each read the taps judged ≥150ms earlier must already be
in the counter, so `n_lo − counter` is 0 through a clean stretch and steps to +1 for good at
the phantom. **Its `--fit` is orientation only** — the offset that zeroes the most reads is
the *late* alias, because being one tap interval late absorbs a phantom (Slam S5 read clean
at 10.40 and +1 from the first readable value at the frame-verified 10.30). Take the offset
from the frames and read the step; then `edit_notes.py remove`. `--until` restricts the fit
to the reads before the first hold, where the counter must equal the tap count exactly.

**`finale_ticks.py "<chart>" [--pin b0-b1=N ...] [--burst <beat> [--pre <rate>]]`**
After the edit and the regen: prices every hold region in the file by closure
(`judged − taps`, split by length across the unpinned regions), authors, verifies. `--pin`
keeps an observed count on a region (Another Truth D18's mid-chart pairs read 6/5/5/30 off
a perfect-play counter) and sends the remainder to the rest. `--burst` rewrites the tuner
region's schedule as a tail burst — `--pre` per beat up to the burst beat (default 2), then a
rate tuned against the converter to land exactly — for finales the counter shows firing in
the last stretch (Slam D22 009 → 463 in 0.2s; FA2 SC D19 577 ticks in one frame; My Way
D16 47 steady then 101 at once, `--burst 193 --pre 16`). **Not on a gimmick beat map**: Conflict
S22 runs ~19 beats a second through its ending, and a burst there came out of the converter at
729 ticks against 204 owed; that chart ships flat, priced by closure alone.

**`auto_anchors.py "<chart>" <offset>`**
The grid verdict without hand forensics: reads → `continuity_repair` (dropped hundreds, a
rail's leading 1, and the atlas reading 9 as 5) → runs split at drops that persist *and*
restart near zero → peaks scaled to close on P+G (a final run resting at maxcombo is exact)
→ anchors → `align_schedule` + `grid_screen`. It refuses, and prints its runs, when the read
peaks exceed P+G or there are more runs than resets — that is the FORENSICS signal, and
frames are the answer.

**`regen_chartstruct.py "<ssc>" <BLOCK> <key>`**
After a note-grid edit, rewrites the chart's chartstruct CSV from the `.ssc` in this tree
(keeping the pipeline's extra columns; the first run saves `<key>.csv.pre-edit`). Every
tool here reads that CSV and the pipeline only rewrites it on a full ingest, so an added hold
is invisible until this runs.

**`result_reader.py`**
Certifies a video from its result screen — the `P/G/Gd/B/M` and `maxcombo` that make a video
usable as evidence. Output is the certification ledger in `sources/`.

**`run_drift.py "<chart>" <offset> [--conf 0.85] [--gap 2.0]`**
The tap-grid check that needs **no run structure**. Inside one rising stretch of the counter
the delta must equal the file's tap rows over the same span, so a file carrying taps the game
never judges drifts persistently NEGATIVE (past its miss count) and a file missing a hold
drifts positive. Use it wherever `grid_screen`'s curve cannot be built — many resets, or a
video where the rails cross the counter. Reads below 4 are dropped (the counter is blank
there, so a sub-4 read is the reader inventing a number from an empty box, and one of those
opens a bogus run that double-counts the climb before it); a drop only starts a new run if
the next read continues from it. A lone `+99`/`+100` run is a dropped hundred, not evidence.

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
**`edit_notes.py remove <ssc> <BLOCK> <col> <beat>`**
**Its `<col>` is a FILE column, not a chartstruct column** — see the padding rule in
EVIDENCE-RULES. It now refuses a column past the row's width; before that guard, python
slicing appended instead of failing and First Love D15 shipped a hold on a seventh panel.
`apply_rails` takes chartstruct columns and does the mapping itself.
Surgical note-grid edits, for content the file is genuinely missing rather than mis-ticking.
`add-hold` clears the column's taps inside the span (the old files wrote holds as repeated
taps and the converter refuses a hold laid over them). `remove` deletes a phantom — one note
of a row; a jump row needs one call per column, because a jump is one judged event and half
of it is still one. First uses: Slam S5's intro jump, Set me up S10's two extra drill notes.

## Verifying

**`tick_verify.py "<chart>" [expected]`**
The acceptance gate. Runs piu-annotate's converter over the block in our tree and reports
`taps + ticks = implied`. A repair is not real until this matches.

**`verify_release.py <release> [--old <release>]`**
Checks a packaged release actually carries the repairs: the `.ssc` through the converter, the
`Hold ticks` in the release's chart JSON, and the judged count must all agree.

**`catalog_sweep.py <chart-json folder> <catalog.txt> <videos.txt> <out.json> [--pct 5]`**
Sizes what is wrong *beyond* the census: every corpus block through the converter against the
catalog's Phoenix note count (two sqlcmd dumps, the queries are in its header), matched
through the pack's own mix - a Rebirth-pack S13 block is Phoenix's S17, so a key's level is
never compared with Phoenix directly. Writes the tail past the threshold with each chart's
shape (over-ticked / under-ticked / single-region / hold-less / duplicate block) and its banked
video. `sources/tail-2026-09-06.json` is its output; nothing in it is authored by this tool.

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
