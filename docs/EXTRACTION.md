# Reading the chart off the screen

Everything else in this repo reads the **combo counter** and does arithmetic on it. That can
move hold ticks around; it can never fix a chart whose **steps** are wrong, because it never
looks at the steps. A person fixing these charts watches the video and transcribes. This is the
work to let us do the same.

## The idea

A note is not an event at a line, it is a **streak**. Watch one column over time and the arrows
are parallel diagonals in a time-by-height picture, rising toward the receptors at the top of
the screen (PIU scrolls **upward**). That framing gives four things a threshold at a fixed line
cannot:

- the **slope of a streak is the local scroll speed**, so tempo changes, speed mods and stops
  need no assumption and no global lead - the streak simply bends;
- the crossing time comes from **extrapolating the streak to the judgement line**, which stays
  sub-frame accurate even when a fast chart only shows an arrow for two or three frames;
- two notes close together stay **two parallel streaks**, where one line merges them;
- a **hold is a streak that keeps arriving** - head and tail are the ends of one long run.

An arrow is **saturated AND bright**; the dimmed BGA behind it is neither. The test never looks
at hue, so a chart that recolours its notes reads like any other.

## Where it stands (2026-09-09)

`tools/note_extract.py` extracts; `tools/extract_score.py` grades it against a chart whose notes
are known right. The oracle is large - **2,234 charts already convert exactly to the catalog
count**, so their notes are correct, plus the 106 repaired ones, all with video.

| chart | file notes | extracted | recall | precision | median error |
|---|---|---|---|---|---|
| Bad Apple!! feat. Nomico D20 | 652 | 677 | **96.9%** | 93.4% | 0.035s |
| Dr. M D18 | 499 | 480 | 92.2% | **95.8%** | 0.009s |
| A nightmare S6 | 190 | 272 | 84.7% | 59.2% | 0.019s |
| Beethoven Virus D13 | 303 | 269 | 81.8% | 92.2% | 0.016s |
| My Way D16 | 447 | 428 | 77.2% | 80.6% | 0.027s |
| Bee S17 | 463 | 256 | 37.1% | 67.2% | 0.009s |

Bad Apple D20 was the worst chart in the corpus at 45% and is now the best at 97%. Bee S17 went
the other way - 85% before the tuner started consulting the flashes, 37% after - and is the open
case. The number to drive is still the worst chart: a transcription is only worth having if it
is very nearly perfect.

Three things got it from 5% to here, and each was a wrong assumption rather than a tuning knob:

1. **Colour cannot find an arrow.** Plenty of BGAs are bright and saturated across whole regions
   of the screen, and a colour threshold reads them as notes everywhere. What separates an arrow
   from the art behind it is SHAPE - a compact blob about one lane wide, as tall as it is wide,
   that fills its own bounding box. Connected components with a size and fill filter took recall
   from 37% to 94% in one change.
2. **A real note falls at the scroll speed; the background does not.** Filtering streaks whose
   slope disagrees with the local median took precision from 43% to 95%. It is deliberately
   LOCAL, so a chart that changes tempo is judged against its own speed at that moment.
4. **A second, unrelated sensor settles the threshold.** Neither "find the most notes" nor
   "find the most consistent ones" balances - the first rewards the false positives on a busy
   stage, the second throws real notes away to look tidy. The receptor flashes are judged events
   read at the top of the screen by completely different means, so a setting is good when the
   two agree in both directions. That took Bad Apple D20 from 45% recall to 97%. A floor
   (an extraction may not find far fewer notes than there were flashes) stops it collapsing to
   a handful of perfect ones, which is what cost Beethoven Virus D13 before it was added.

3. **One note can arrive as two streaks** when it is lost behind an effect and re-acquired.
   Nothing puts two notes in one column closer than 50ms, so anything nearer is one note.

Three bugs on the way, all of which made the numbers meaningless:

1. The lead was measured from the **bottom of the receptor band** instead of the judgement line
   at its middle - a 2.25x error in every extrapolation.
2. The scorer accepted a match up to `tol + 1` **seconds**.
3. Extracted times are **video** time, the file's are **chart** time, and the chart starts ten
   or more seconds in while the scorer searched ±0.2s. This one alone took Bee S17 5% -> 39%.

Two changes that raise recall and were measured to be a bad trade, so they are NOT in:

- **Splitting a wide blob back into the lanes it covers.** Arrows on neighbouring panels do
  touch and merge, and a dense chart is full of them, so this looks obviously right - it takes
  Dr. M D18 to 96% recall and My Way D16 from 58% to 80%. But precision falls to about 42%
  whatever the speed filter is set to, because the extra events move at scroll speed like real
  notes and cannot be filtered out afterwards. Recovering merged jumps needs the merge to be
  resolved at detection - by shape, not by lane arithmetic.
- **Running the continuity repair over the whole scan** before pricing (a different tool, same
  lesson): it prices more rails and rewrites ones that were already right.

My Way D16 is the open case: same settings, much lower recall, and worth understanding before
trusting the extractor generally.

## The charts that will break it

The owner's list of the rare things that exist in this game. Each is a real chart to test
against, and none of them is handled yet:

| what | chart to test | why it breaks a naive extractor |
|---|---|---|
| a very long hold | End of the World S20 | one streak that lasts for ever; head and tail must not become two notes |
| a visual gimmick | 8 6 - FULL SONG - S21 | the screen effect trips a saturation test |
| notes change colour | Legendary Dominion D27 | already handled by design - the test is hue-blind - but must be proven |
| disappearing notes | Vanish D22 | the note is gone before the judgement line; caught only if seen early enough |
| hidden holds | Ugly Dee S17 | the head judges normally, the hold body is invisible - the ticks are real and unseeable |
| tempo changes | VVV S23 (severe speed up), Chaos Again S21 (stop-go), Twist of Fate S19 (severe slow down) | the streak's slope changes mid-flight; a stop makes it vertical |
| fake notes | See 22 (at the end) | drawn but never judged - extraction must not author them |
| entirely hidden notes | Ignis Fatuus S21 | nothing on screen at all; extraction can only report that it is incomplete |
| animation behind the notes | Big Daddy D23 (chili pepper, ~halfway), 8 6 - FULL SONG - D23 (~3 min, and a flash) | bright moving art in the lanes reads as arrows |

Two of these are hard limits rather than bugs: **hidden holds** and **entirely hidden notes**
cannot be seen, so the honest behaviour is to detect that the extraction disagrees with the
game's own note count and refuse, exactly as the repair gate already does.
