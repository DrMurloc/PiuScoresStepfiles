# Reading the evidence

Everything here was learned the hard way, usually by shipping something wrong first. It is
the part of the project that is not obvious from the code.

## What the game tells us

**The result screen self-certifies.** For a completed pass, `P + G + Gd + B + M` equals the
chart's `NoteCount` in our database. When those agree, the video is certified: we know the
exact number of judged events, which is the target every repair must hit.

**The in-game combo counter is a judgment oracle.** It increments on every PERFECT and GREAT,
*including every hold tick*. So:

- `taps + hold_ticks == judged` is the equation a correct file satisfies.
- **GOODs do not break combo, and do not increment it.** Proven by Hyperion S20, which shows
  `Gd2` yet `maxcombo == counted`. BADs and MISSes reset it.
- Therefore the sum of all run peaks equals `P + G` exactly — not `judged`. This closure is
  the single most useful constraint in the project.

**`maxcombo` from the result screen is a hard cap and a lock.** No run can exceed it, so any
read above it is a misread and can be filtered before anything else. And when the counter's
resting tail equals `maxcombo`, the final run *is* `maxcombo`, which pins the last segment's
offset exactly. Most short-cut charts end this way.

## Misreads, and how to tell them from real resets

The OCR fails in specific, recognisable ways. Every one of these produced a wrong answer at
least once before it was understood.

| Pattern | Looks like | Tell |
|---|---|---|
| **Truncation shadow** | `210 -> 21`, `410 -> 41` | New value ≈ old/10 **and** the gap is under ~1.2s. A real reset cannot reach 21 that fast. Three of these hid Sarabande's true structure. |
| **Dropped hundreds** | `118 -> 18`, `110 -> 10`, `115 -> 17` (117) | The run continues; the leading digit was lost. Frames settle it. |
| **9↔8 atlas confusion** | `890s` read as `880s`, `90x` as `80x` | Happens at confidence 0.55–0.70 over bright BGA. De-confuse by continuity, then re-run the isotonic filter. |
| **Leading-1 rail artifact** | `20` read as `120` | A hold rail left of the digits reads as a leading 1, at *high* confidence, for whole stretches (Kasou Shinja S20). Detect by century-jump plus local trajectory. |
| **Digit fusion** | `1876`, `5310`, values above `maxcombo` | Killed for free by the maxcombo cap. |
| **Tens-digit 9 read as 8** | `88 -> 81, 82 .. 88 -> 100`, `288 -> 280, 284, 288 -> 300` | The run "falls back" by a few and then jumps ten past where it was. Desaparecer did this twice; a `v + 10` candidate in the segment repair fixes it. |
| **Rail leading 1 on a rest** | finale reads `104 .. 121`, frame shows `004 .. 021` | Same rail artifact as Kasou, but on the *last* run it inflates the final peak by 100 and the closure with it. Bad Apple's final run was 58, not 121. |
| **First read after a reset** | `107` where the run has just restarted | A run starts near zero, so the first read of a segment is the *lowest* candidate (`7`, not `107`); taking it at face value shifted a whole segment by 100 on Desaparecer. |

**When peaks sum above `P + G`, at least one "reset" is a misread.** That is the signature to
act on: rebuild the run structure, do not distribute the excess. `tools/triage.py` reports it
as FORENSICS for exactly this reason.

**A blank counter is a number too.** The game does not draw the combo below 4, so a judgement
text with no number under it means the run has just restarted (Desaparecer 52.5, 121.9). And
a GOOD keeps the run: `GOOD 013` at LiaDZ 63.4 is still that run, the reset came after it.

**Frames are the arbiter.** Extract the boundary at 2–3 timestamps and read the counter with
your own eyes. Never label a frame you have not looked at — an early session fabricated one
and poisoned the digit atlas.

## Finding the offset (video time → chart time)

In rough order of trustworthiness:

1. **`tools/fit2.py`** scores offsets *only* inside tap-only windows, where the observed combo
   delta must equal the tap count exactly. Two-sided, so a tick-dominated chart cannot fool it.
   Trust it when it reports many windows and a low error; distrust it under ~15 windows.
2. **Structural anchor.** The counter's last increment must coincide with the chart's last
   event. This settled Poseidon SC D21 (where fit2's optimum was impossible), Sarabande, and
   Death Moon. It is a physical fact, so it outranks a fitted score.
3. **Violation minimum** from `align_schedule`. Weakest — it is dragged by GOODs and by
   segment-boundary steps.

A one-sided fit *cannot* reject a wrong offset on a tick-dominated chart, which is how three
charts shipped with false optima before `fit2` existed.

**`fit2` can still beat-alias on a rhythmically regular chart.** Its windows only require the
combo delta to equal the tap count, and on a chart of even patterns an offset shifted by a
whole beat satisfies that just as well. Auditing Another Truth D19 in 2026-09 it reported
16.00 with zero error over 40 windows, while the shipped 16.91 scores violation 0 against
548-of-548 observed ticks and 16.00 scores 48 against 546. When `fit2` and the violation /
coverage check disagree, prefer the one that observes more of the chart — and always sanity
check against the structural anchor.

## Phantom rows: taps the file has that the game never judges

On a (near-)perfect play the counter is an exact running count of judged events, so a file
with more taps than the game has a **deficit that steps and stays**: with `n_lo(t)` the
file's taps judged at least 150ms before a read, `n_lo − counter` is 0 (flickering to −1
when the counter is a frame ahead) through a clean stretch and +1 for good from the phantom
on. `phantom_scan.py` prints those segments from raw high-confidence reads only — no run
repair, which is where junk gets in.

Two traps, both hit on the first two charts:

- **A late offset hides a phantom.** Being one tap interval late shifts `n_lo` down by one
  and the deficit vanishes. The flash matcher's one-beat-late alias is exactly that on a
  chart of quarter notes: Slam S5 read clean at 10.40 and +1 from the counter's first
  readable value at the frame-verified 10.30 (132 BPM = 0.45s per beat). `--fit` chooses
  the late alias for the same reason. Take the offset from receptor flashes in frames — a
  flash and its increment land in the same frame — and only then read the step.
- **The counter says when, not which.** In a drill the step lands at the last row before
  the counter stalls, and that row is not necessarily the phantom: Set me up S10's counter
  stalled across the closing jump of each drill, but the frames show the jump's arrows at
  the receptors and its flash with the increment; the game simply has four notes where the
  file has five (side/centre/side/jump), so the extra **centre** note goes. Read a strip at
  ~15 fps across the drill and count the judgements per column before removing anything.

A jump is one judged event, so removing a phantom jump means removing every column of the
row (`edit_notes.py remove` once per column); half a jump still counts one.

**`grid_screen`'s verdict is only as good as its run structure.** Its slack is `cum − taps`,
and `cum` needs every reset placed correctly. Where that reconstruction fails the verdict
describes the failure, not the file: Mr. Larpus D16 screened as MISMATCH at −116 — "the file
carries ~116 taps the game never judged" — on a play with **11 misses**, which is
arithmetically impossible. Its counter is crossed by the finale rails (reads of 5657, 157,
555, 15, 565 inside half a second) and the play resets 14 times, so no curve could be built.
When the slack is more negative than the play's miss count, suspect the curve first and
measure locally with `run_drift`, which compares the counter's delta to the file's taps inside
a single run and needs no structure at all.

**A slack profile that falls and then recovers is broken, whatever its verdict.** Slack rises
at holds and falls only at misses, so it cannot plunge 117 and climb 160 on a six-miss play —
Extravaganza D18 screens +59, −58, +102, +78 across four zones, and the cause is visible in
the run count: the solver placed 4 runs against 9 resets, and each reset it dropped moves the
cumulative under everything after it. Read the *profile*, not just the verdict.

**A mangled read imitates a reset, and a run of them imitates a reset climbing.** The reader
drops leading digits in bursts: Extravaganza D18 emits 10, 12, 13, 14, 15, 18 where the
counter shows 110–118, and 21 where it shows 211. Each is low, each is followed by more lows,
and splitting a run at one charges the whole climb after it as accrual — the phantom +189 and
+99 in that chart's drift. `run_drift` demands a candidate reset stay near its value for half
a second, which rejects most of these, but the residue is why a **large positive drift is a
prompt to read the raw counter, never a measurement**.

## Reading the audits honestly

**Violation score is inflated by GOODs.** Each GOOD drags `cum − taps` down by one,
permanently. Emperor S16 with `Gd6` scores 289 and is verified correct. Do not judge on it
alone.

**`align_schedule`'s out-of-hold accrual counts the arithmetic step at every run-segment
boundary.** A chart with many breaks shows spikes there that are not missing content — FA
Ep. 2-2 D23's 123 was 96 in one boundary step plus 27 genuinely spread. Look at the spread,
not the total. Trotpris's 395-of-439 was real because that chart has exactly one break and
nowhere for such artifacts to hide.

**Slack (`cum − taps`) rises on tick-heavy charts and that is healthy** — it is banking hold
ticks. Emperor S16 climbs to +270 and is correct. What cannot happen is slack going negative:
that says the file scheduled taps the counter never registered. See `grid_screen`.

## What the receptors tell us

The combo counter says *how many*; the receptors say *which column and when*. A judged event
flashes its receptor white and the flash is far brighter than the receptors' beat pulse
(peak heights split cleanly, ~30 against 80–120 over the rolling floor). A hold keeps its
receptor lit and, more usefully, draws a rail — a saturated **and bright** bar — down the
lane beneath it; a tap sprite passes that spot in a few frames. Misses do not flash, so the
reader sees hits, which is fine: the file already has the taps, and cross-referencing the
file-only events against the counter's non-incrementing judgements is how a phantom tap will
be found. Video time drifts against file time by ~0.1% on Slam D22 (offset 14.17 → 14.25
over the chart), which is the file's BPM being rounded, not the video.

**A run structure that closes on P+G is not thereby right.** `auto_anchors` chooses, among
the low restarts it can see, the subset of at most B+M resets whose peaks sum to P+G. On
Extravaganza D15 it split one continuous run at a covered-digit "1" (110 → "1" → 120 → 138,
plainly the same run) and the five pieces still summed to 497 exactly; on Pump me Amadeus it
merged two real resets the frames show at 56.0 and 67.8. The tool's grid verdict is a
screen — a wrong structure usually inflates violations rather than hiding a bad grid — but
an accrual burst it reports is **not evidence of a hold** until frames show the rail or the
counter is read across it. Prefer structures where the tail rests at maxcombo and where the
reads' own continuity agrees with every boundary.

**The flash matcher aliases one beat late on periodic charts.** The receptor-flash offset
sits a whole beat after the truth whenever the chart's taps repeat at the beat: Slam S18/S20
(14.39 → 14.13), Dr. M D14 (11.72 → 11.35), Beethoven Virus D13 (15.29 → 14.87), Another
Truth D18 (16.05 → 15.65). The tell is a rail head that lands on a file row carrying exactly
the rail's columns at the earlier offset and on nothing at the later one. Take the offset
from the heads when that happens; the grid passes at either alias, so it cannot decide.

**A finale bracket that over-prices the deficit has a 5 in its before-read.** Winter D17
read 155 → 324 for a pair owed 128; the frame says 195, and 324 − 195 − 1 = 128. Dr. M S9
read 254 before a pair on a chart owed 27; the frame says 294. The atlas reads 9 as 5 (see
the misread table), and a single wrong digit in the read *before* a hold is the usual reason
a local bracket disagrees with closure. Look at that frame before believing either.

**A bracket can straddle a reset and still climb.** Naissance S20's finale read 110 before
its heads and 457 after its tail, but the frames show a MISS at 105.10 and the counter at
004 at 105.30: the run before the miss reached ~110, and the 457 is the *finale's own run*
(1-2 taps, the heads, then ~145 ticks a second). A bomb outruns the reset it follows, so
`after > before` proves nothing; `rail_ticks` now refuses any bracket with a lower read
between its two ends, and the frames at the head decide.

## Narrow styles: the chartstruct pads, the file does not

A `pump-halfdouble` block is **six** panels wide in the `.ssc`, and the ingest centres it in
the ten-column pad with two zeros on each side. So a rail seen at receptor column *c* is
file column *c − 2*, and every tool that reads a chartstruct (`rail_ticks`, `extract_holds`,
`excess_scan`) reports columns two higher than the file uses. Verified on First Love D15 by
diffing its raw rows against its chartstruct line for line: raw `000010` is chartstruct
`0000001000`.

The general rule is `file column = chartstruct column − (10 − width) // 2`. Getting it wrong
does not necessarily fail loudly: the converter accepted a hold written past the end of a
six-wide row and `tick_verify` still closed on the judged count, because the arithmetic does
not care which panel a tick belongs to. What caught it was the annotation pipeline's
featurizer, which refuses an inhomogeneous array — ninety minutes into a rebuild. **A total
that closes is not evidence that the arrows are in the right place.**

## A sub-4 read is always junk, and it invents holds

The combo counter is **blank below 4**, so any read of 0–3 is the reader finding digits in an
empty box. One of those is not harmless noise: it ends a segment, and every tool that measures
between segment boundaries then charges the whole climb after it as accrual. A lone `3` in
Bee S17 invented a 37-tick mid-chart hold, which is what made its finale (381) plus that
"hold" exceed the 388 the chart owed — and that contradiction is why the chart sat parked as
"the tap grid must be ~37 short". It was not: the reads either side of the 3 are one apart and
no rail is visible there. `excess_scan`, `run_drift` and `phantom_scan` all drop reads below 4.

## A rail shorter than the detector's floor is still a rail

`rails()` defaults to a 0.30s minimum length, which exists because flash decay can masquerade
as a rail. It also hides real ones: Final Audition Ep. 1 S17 was parked as having *no rail
inside the chart*, and its finale pair is 0.28s. **Before concluding a chart has no holds,
re-scan its closing seconds at `min_len=0.15`** and check the candidates against the counter.

## Instantaneous tick bombs

Some charts deliver a hold's ticks at one instant rather than across the hold: Ignis Fatuus SC
D21's counter appears already reading **541** with no judgement before it, at chart 8.47s,
while the file's only opening hold runs 3.00–4.16s — and its four ending holds judge as
nothing at all. That is a timing gimmick the `.ssc` does not model, so it is not a re-tick:
forcing 541 ticks into a hold four seconds away from where the game fires them would be
count-right and shape-wrong. Recognise it by a first read that is already in the hundreds
with an empty screen just before, and put the chart on the extraction pile.

## No per-beat tick rate

The game's hold ticks are authored per chart, not derived from hold length. Across the 43
repaired charts whose single hold region carries an exact measured count, ticks per beat run
from **3.75 to 414** (median 49): Imagination S18's ten rails over 89 beats tick at 3.75, Love
is a Danger Zone pt.2 [Another] S18's triple over 31 beats at 4.08, and every finale is a
designed remainder - Bee S17's 389 sit on 0.94 beats, Beethoven Virus D13's 146 on 0.37. So
the total is a round number the step artist landed on, and the last hold absorbs whatever
that takes. Consequences: a hold is priced by its footage or by closure over ONE region, never
by a rate; a file whose ticks "look reasonable" per beat is not evidence of anything; and the
2,207 beyond-census charts cannot be re-ticked from the catalog count alone unless a single
region carries the whole difference (see STATUS, "Beyond the census").

## Drill charts: windows, not brackets

A 0.1s hold cannot be bracketed by a persistence-based curve — its "observed" count is 0 or
38 depending on which anchor happens to sit next to it — but a two-second window over a
cluster of them is read honestly. Bad Apple D20 (232 holds) and Desaparecer D25 (144) were
authored from `window_targets` windows split into converter regions, and audited at the
window level. The per-hold interior of a drill is unobservable; say so in the commit.

## Blind stretches are normal; fabrication is not

Storms and ending bombs run at 100–1,500 events/second, far past what persistence-based
anchoring can read. Nothing inside them is observable, so the honest options are:

- **Closure** prices the whole blind span exactly (total minus everything observed).
- **The file's own beat profile** shapes the interior, rescaled to that total.

Say which one you used. What is *not* acceptable is letting the beat-weight distributor
scatter a bomb's ticks across mid-chart holds the anchors say are nearly empty — always check
large targets against their anchor brackets and push the remainder into the window where the
counter actually moved. This is the single most common way a converged file is still wrong.
