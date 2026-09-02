# Repairing one chart

The loop that produced every fix in `sources/repairs.json`. Read
[EVIDENCE-RULES.md](EVIDENCE-RULES.md) first — this is the procedure, that is the reasoning.

Throughout, `PY` means `C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe -X utf8`.

## 0. Facts you need before touching anything

From `sources/census-final.json`: the chart's `judged` count and its video. From
`sources/certification-2026-08-30.json`: the result screen (`P/G/Gd/B/M`, `maxcombo`) and
which side (`1p`/`2p`) is our chart. From `sources/ssc-map.json`: the chartstruct `key` and
the `.ssc` path.

Derive two numbers immediately:

- `counted = P + G` — what all run peaks must sum to.
- `breaks = B + M` — how many resets exist, hence `breaks + 1` runs.

## 1. Scan the footage

```
$PY tools/combo_reader.py --scan <videoId> side=<L|R|C>
```

`L`/`R` are the halves of a two-player video; `C` is a centred counter (doubles, or a
full-screen single). Writes `work/combo/<vid>.<band>.jsonl`. Pick the band with the most
usable reads — scanning the wrong side silently produces nothing (Trotpris was scanned on
`R` and returned 3 reads before anyone noticed it was a doubles chart).

## 2. Read the run structure

List the drops, capped at `maxcombo`, and classify each as a real reset or a misread using the
table in [EVIDENCE-RULES.md](EVIDENCE-RULES.md). Extract frames at every ambiguous boundary:

```python
cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)   # crop ~y 28-62%, x by band, upscale 2x
```

Then check closure: observed peaks plus the final run should be **at or below** `counted`, and
the shortfall is what the unobserved breaks are worth. If the peaks *exceed* `counted`, a
"reset" is a misread — go back and re-read, do not proceed.

## 3. Assemble the cumulative curve

Partition reads into segments at the reset boundaries. Each segment's offset is the running
sum of prior peaks, and the last segment's offset is forced by closure
(`counted − final_run`). Within a segment, take the longest non-decreasing subsequence of
reads (this discards misreads), then collapse equal values into
`[t_first, t_last, cum]` anchors. Write `work/combo/<vid>.<band>.anchors.json`.

The curve **must** be monotone and end exactly at `counted`. Non-monotone means the run
structure is wrong — that is what parked Desaparecer D25.

## 4. Settle the offset, then screen the grid

```
$PY tools/fit2.py <vid> <band> <key>
$PY tools/grid_screen.py "<chart>" <vid> <band> <offset>
```

Offset priority is in [EVIDENCE-RULES.md](EVIDENCE-RULES.md). **If `grid_screen` says
MISMATCH, stop** — the chart needs re-stepping, not re-ticking. Record that and move on.

## 5. Observe per-hold, and check the distribution

```
$PY tools/align_schedule.py <vid> <key> <judged> <band> <offset>    # violation + coverage
$PY tools/hold_observe.py  <vid> "<key>" <offset> <judged> <band>   # per-hold brackets
$PY tools/make_targets.py  <vid> work/<name>-targets.json
```

Then the step that is easy to skip and must not be: **check every large target against its
anchor bracket** — `cum_at(t1) − cum_at(t0) − taps_in_window` — and override the ones that
disagree, pushing the remainder into the window where the counter actually moved. The
beat-weight distributor routinely wants hundreds of ticks in a window the curve says holds
twenty (Kasou Shinja D21 wanted 348 where observation said 20).

### 5b. Drill charts: windows instead of brackets

When the file has hundreds of tenth-second holds (Bad Apple D20 has 232, Desaparecer D25
144), skip `hold_observe`/`make_targets` — a 0.1s hold "observes" 0 or 38 depending on which
anchor sits next to it. Read two-second windows off the curve instead and split them into
converter regions:

```
$PY tools/window_targets.py <vid> <band> <key> <offset> <judged> work/<name>-targets.json 2.0 1.0 [t0-t1=N ...] [spread=length]
$PY tools/windows_to_holds.py <key> work/<name>-targets.json work/<name>-holds.json
```

Pin any window the frames settled (a finale that rests at a known value: `119.85-122.25=58`
— give the pin a little slack past the hold's end, a hold ending on the pin's edge falls
out). Use `spread=length` when the player dropped holds: a window that read zero because of
a BAD still owes the ticks the chart judges there. Then author the `-holds.json`.

## 6. Author and verify

```
$PY tools/author_ticks.py "<ssc path>" <BLOCK> work/<name>-targets.json <judged>
$PY tools/tick_verify.py "<chart>" <judged>
```

`author_ticks` patches `#TICKCOUNTS`, iterates against the real converter, and restores the
file if it cannot converge. **If it fails, `git checkout` the `.ssc`** — a failed run can
leave a partial schedule behind.

**Then read its closing report, not just the word CONVERGED.** A converged total says nothing
about the interior: the tuner absorbs whatever the other regions could not reach. The tool
prints authored-versus-target per region and how many regions sit over and under; on Bad
Apple D20 the first "CONVERGED" run had parked 182 ticks on one 0.2s hold. A tuner more than
a handful off its target means the targets were unreachable as given — fix the targets (merge
regions, check the window pins) and author again. Worst deviations go in the commit message.

Convergence trouble is usually one of: targets too fine-grained (merge windows), or a
mis-assigned region. If a chart "cannot converge", suspect region assignment first — that was
a real bug that made two charts look impossible.

Verify **every block in the file**, not just the one you touched, since several songs carry
two repaired charts.

## 6b. Holds the file does not have: add them from the footage

Most of the remaining census charts carry **no hold heads at all**. The counter says how many
events the holds owe; the receptors say where they are:

```
$PY tools/receptor_reader.py <vid> <t0> <t1> <key>          # per-column onsets, rails, offset
$PY tools/edit_notes.py add-hold "<ssc>" <BLOCK> <col> <headBeat> <tailBeat>
$PY tools/regen_chartstruct.py "<ssc>" <BLOCK> <key>         # or nothing downstream sees the edit
```

Read the rail's head and tail off frames before trusting the reader's span (its lane box
starts a few pixels below the receptor, so it sees a rail slightly after the head passes).
A hold head is often a **tap row in the file** — Slam D22's last row was the two centre
panels the rails begin on — so add-hold's overwrite of that row is the intended edit. Then
author the ticks as usual (step 5/6). Where the counter shows the ticks firing at the *end*
of a hold (Slam D22: 009 → 463 in the last third), write the schedule as a tail burst — a
low rate then a high one — and tune the high rate against the converter; the owner's rule
is to model the game, not the file's shape.

## 7. Commit

Name the video, its result-screen numbers, the offset and how it was determined, the run
structure, what the audits said, and the closing arithmetic. State plainly which parts are
observed and which are priced by closure. Then:

```
$PY tools/rebuild_repairs.py
```

which re-derives `sources/repairs.json` from the tree.

## When it will not close

- **Grid mismatch** → re-step pile. The file is a different chart revision.
- **Missing content** → the game ticks where the file has no hold at all. Sometimes fixable
  surgically with `tools/edit_notes.py` (Pop The Track, Like Me, Exceed2's missing intro);
  otherwise park it.
- **Non-monotone assembly** → the run structure is wrong, not the file.
- **Unreadable footage** → an all-miss play (Blaze Emotion S2) or no result screen
  (Conflict D26) cannot certify anything.
