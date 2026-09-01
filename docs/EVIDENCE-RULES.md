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

**When peaks sum above `P + G`, at least one "reset" is a misread.** That is the signature to
act on: rebuild the run structure, do not distribute the excess. `tools/triage.py` reports it
as FORENSICS for exactly this reason.

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

## Blind stretches are normal; fabrication is not

Storms and ending bombs run at 100–1,500 events/second, far past what persistence-based
anchoring can read. Nothing inside them is observable, so the honest options are:

- **Closure** prices the whole blind span exactly (total minus everything observed).
- **The file's own beat profile** shapes the interior, rescaled to that total.

Say which one you used. What is *not* acceptable is letting the beat-weight distributor
scatter a bomb's ticks across mid-chart holds the anchors say are nearly empty — always check
large targets against their anchor brackets and push the remainder into the window where the
counter actually moved. This is the single most common way a converged file is still wrong.
