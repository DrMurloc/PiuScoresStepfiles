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
| Dr. M D18 | 499 | 466 | 57.9% | 62.0% | 0.014s |
| My Way D16 | 447 | 437 | 51.9% | 53.1% | 0.025s |
| Bee S17 | 463 | 369 | 36.7% | 46.1% | 0.007s |

**The counts are close and the timing is tight** - a matched note lands within 7-25ms, far
inside a 16th. Half the notes are still not matched at all, which is the work in front of us.

Three bugs found and fixed on the way, all of which flattered or destroyed the numbers:

1. The lead was measured from the **bottom of the receptor band** instead of the judgement line
   at its middle - a 2.25x error in the distance every arrival is extrapolated over.
2. The scorer accepted a match up to `tol + 1` **seconds**, so early "recall" was meaningless.
3. Extracted times are **video** time and the file's are **chart** time. The chart starts ten or
   more seconds into the video, and the scorer was only searching ±0.2s, grading every chart
   against a wildly wrong alignment. This one alone took Bee S17 from 5% to 39%.

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
