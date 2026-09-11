# Reading the chart off the screen

Everything else in this repo reads the **combo counter** and does arithmetic on it. That can
move hold ticks around; it can never fix a chart whose **steps** are wrong, because it never
looks at the steps. A person fixing these charts watches the video and transcribes. This is the
work to let us do the same.

## The idea

Two halves, and they were got right in the opposite order.

**When a note is** comes from treating it as a **streak**, not an event at a line. Watch one
column over time and the arrows are parallel diagonals in a time-by-height picture, rising
toward the receptors at the top of the screen (PIU scrolls **upward**). That framing gives four
things a threshold at a fixed line cannot:

- the **slope of a streak is the local scroll speed**, so tempo changes, speed mods and stops
  need no assumption and no global lead - the streak simply bends;
- the crossing time comes from **extrapolating the streak to the judgement line**, which stays
  sub-frame accurate even when a fast chart only shows an arrow for two or three frames;
- two notes close together stay **two parallel streaks**, where one line merges them;
- a **hold is a streak that keeps arriving** - head and tail are the ends of one long run.

**What a note is** was, for a long time, a shape statistic: a compact blob, bright and
saturated, about one lane across and as tall as it is wide. Bright art satisfies that constantly
and a dim arrow fails it, so it needed a brightness threshold tuned per chart out of six extra
decodes of the video, and it still capped out around 60-90% depending on the stage.

It is now the **picture**. PIU draws its notes from five fixed images - one per panel - at the
same size for the whole song, and the game hands them to us: **the receptors at the top of the
screen ARE those five pictures**, at exactly the resolution this video draws notes at, and
`receptors.geometry` already isolates them (they are the only static thing in that band, so a
temporal median keeps them and washes out the notes and the BGA). Measured on Dr. M D18, a
receptor correlates **0.86-0.97** with a note of its own panel and under 0.3 with any other.
Correlation is normalised, so it reads structure and not colour - a chart that recolours its
notes matches the same template.

**ONE decode does everything**: the sprite correlations, the receptor flashes that decide which
correlation to believe, and the lane rails that say which taps are holds.

## Where it stands (2026-09-11)

`tools/note_extract.py` extracts, `tools/quantize.py` puts it on the beat grid, and
`tools/extract_score.py` grades it against a chart whose notes are known right. The oracle is
large - **2,234 charts already convert exactly to the catalog count**, so their notes are
correct, plus the 106 repaired ones, all with video.

| chart | file notes | extracted | recall | precision | median error | holds |
|---|---|---|---|---|---|---|
| Bee S17 | 463 | 463 | **100.0%** | **100.0%** | **0.001s** | 1/1 |
| A nightmare S6 | 190 | 193 | **100.0%** | 98.4% | 0.008s | 0/2 |
| Beethoven Virus D13 | 303 | 306 | 99.7% | 98.7% | 0.016s | 2/2 |
| Dr. M D18 | 499 | 502 | 99.2% | 98.6% | **0.001s** | 8/9 |
| Bad Apple!! feat. Nomico D20 | 652 | 664 | **100.0%** | 98.2% | 0.004s | 226/232 |
| My Way D16 | 447 | 457 | 89.9% | 88.0% | 0.031s | 0/2 |

Through the corrected lanes and the tie-broken floor choice, both described under "The lanes"
below; every chart on this page was re-measured under that code on the same day.

against what the blob detector scored on the same charts:

| chart | recall | precision |
|---|---|---|
| Bee S17 | 62.0% | 58.7% |
| A nightmare S6 | 80.5% | 63.5% |
| Beethoven Virus D13 | 81.8% | 92.2% |
| Dr. M D18 | 92.2% | 95.8% |
| Bad Apple!! feat. Nomico D20 | 96.9% | 93.4% |
| My Way D16 | 77.2% | 80.6% |

Every chart went up on recall and the worst went from 62% to 87.5%. The number to drive is
still the worst chart: a transcription is only worth having if it is very nearly perfect.

**The timing is not the problem it looked like.** The old table reported 16-47ms of error; that
was the scorer, which searched a 50ms coarse grid, refined only ±60ms, and stopped caring once
every note was inside the tolerance - so a constant lead clipped at its own rail and was
reported as the extraction's error. Measured properly, the residual on Bee S17 is a constant
**-60.0ms with a standard deviation of 1.3 MILLISECONDS**, per column and over the whole song.
Dr. M D18 is 9.2ms, and its residual drifts +13ms per minute - which is the video's clock
against the stepfile's tempo map, not anything the detector did. A 16th note at 200bpm is 75ms,
so there is an order of magnitude in hand.

## What made the difference

1. **The receptor is the sprite.** Two seeds were tried before it and both are worse. The median
   of the blob detector's candidate crops is a picture of the BGA on any chart whose notes have
   not started yet, and every refinement round then protects it. Their MEDOID - the crop most
   like the others - is right whenever arrows are a plurality, and on Dr. M D18 it recovered
   three panels perfectly and handed the other two a "3" and an "O" off the combo counter,
   because a plurality vote can simply lose. The receptor cannot lose: it is the picture, not a
   vote about the picture.
2. **A hold's tail is not a note.** The tail cap is the head's own sprite, so it correlates
   exactly as well and arrives as a second note - on Bad Apple D20, 260 extra "notes" and the
   whole of that chart's precision problem. While a hold runs its panel is held down, so the
   game cannot put another note in that lane: anything inside the rail that did not open it is
   the hold's own artwork. Only a rail an extracted note actually **opened** is trusted to
   swallow anything, because a short bar of bright saturated art also reads as a rail, and
   deleting real notes inside one is a silent loss where keeping a tail is a false positive the
   count gate catches.
3. **Holds need no new machinery.** The game already reports a held hold at the receptor, as a
   saturated bright rail down the lane, and `receptors.rails` reads it: the head is the note
   that opens the rail and the tail is where it closes. Two settings had to be got right. The
   rail box sits 8px BELOW the receptor band while the judgement line is that band's middle, so
   both edges of a rail are early by the same distance over the scroll speed - the code
   subtracted the box height instead of adding the gap, a 150ms error that put 99% of Bad
   Apple's hold ends outside a 120ms tolerance. And `min_len` had to come down from the 0.30s
   the repair pipeline uses (it prices long hold REGIONS) to 0.065s, because **78% of Bad
   Apple's 232 holds run for 0.11s**. Swept against a hold-heavy chart and a hold-free one,
   0.065 keeps 220 of 232 while cutting Bee S17, which has ONE hold, from 29 rails to 8.
4. **A real note falls at the scroll speed; the background does not.** Filtering streaks whose
   slope disagrees with the local median took precision from 43% to 95% when it landed, and it
   is deliberately LOCAL, so a chart that changes tempo is judged against its own speed then.
5. **A second, unrelated sensor settles the threshold.** Neither "find the most notes" nor "find
   the most consistent ones" balances - the first rewards the false positives on a busy stage,
   the second throws real notes away to look tidy. The receptor flashes are judged events read
   at the top of the screen by completely different means, so a setting is good when the two
   agree in both directions, and a floor (an extraction may not find far fewer notes than there
   were flashes) stops it collapsing to a handful of perfect ones. Neither sensor sees the
   stepfile.
6. **A colour gate learned from the chart's own confident notes.** Not a hue test and not a
   fixed threshold: the largest channel gap over the largest channel, with the bar set from the
   notes THIS chart already showed at a correlation nothing else reaches. On a monochrome BGA it
   removes almost every false positive; on a chart whose notes really are pale it learns a low
   bar and removes nothing, which is correct rather than a failure.
7. **One note can arrive as two streaks** when it is lost behind an effect and re-acquired.
   Nothing puts two notes in one column closer than 50ms, so anything nearer is one note.
8. **The time base is the container's timestamp**, not a count of frames times 1/fps. On a 59.94
   stream that reports 60, accumulated drift is indistinguishable from the chart being wrong.

## Putting it on the grid, and writing it back

A stepfile is beats, not seconds. `tools/quantize.py` fits the offset and the subdivision,
`tools/author_notes.py` writes the note grid back into the .ssc, and `tools/diff_notes.py`
compares what came out against what was there - in BEATS, so a measure written on 16ths and the
same measure written on 48ths compare equal, which they should. Nothing reads the stepfile's
NOTES except the offset anchor below; BPMS, STOPS, TICKCOUNTS, the description and the other
difficulties are not touched, because none of them is what was wrong.

Read off the video and written back out, against the charts the repo already believes:

| chart | events in the file | authored | identical |
|---|---|---|---|
| Bee S17 | 464 | 464 | **463 (99.8%)** |
| A nightmare S6 | 192 | 192 | 186 (96.9%) |
| Dr. M D18 | 508 | 502 | 486 (95.7%) |

Bee's single difference is its one hold's TAIL, one grid step out, which is the rail end's known
accuracy. Everything else - every tap, in every column, at every beat - matches.

Four things had to be learned to get there, and three of them are the same mistake:

- **A tolerance in beats means nothing until you say which lattice.** 0.02 beats against a 48th
  lattice, whose lines are 0.0208 beats apart, accepts every possible time - which is how the
  first fit came back "100% on the lattice" at an offset of zero. Grid error is a fraction of
  the spacing now.
- **Counting things inside a tolerance stops discriminating** as soon as they are all inside.
  The grid fit picked an offset a whole lattice step off the truth, the offset anchor did the
  same, and `extract_score` reported a constant lead as the extraction's timing error - three
  tools, one mistake. All three now break the tie on how WELL things fit, not how many do.
- **The lattice repeats, so it cannot say where the song starts.** Every offset a whole number
  of steps away scores identically, and on a chart whose spacing is 39ms that is hundreds of
  equally good answers - the first authored chart came out one quarter-beat late in EVERY row.
  The file's own notes are the anchor: borrowing them is not circular, because it is not their
  content that is borrowed. A file we are replacing is wrong in places; it is not wrong about
  which minute of the song it is. The grid fit is then confined to ±50ms around it.
- **Fitting tolerance and writing tolerance are different questions.** A note 20% of the way to
  the next line still snaps to the right line; only a note near the boundary is ambiguous. Using
  the fitting tolerance to decide what may be WRITTEN refused charts that were right - Dr. M D18
  measures 9ms of spread against an 18ms quarter-beat window, so 4% of its notes missed a
  tolerance built for choosing a lattice and the chart was correct in every one of them.

A note whose snap IS ambiguous is dropped rather than guessed at, and so is a second detection
landing on a line another already holds (the detector de-duplicates in seconds, at 35ms, and a
quarter-beat row is 100ms wide). What stops that quietly deleting real notes is the count check
afterwards: a chart short of the catalog's number does not ship.

## What density does to it

The owner asked for a D26 in the verification set on the grounds that note density might cause
extra hurdles. It does. The densest certified charts in the corpus, whole song:

| chart | notes/s | recall / precision | hold heads found |
|---|---|---|---|
| 1949 D28 | 12.2 | 92.7% / 95.3% | 55 of 84 |
| ESCAPE D26 | 11.6 | 86.5% / 92.5% | 108 of 283 |
| Brown Sky D26 | 10.9 | 97.0% / 88.3% | 121 of 191 |
| Shub Niggurath D26 | 10.7 | 83.8% / 87.4% | 49 of 153 |

against 99-100% on the sparse charts (My Way D16 aside - it is its own case, below). Before the
lanes were corrected these four read 90.1/88.4, 79.8/89.7, 90.0/91.2 and 79.7/78.9: a good part
of what this section used to call the density penalty was the lanes. What is left is still two
separate limits, and neither is a threshold to tune:

**It is not the tight pairs, and it is not peak suppression.** That was the obvious theory -
suppression is half a sprite, 32px, and a 34ms pair at ESCAPE's scroll speed is 20px apart, so
two arrows that close should merge into one peak. Both halves are measurable and both are wrong.
Loosening suppression from half a sprite to a quarter changes ESCAPE's recall by **nothing at
all** (79.7% at 0.50, 0.35 and 0.25 alike; only precision falls), and ESCAPE contains exactly
**one note** inside 35ms of a same-column predecessor - 0.1% of the chart - while it is missing
20%. Brown Sky D26 has none at all and still stops at 90%.

Priced across the whole corpus, the two-frame blind spot is not a general ceiling either: it
costs 3,059 notes of 1,549,070, **0.20%**. What it is instead is a per-chart disqualifier - 23
charts lose more than 5% of themselves to it, and one loses half - which is a thing to DETECT
rather than to fix, and the count gate detects it.

What the dense charts actually lose is panel-shaped. ESCAPE's recall by panel: **up-left and
up-right 94-100%, centre 74-76%, down-left 73-86%, down-right 58-74%**. A miss that sorts by
which picture is being matched is a template problem, not a density problem. (Measured through the
old lanes and not re-measured since: every template was cut up to 6px off its receptor then, and
by different amounts per column, so some of that shape may have been the lanes.)

**Half of a dense chart's holds are shorter than two frames.** ESCAPE D26's median hold is
**0.03 seconds** - under two frames at 60fps - because a hold that short is how a chart writer
adds a single tick. The rail cannot resolve what the camera did not sample: at a 0.04s minimum
the reader finds 48% of them and starts inventing rails, at 0.065s it finds 41%. This is the
same kind of limit as a hidden hold, and the same answer applies: the count gate refuses.

The rail SIGNAL is not the problem, which is worth saying because it looks like it should be:
during ESCAPE's holds the lane reads above 0.40 on 73% of frames against 2% elsewhere - cleaner
separation than Bad Apple D20, where the holds are found.

## The lanes, and a threshold that can miss by a whole receptor

Before anything is matched, `receptors.field` decides where the lanes are: the median receptor
band, its column profile, and the outermost strong peaks of that profile taken as the field's two
outer borders, with the lanes spaced evenly between. On Andamiro's upload of **L (PIU Edit) D27**
the right-hand border peaked just under the 0.6 cut, so the span stopped one ridge short. The
pitch came out 69.5 where the full span gives 73.9, and each lane sat further off its receptor
than the last - **46px by column 9**, most of a receptor's width. Everything measured on that
video before the fix was measured through the wrong lanes: the centre panel's template was
averaged with a crop of the gap between two receptors, column 2 found **8 notes** where its
mirror column 7 found 280, and the whole song came to 1,181 notes and 11 holds.

69.5 is an ordinary pitch, so the guard on pitch could not see it. The picture could. A receptor
row is its own reflection - down-left against down-right, up-left against up-right, the centre
against itself, on one pad or two - and the band correlates with its reflection at **0.99** about
its true axis. So the fit now measures that axis first, and a span that is not symmetric about it
is re-read as the outermost PAIR of peaks that is, from peaks allowed to be weaker than the cut. A
span that already is symmetric is left exactly as it was.

Through the right lanes the same D27 reads **1,365 notes and 58 holds**, per column
`[23, 33, 142, 203, 279, 308, 193, 141, 25, 18]` - a doubles chart's shape, each column within a
few notes of its mirror.

It was not one video. Every cached fit was checked against two things that need no stepfile - the
two pads' receptors are the same picture, and the field is its own reflection:

| fits | checked | centre off the mirror axis | agreement on the good fits (twin / mirror) | on the lopsided ones |
|---|---|---|---|---|
| extractor (`field`) | 36 | **5**, by 21-36px | - / 0.97 median | mirror 0.10-0.17 |
| repair pipeline (`geometry`) | 214 | **8**, by 21-36px | 0.95 / 0.98 median | mirror 0.10-0.24 |

Re-fitting the 36 extractor fields under the new rule moves exactly those five and returns the
other 31 unchanged, Bee S17 and Dr. M D18 among them - their templates regenerate byte-identical
and their scores do not move. None of the five is a certified chart, so no published extraction
number changes: they are Fracture Temporelle D23, Highway Chaser D22, Legendary Dominion S20 and
S16, Big Daddy D23, and the D27.

The repair pipeline's `geometry()` is deliberately left alone, and six of its lopsided fits
belong to certified charts: VECTOR S22, Conflict S22, KUGUTSU S25, Monkey Fingers 2 S17,
Solitary D17 and 2006. LOVE SONG S12 (that video's left field; its S15 was played on the right).
Their flashes and rails were read through the wrong lanes. One has a shipped repair - Conflict
S22, whose finale pair was re-priced in `a35085e` - and it passed the count gate, which is
strong evidence for its total and none at all for its columns.

Both caches keyed on a video now carry the lanes (the receptor templates and the sprite pass), so
a corrected fit can never be handed the picture read through the old one.

**The peaks are not the edges, either.** Even a symmetric span was packed too tight. The two
outermost profile peaks are the bright outer ridges of the first and last receptor, and those sit
inside the lane boundary, so spreading the lanes evenly between them squeezes every fit - a little,
and by the same share every time. The census shows it without a stepfile: on all 125 centred
doubles fits, the two pads' receptor rows repeat at exactly **1.019x** the pitch the span implied
(tenth percentile, median and ninetieth alike), which puts each ridge 0.093 of a lane inside its
edge. The lanes are now spread from the edges (`INSET`). On the D27 that puts the two centre
receptors at 452 and 829px, where the picture has them at 452 and 829.5; and a singles field and a
doubles field off the same footage now agree on how wide a receptor is (75.8 and 75.5px, where
the old fit said 73.0 and 74.1). An outer lane moves about 6px.

Every published chart, the same day, before and after:

| chart | before | after |
|---|---|---|
| 1949 D28 | 90.4 / 88.5 | **92.7 / 95.3** |
| Brown Sky D26 | 89.6 / 88.4 | **97.0 / 88.3** |
| ESCAPE D26 | 80.5 / 90.7 | **86.5 / 92.5** |
| Shub Niggurath D26 | 80.4 / 83.5 | **83.8 / 87.4** |
| Bad Apple!! feat. Nomico D20 | 99.2 / 93.2 | **100.0 / 98.2** |
| Beethoven Virus D13 | 99.3 / 88.3 | **99.7 / 98.7** |
| VANISH D22 | 94.6 / 87.6 | **100.0** / 85.4 |
| Dr. M D18 | 98.8 / 98.4 | 99.2 / 98.6 |
| My Way D16 | 89.7 / 85.5 | 89.9 / 88.0 |
| VVV S23 | 99.0 / 97.4 | 99.0 / 98.0 |
| A nightmare S6 | 100.0 / 97.9 | 100.0 / 98.4 |
| Bee S17 | 100.0 / 100.0 | 100.0 / 100.0 |
| Ignis Fatuus(DM Ashura Mix) S22 | 94.2 / 99.6 | 94.1 / 99.5 |
| The End of the World ft. Skizzo S20 | 99.1 / 97.0 | 98.6 / 98.6 |
| Ugly Dee S17 | 15.1 / 21.3 | 17.0 / 38.3 |

"Before" is symmetric borders with the floor chosen by flash agreement alone; "after" is `INSET`
with the tie rule below.

**Bee S17 is why this did not ship on its first run.** Through the new lanes its precision fell to
97.3% - thirteen false notes, all on the centre panel. The lanes were not the cause: through them,
floors 0.44, 0.52 and 0.60 all read Bee at 100/100, and the extractor picked 0.36 because its
receptor-flash agreement came out 0.514 against 0.512. A second sensor that cannot tell floors
apart is not choosing between them, so a tie now goes to the strictest floor (`TIE = 0.005`): a
lower floor only ever adds detections, and when those do not make the flashes agree measurably
better, they are not notes. Replayed over all fifteen charts from their cached passes, that lifts
mean F1 from 94.98 to 95.07 and puts Bee back at 100/100; a margin of 0.01 does no better on
average and costs The End of the World its precision.

## Checking an official video against its own counter

Andamiro's uploads carry no result screen, so the certification gate that guards the repair path
can never pass one. What they carry instead is autoplay: the game hits every note, nothing breaks
the combo, and the counter goes up by exactly one for every judged event. `tools/combo_check.py`
turns that into a check that runs one stretch of the song at a time.

Two things had to be right first.

**The counter has to be read in Phoenix 2's font.** Phoenix 2 redrew it - solid silver italics
where Phoenix 1 has a hollow outline - and the original atlas reads none of it: on 14 held-out
frames of L (PIU Edit) D27 it found no label on nine and returned five values, all wrong (393,
379, 938, 800, 800). `tools/atlas-combo-p2` reads 13 of the 14 exactly and abstains on the last.
Scanned whole, the D27 reads on 55% of its frames, and the longest never-decreasing run of
confident reads climbs from 4 to **1500** - 1436 at 129.98s, 1500 from 130.02s, as the video
fades out on a hold in column 0.

**A judged event is a row, not an arrow.** A jump is one judgement (EVIDENCE-RULES.md). Across
stretches where the D27's counter moved 180, the extraction held 206 arrows and 183 rows.

The stretches come from the counter alone. Two reads of the same value mean nothing was judged
between them, however many frames in between went unread, so a quiet instant is the middle of any
such pair at least 0.15s apart. The stretches are then the same for every extraction of a video,
which is what lets two correlation floors be judged on the same evidence. A stretch with a hold
rail in it is reported and not judged: the counter there carries hold ticks, a per-hold tick
model was measured and failed (`verify_extract.py`), and the converter's implied count is the
authority for those.

On the D27, through the corrected lanes and at the floor the extractor chose (0.419): 57
stretches, 29 with no rail, **27 of them exact** - and both misses fall in one second. Counter +1
against two rows at 94.50-94.69s and +2 against three at 94.69-95.09s: each holds one false note,
a three-frame streak moving at 840 and 780 px/s where every real note that second moved at
953-983, 29 and 35ms behind a real note in the same column. Each is that arrow lost and
re-acquired, getting past both the 15ms merge and the speed filter; the frames show one arrow
each time. Nine stretches that did contain a rail matched exactly as well, so those rails carried
no ticks.

`_clean` now drops exactly that: a streak of at most 4 frames running more than 12% slow within
60ms of a longer streak in its column. Measured before it went in, it deletes no real note on any
of the fifteen published charts - recall is unchanged on every one, and five false notes go (1949
D28, ESCAPE D26, Brown Sky D26) - and the D27 then matches its counter on all 29 stretches.

That is the review loop in one example: the extractor did the work, the counter pointed at one
second of a two-minute D27, and four frames settled it.

## Different footage, different correlation scale - and every threshold here is absolute

> **Correction, 2026-09-11: the D27 evidence in this section was measured through lanes fitted
> 46px wrong** (see "The lanes" above), and the two-source contrast sample predates the lane fix
> too. Through the corrected lanes the D27's templates read 49, not 37; its extraction barely
> moves between floors 0.34 and 0.52 (1,275-1,285 notes); and its own combo counter says every
> floor from 0.48 up is exact on each hold-free stretch - higher than the 0.42 that scaling the
> floors by sharpness lets it reach. All fifteen published charts measure at full scale, so none
> of them can test the scaling in either direction. It stays in the code until a genuinely soft
> official video is measured, because removing it untested would be the same mistake again. What
> follows is kept as the record of what was believed and why.

The six charts this detector was tuned on all came from one uploader. Footage from elsewhere
does not have the same contrast, and the correlations follow it. Sampling sixteen videos, the
two sources this corpus draws on do not overlap at all:

| source | n | mean template contrast | range |
|---|---|---|---|
| NEVSISTER | 8 | 70.9 | 67.0-74.6 |
| PUMP IT UP Official | 8 | **44.6** | 30.8-50.1 |

**What causes that is not established.** Channel, mix era and upload pipeline are confounded,
and the `skin` field cannot arbitrate because it is read off a result screen that official
uploads do not have - it says `phoenix` for all eight NEVSISTER videos and `None` for all eight
official ones, which is only a restatement of which group is which. The Phoenix 2 screen does
look different - soft pastel receptors with a glow against Phoenix 1's hard white outlines -
but one video is not a demonstration that the mix is the cause.

What IS established is the part that matters: a video's correlation scale varies by about 1.6x
between sources, and every threshold here is an absolute number. On Andamiro's upload of
**L (PIU Edit) D27**, across thirty seconds of dense chart, the peaks run **p50 0.23, p90 0.35,
p99 0.48**.

The lowest floor this extractor will consider is **0.36** - above the ninetieth percentile of
everything on that screen. It reads the chart from the tail of its own distribution:

| floor | notes found in 30s |
|---|---|
| 0.18 | 612 |
| 0.24 | 584 |
| 0.30 | 310 |
| **0.36** (the current minimum) | 152 |
| 0.44 | 44 |

Over the whole 133-second video it recovered 662 notes, about what it ought to find in thirty
seconds, and the per-column spread at 0.18 looks like a doubles chart where at 0.44 it is noise.

**This is not fixed.** Two attempts are recorded here because both look obviously right:

- **Replace the absolute floors with quantiles of each video's own distribution.** Self-
  calibrating, needs no knowledge of which mix it is looking at - and it takes Bee S17, the one
  chart that was exactly right, from 100.0%/100.0% to **95.9%**/100.0%.
- **Add the quantiles to the absolute floors** rather than replacing them, so a Phoenix 1 video
  can still choose the floor that suits it. Bee S17 stays at 95.9%.

The second result is the informative one: since the old floors are all still candidates, the
loss cannot be the floor that was chosen. What both changes share is dropping the DETECTION
floor from 0.36 to 0.14 so the quantiles are computable at all - and the comment that used to
sit on FLOORS said exactly this, that a floor below 0.36 costs recall rather than buying it,
because the extra peaks drown the tracker. It was right and it was removed. Whatever handles
both skins has to leave Phoenix 1 detection alone.

## Measured dead ends

Kept because each one looks obviously right:

- **Notes are drawn SMALLER than the receptors.** They look it on screen - the receptors carry a
  heavier frame - and if it were true the template would need a scale per depth. Matched at
  0.55x through 1.10x over 300 frames and five depth bands of the strip, **1.00 wins in every
  band**; nothing else even registers.
- **A longer minimum streak buys precision.** It buys it slower than it costs recall: on Bad
  Apple D20, going from 3 frames to 16 takes precision 79% -> 92% and recall 92% -> 47%.
- **Splitting a wide blob back into the lanes it covers** (blob detector). It takes Dr. M D18 to
  96% recall and My Way D16 from 58% to 80%, and precision falls to about 42% whatever the speed
  filter is set to, because the extra events move at scroll speed like real notes. The merge has
  to be resolved at detection, by shape - which is what matching the sprite per column now does.
- **Fitting each streak on the frames nearest the judgement line** instead of all of them. On
  Bee S17 it looked dramatic; it also took Dr. M D18 from 92% to 63% and Bad Apple D20 from 97%
  to 72%, and making it conditional on the fit's residual does not discriminate because nearly
  every streak exceeds any residual worth setting.
- **Sampling three windows across the song to tune on.** It chose exactly the same threshold on
  every chart tried, for three times the work. (The flashes now cover the whole song anyway,
  because the holds need them.)
- **A correlation floor below 0.36.** Lower is not safer: the extra peaks drown the tracker,
  which links runs to the wrong streaks and hands the speed filter a polluted median. On
  Beethoven Virus D13, 0.28 scores 32% recall where 0.36 scores 86%.
- **Running the continuity repair over the whole scan** before pricing (a different tool, same
  lesson): it prices more rails and rewrites ones that were already right.

## What is still missing

- **My Way D16 is the open case**, and it is not a detection failure: at every floor and with no
  filtering at all, recall stops at the same number, and the notes it misses cluster in one
  passage (video 20-24s) where the extraction and the file disagree by 0.2-0.5s with alternating
  sign - not a constant offset, so not a clock. Both sensors are thin there. Worth understanding
  before trusting the extractor generally.
- **A chart for a song this repo has no file for** is now written by `author_new.py`, and L (PIU
  Edit) D27 comes to **1,454 judged events against its counter's 1,500**. Its tempo is a constant
  155 BPM fitted from its own rows (their alignment with a twelfth-of-a-beat lattice 0.92 against
  0.57 for the next tempo tried; the two halves fit 155.03 and 155.00), written in 16ths and
  16th-triplets. Before 80 seconds the file agrees with the counter stretch by stretch - the
  intro's holds over-count by six, nothing else is off by more than one. 1,266 of its 1,272 notes
  are written (the other six were two detections on one lattice line) and all 68 holds. The 46
  still missing are hold ticks in two places: the stretches between 96 and 124 seconds (21) and
  the part of the last hold the video shows (about 29). No single change of `#TICKCOUNTS`
  explains both - the best fit to the stretches overshoots the total by 15, the best fit to the
  total leaves the stretches as they were - and the stretches holding exactly one hold, where a
  hold's length could be read off the counter, are all before 92 seconds. Those holds are where
  the frames get looked at. The first look, at 103-109 seconds where the file is five short,
  finds every row where the file has it and one hold - column 8 at 108.3s - drawn about 80ms
  longer than its rail read it: a tick, not five. So hold ends may read early, and nothing yet
  says that is the whole of it.
- **The middle lanes are timed late where the judgement text covers them.** On the D27, columns 4
  and 5 keep only 8-11 frames of most streaks where every other column keeps 18 or more; those
  streaks fit 1.5-4% slow and cross the judgement line up to 10ms late (p90), where the outer
  columns sit within 3ms. At a twelfth of a 155bpm beat that is enough for 41 real notes - all
  but two of them in columns 4 and 5 - to be refused as off the grid when the chart is authored.
  What was seen of each arrow is still where it was; only the slope is wrong, so re-timing a note
  from its streak's centroid at the local scroll speed puts them back (49 off the D27's lattice
  before, 0 after). That is **not** in the extractor. Tried there on the short streaks only, and
  on short streaks that also run slow, and replayed over the fifteen published charts at the
  floors they are read at, every version cost VANISH D22 four real notes and Brown Sky D26 about
  5.5ms of median timing (Shub Niggurath D26 2-6ms), against gains such as ESCAPE D26's timing
  going from 29.8ms to 23.0. `author_new.py` applies it to a chart it writes at one tempo and
  checks against that chart's own counter.
- **A lattice read off footage can be too coarse, and then triplets are written on the wrong
  rows.** The subdivision a chart is written on is inferred from the extraction's own timing. On
  the repair path that inference disagrees with the file's own subdivision on 8 of the 15
  published charts: VVV S23 (written in 24ths), Bad Apple!! D20 and Ignis Fatuus S22 (12ths) all
  read as quarter-beats; ESCAPE D26, Brown Sky D26, The End of the World S20, VANISH D22 and Ugly
  Dee S17 (16ths) read as 24ths, 32nds, 8ths, 8ths and 32nds. The snap that follows accepts a
  triplet a twelfth of a beat from a 16th line (0.67 of half a spacing, under SNAP's 0.70), so a
  chart on too coarse a lattice gets its triplets on the wrong rows and nothing is refused - and
  no count can see a note in the wrong row. Choosing by how many notes a lattice holds within the
  fitting tolerance, rather than `fit_offset`'s 75th percentile, recovers VANISH and Ugly Dee and
  is what `author_new.py` uses; the other six ask for timing their footage does not give.
  `author_notes.py` has only been round-tripped on charts written in quarter-beats (Bee S17, A
  nightmare S6, Dr. M D18).
- **An official video's hold stretches are not judged.** The counter says how many judged events
  each one holds; which share of them is ticks is the converter's to say, once there is a file.
- The receptor-flash floor choice is still the one thing here that looks at a sensor measuring
  STEPS; on official footage the counter is the better chooser, and nothing uses it for that yet.

## The charts that will break it

The owner's list of the rare things that exist in this game, and what the extractor scores on
each. Where the exact difficulty is not certified, the nearest certified chart of the same song
stands in.

| what | chart | recall / precision | holds |
|---|---|---|---|
| a very long hold | The End of the World ft. Skizzo S20 | **98.6% / 98.6%** | 27 of 27 |
| tempo change (severe speed up) | VVV S23 | **99.0% / 98.0%** | 34 of 39 |
| disappearing notes | VANISH D22 | **100.0%** / 85.4% | 90 of 189 |
| entirely hidden notes | Ignis Fatuus(DM Ashura Mix) S22 | 94.1% / 99.5% | 19 of 27 |
| hidden holds | Ugly Dee S17 | **17.0% / 38.3%** | 0 of 52 |

(Hold heads found, of the file's holds. Through the corrected lanes; before them these read
99.1/97.0, 99.0/97.4, 94.6/87.6, 94.2/99.6 and 15.1/21.3.)

The first four are effectively solved, and two of them are the cases that were supposed to be
hardest. **A severe speed change costs nothing at all** - which is the streak model earning its
keep: the slope of a streak IS the local scroll speed, so a chart that speeds up simply draws
steeper diagonals and no assumption anywhere has to change.

**Ugly Dee S17 is the one that stands.** It is 212 notes carrying 597 judged events - 385 of
them hold ticks from bodies that are not drawn - and the second sensor is no help precisely
because of that: the receptor flashes are mostly ticks, so flash agreement bottoms out at 0.18
and the correlation floor gets chosen badly. This is the hard limit the design predicted, and
the honest behaviour is what the count gate already does: refuse.

The other five on the list are **not measurable yet, and that is a footage problem rather than
an extractor problem**: Legendary Dominion D25, CHAOS AGAIN D26, Big Daddy D23, Twist of Fate
(feat. Ruriling) S16 and 8 6 - FULL SONG - S21 are all `verdict: OPEN` - no readable result
screen, so nothing establishes that the video IS that chart, and nothing says which pad was
played. Run anyway they scored 17-69%, against 94-99% for the four certified ones, and the
extractor now refuses them rather than reporting a number: on a two-player video, guessing the
pad reads the wrong half of the screen. Big Daddy D23's video is also one of the five whose lanes
were fitted lopsided (see "The lanes"), so its number from that run was taken through the wrong
lanes as well.

Two entries have no certified video at all and could not be tested: **See 22** (fake notes) and
**Destroyer D24** (laser beams).

## Cost

One decode per chart, at 6.4 ms/frame for a singles chart and 11.6 for doubles - so roughly 45
to 110 seconds of a core for a three-minute song, plus a few seconds to choose the correlation
and mark the holds. The 2,207 charts of the tail are 55-110 core-hours, and each chart is
independent, so it parallelises exactly.

`--cache` keeps a chart's sprite pass under `work/`, so a change to anything AFTER the detector
- the correlation floor, the holds, the grid - is re-scored without decoding. It is off by
default: a corpus run should not leave two thousand of them behind.
