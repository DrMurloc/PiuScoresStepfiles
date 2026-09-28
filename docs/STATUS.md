# Where the repair project stands

`sources/repairs.json` is the authority on what is **fixed** — it is regenerated from the
tree by `tools/rebuild_repairs.py`, so it cannot go stale. This file is the working ledger
for what is **left**, and it is hand-kept: re-derive the counts before trusting them.

As of 2026-09-23: **107 of the 121 census charts derive their judged count exactly**, graded by
the converter's tick lattice (below, "Hold ticks are counted by the tick lattice") - 104 of them
our repairs, three exact with their upstream block untouched. 14 remain. (As of 2026-09-06 the
count was 106 of 121 under the old arithmetic; twenty-nine of the thirty before that came
through the extraction pipeline in two days, group A.)

## The remaining 40, by what actually blocks them

### A. Missing hold notes, not missing tick counts — 53 charts (was 54)

> **The capability now exists (2026-09-02), and it runs.** `tools/extract_holds.py` surveys a
> chart's video for rails, `finale_ticks.py` prices them by closure, `auto_anchors.py` gives
> the grid verdict. Fifteen of this group landed in one day: Slam D22, S18, S20, 2006. LOVE
> SONG D14, She Likes Pizza D11, Csikos Post D16, Turkey March D13, Oh! Rosa D11, Dr. M D14,
> Beethoven Virus D13, My Way D16, We will meet again D11, First Love D15, Another Truth D18,
> Bee D15, Final Audition D19. The shape repeats: the game's finale holds begin on the file's
> **last row** (the file wrote the hold as taps on exactly the rail's columns) and most fire
> their ticks as a tail bomb. See REPAIR-WORKFLOW §6b.
>
> Since then: Final Audition D19, Final Audition 2 SC D19, Will-O-The-Wisp D20, Close Your
> Eye S6, Winter S16, Beethoven Virus D21, Gun Rock D24; and, priced rail by rail from the
> counter reads around each one (`rail_ticks` → `apply_rails`): Dr. M D18, Mr. Larpus D18,
> Final Audition Ep. 1 D15, Will-O-The-Wisp D16, Winter D17, Love is a Danger Zone pt.2
> [Another] S18 (a staggered triple), An Interesting View S13, Pump me Amadeus D15, Dr. M S9
> (its finale pair sits on cols 1/3 where the file wrote a 0+4 jump - the row was replaced).
> Four of those closed *exactly* on one finale hold once a single before-read was corrected
> in a frame (a 9 read as 5: Winter D17's 155 = 195, Dr. M S9's 254 = 294). Then Extravaganza D15
> (the finale pair is the whole deficit; the counter resets to 4 just before it), Caprice of
> DJ Otada S21 (three mid-chart holds off the 2P-side counter) and D22 (an *opening* pair
> hold on the first row carrying all 158 - the counter had to be rescanned, the old scan
> held no values), Vook D21 (a 9-tick hold early and a 436-tick finale bomb; the 44 other
> 'rails' were the video's preview), Naissance S20 (the file's mid pair re-priced 81 from
> frames - '52' was 92 - and a 456-event finale pair that is the entire run after a MISS).
>
> Surveyed and **parked** (holds the reader could not see, or a run structure the frames
> contradict): She Likes Pizza D18 — re-scanned at `min_len=0.15` it shows **15** rails, not
> three, and they price to about 176 of its 269 (36 + 76 on the two big ones, single digits on
> most of the rest, ~41 on the opening pair from frames). Roughly 93 events are still
> unlocated, so it stays parked rather than ship a guessed interior - its opening pair reads
> 045 in the frame, not 145, and its +99 run is a dropped hundred, so the tap grid is right
> and the missing events are ticks the counter never showed. Mr. Larpus S15 (its 42: one
> real hold is visible in frames - a col-2 mini-hold at beat 148 worth ~10 events, two stacked
> arrows arriving together - and the other ~32 are not; both other excess spots are plain
> drills the counter follows note for note, and drift shows a few extra file notes as well as
> missing ones, so it is a small grid revision, not a hold). We will meet again S13 (a
> different revision: the flash match is under 30% in every stretch of the chart at any
> offset, and the counter reaches its final 510 three to four seconds before the file's last
> row would arrive). Mr. Larpus S15 was previously listed here as (frames show notes on col 1 the file
> does not have - a re-step), We will meet again S13 (the game's intro is visibly sparser
> than the file's 16th stream - a re-step, whatever the grid screen says), Leather D22 (measured 2026-09-06: `run_drift` is +0 across its hold-free runs, so the
> grid is right and it is a re-TICK - 620 events owed over 227 file holds; `rail_ticks` at
> min_len 0.15 brackets ~48 rails for ~325 of them, one of those a leading-1 read, and the
> rest sit in reset-blocked rails and holds under the detector's floor, so its interior would
> still be a guess), Conflict S22 (beat 5917 at 116s: a BPM gimmick), Bee
> S17 — **repaired 2026-09-05**: that mid-chart hold never existed. Its whole evidence was one
> sub-4 junk read, which ends a segment and charges the climb after it as accrual; the finale
> alone is the 389, fired in a tenth of a second. Grid **mismatch** (the tap grid itself is a different revision):
> **Winter D21 and Extravaganza D18 came off this list too** - its 54 events are three
> mid-chart holds in one second, and its screen verdict is refuted by its own profile
> (+59, -58, +102, +78 cannot happen on a six-miss play). **Vook D15 and Mr. Larpus D16 came OFF this
> list** on 2026-09-05 - both were finale holds all along. Mr. Larpus D16 is the cautionary
> one: it screened at -116 on a play with 11 misses, because its own rails cross the counter
> and the play resets 14 times, so no curve could be built. `run_drift` measures the tap grid
> inside single runs instead and cleared it.
>
> The split-screen singles followed (the reader takes a half-screen band): She Likes Pizza
> S10, A nightmare S6, All I Want For X-mas S5, Will-O-The-Wisp S16, Final Audition S18,
> Beat of The War S16, My Way S15, Love is a Danger Zone S17. Caprice of DJ Otada S21 followed once its 2P-side counter was bracketed rail by rail (three real mid-chart rails, but the curve over-observes by 200
> - its structure needs frames).
>
> Dr. M D18 (nine rails) and Mr. Larpus D18 (four) came off the parked list with
> `rail_ticks` — each rail priced from the two counter reads bracketing it, no run
> structure needed; the 'reset inside' one was a leading-1 read and the '+143' a covered
> hundred. `apply_rails` then does the edit, regen and pinned pricing in one run.
>
> What is left in this group is the hard residue: charts where the reader sees no rail for
> the events owed, or the run structure will not settle without frame forensics at every
> reset. Every one is listed above with what it needs.

This is the largest group and it is **not** the work the rest of this repo describes. These
files contain **zero hold heads** while the game judges 15–588 more events than the file has
taps (Slam D22: 506 tap rows, 0 holds, 494 events unaccounted). The holds exist in the real
chart and are simply absent from the stepfile, so there is nothing to re-tick — the notes
themselves have to be placed.

That needs a capability this repo does not yet have: reading hold starts, columns and
lengths out of footage. Authoring tick counts against holds that do not exist would produce
a file that is exactly wrong in a way that looks right.

Two Tier A charts sat here for the opposite reason — the file had **one or two more** taps
than the game judged (Set me up S10 at −2, Slam S5 at −1). **Both are done** (2026-09-03):
`phantom_scan` reads the deficit off a perfect play's raw counter (the file's taps judged
≥150ms before a read minus the read steps to +1 for good at the phantom), and frame strips
named the rows — Slam S5's fourth intro jump, and on Set me up S10 the extra centre note
before each closing jump (the game's drills go side/centre/side/jump; the file had five
rows). Both wrong rows were nearly removed first: the counter alone cannot say *which* row
of a drill is missing, and the flash-matched offset was one beat late, which hides a
phantom exactly. See EVIDENCE-RULES.

### B. Confirmed re-step, not re-tick — 1 chart

`grid_screen` says the file carries taps the game never judged, so the note grid is a
different chart revision: **Slam D24**. Same extraction capability as group A. (Slam D24
keeping this verdict is consistent with its Phoenix 2 re-step, 1,004 → 704 notes; it is
also on the owner's manual-pass list.)

> **Leather D22 left this group on 2026-09-06.** Its -115 was the curve failing on a
> 37-reset play, the same way Mr. Larpus D16's -116 was: `run_drift` at the swept offset
> (11.30) is **+0** across every hold-free run, and no run drifts negative past its misses.
> The grid is right; the 620 owed events are hold ticks over 227 file holds. It is parked
> on that measurement (group A above), not on a verdict.

> This group was **eleven** charts until 2026-09-01, when an audit found the gate itself was
> wrong: `grid_screen` counted arrows instead of steps, so every jump counted twice and
> manufactured a deficit that looked like a bad grid. Nine charts flipped back to OK — they
> are in group D below. The repairs were never affected, because every tool that produces a
> fix counts rows correctly; the bug only ever rejected work. See commit `5afffcf`.

### C. Needed frame forensics — done, 3 of 4 repaired (2026-09-01, batch 2)

The observed run peaks exceeded `P + G`, so the assembled curves were fiction until the
boundaries were read off frames. Reading them settled three:

| Chart | What the frames said |
|---|---|
| Love is a Danger Zone pt. 2 SC D23 | the 58–64s miss cluster is four runs, not two; the 794 ending bomb rests by 68.3 = maxcombo |
| Bad Apple D20 | dropped hundreds and a rail's leading 1 on the finale; the final run is **58**, not the 121 the reader gave |
| Desaparecer D25 | twenty-six runs; MISS/BAD frames at 26.5, 115.2 and 128.9 and blank counters (under 4) at 52.5 and 121.9 fix the resets |

**Ignis Fatuus SC D21 is not a re-tick.** Its 541-tick opening is an *instantaneous* bomb
fired at chart 8.47s (the counter appears already reading 541, with no judgement before it),
while the file's only opening hold is 3.00–4.16s; the file's four ending holds judge as
nothing (the counter rests at 072 through the fade); and the clean mid-chart accounting
observes ~125 ticks against the 189 owed, a gap this footage cannot split between phantom
taps and blind ticks. The file does not model the game's timing gimmick, so it joins the
extraction pile (group G) rather than getting a forced distribution.

### D. Reachable with the current pipeline — batch 1 (2026-09-01): 5 of 6 repaired

| Chart | Commit | What it took |
|---|---|---|
| Poseidon SC S21 | `788597a` | the arrow-counting bug had hidden two intro stumbles; with them placed the head slack dip vanished |
| Extravaganza SC D16 | `7f649db` | hidden stumbles re-split by the slack profile (gap 3, not gap 4) |
| Can-can SC D17 | `fff361a` | two more hidden breaks found in the raw reads; 671+1 = P+G |
| Break it Down D21 | `ac7eb8c` | one 1.2s hold carrying all 617 ticks at ~514/s; resets hidden in blind stretches, GOODs drift priced in |
| Can-can SC D21 | `d1baa8a` | fresh scan; the "58" over-sum was a misread, nine near-zero miss-cluster runs |
| Mental Rider D22 | `9ed304d` (timing only) | **parked.** Its authored freeze gimmick (BPM 1.0 + a 999s stop one beat before the last hold's tail) gave it a 17-minute final hold in every release; that is fixed and the chart ends at 103.5s as the video shows. The tick repair is blocked: the counter bursts 18–40 ticks in half-second stretches that *trail* clusters of 0.03s micro-holds by 0.5–1s with no file hold beneath — either the file's 42-entry BPM map mis-times them or the game judges micro-hold ticks on a coarser grid. Needs a timing-model decision. Its `p2-082626` chartstruct CSV was regenerated locally from the fixed file so the tools could run (`.pre-timing-fix` backup kept). |

Every one of the five needed run-structure work the survey pass had not done: hidden breaks
inside blind stretches or miss clusters, priced by closure and placed by where the slack
profile fell. Two lessons are recorded in [EVIDENCE-RULES.md](EVIDENCE-RULES.md): GOODs make
slack drift down one per good, so a "minimal non-falling" solver over-asks by exactly the
goods before a bomb; and `fit2` beat-aliased again (Mental Rider: 12.62 reported, ~8.6 real).

#### Batch 2 (2026-09-01, evening): 4 of 5 repaired

| Chart | What it took |
|---|---|
| Imagination S18 | a per-video digit atlas (`cell_reader.py`): the font did not match and a rail ran through the digits |
| Love is a Danger Zone pt. 2 SC D23 | group C above |
| Bad Apple D20 | group C above; the first drill chart authored from 2s windows instead of per-hold brackets |
| Desaparecer D25 | group C above; 26 runs, 51 resets |
| Ignis Fatuus SC D21 | **not repaired** — gimmick, see groups C and G |

Drill charts changed the authoring method: a 0.1s hold cannot be bracketed by the curve, so
`window_targets.py` reads 2s windows off the curve and `windows_to_holds.py` splits them into
converter regions. `author_ticks` now reports authored-versus-target per region, because on
Bad Apple a "converged" total had quietly parked 182 ticks on one 0.2s hold.

### D′. Grid OK but the holds are missing — 4 charts

`grid_screen` passes these — the file's taps never outrun the counter — but the counter
ticks hundreds of times where the file has **no hold at all**: Another Truth D21 (666
out-of-hold, file has 4 holds), Naissance S20 (414 of 537, file has 2), Trotpris SC D15 (395
of 439), Conflict S22 (113, and over-ticked besides). A tick schedule cannot fix a hold that
is not there. Same capability as group A; the grid verdict just says the *taps* are right.

### E. Blocked on footage — 8 charts

- **All-miss plays** (`maxcombo 0`), which certify nothing: Blaze Emotion S2, An Interesting
  View S6, First Love S6, God Mode S4.
- **No result screen**: Conflict D26 — needs a checksum established at transcription time
  instead.
- **Owner-held cab-cam recordings**, not downloaded: Final Audition S7, Point Break S6,
  Mission Possible S7.

New footage would move any of these into a normal group.

### F. OCR-blocked — resolved

Imagination S18 was repaired in batch 2 with `cell_reader.py`: fixed-cell OCR with a
per-video digit atlas bootstrapped from eye-read frames. The same tool read Love is a Danger
Zone pt. 2's 2P counter. Atlases live in `tools/atlas-cell/<vid>/`.

### G. Gimmick charts the file does not model — 1 chart

Ignis Fatuus SC D21: instantaneous tick bombs at times where the file has no hold (see group
C). Needs the game's actual timing data or note extraction; a tick schedule cannot express it.

## Footage policy for a Phoenix 2 validation pass

Owner's rule (2026-09-01): **prefer Phoenix 2 footage; Phoenix 1 is acceptable for any chart
not suspected of note changes between the two mixes.** Where we find newer video than what
the database holds, record it — the owner bulk-updates the database from that list later.
Charts with no P2 footage *and* a changed note count are the worst case, and he will capture
those himself.

The note count is the signal for "did this chart change", and
`sources/p2-footage-needs.json` sizes it from the local prod-synced database:

| Charts | Situation | Footage |
|---|---|---|
| 2,988 | note count identical P1 → P2 | **Phoenix 1 is fine** |
| 16 | note count genuinely changed | **needs P2** — P1 footage is actively misleading here |
| 249 (29 songs) | chart exists only in P2 | **needs P2** — there is no P1 chart |
| 1,363 | no P2 note count in the database yet | **unknown**, and unanswerable until P2 data lands |
| 204 | chart dropped in P2 | out of scope for a P2 pass; P1 footage is all there is |

So the capture-card list is bounded at **265 charts today**, not the whole corpus — and the
16 changed ones are where P1 footage would silently validate the wrong chart. Some of those
deltas are enormous (Solve My Hurt SC D26 loses 540 notes, Destination SC D21 loses 360),
which is exactly the re-step signature `grid_screen` detects.

The 1,363 unknowns are a **data gap, not a chart-change estimate** — Phoenix 2 has not
released, so most note counts simply are not populated. Re-run the query behind
`p2-footage-needs.json` once they are; every chart that moves out of "unknown" into
"identical" is one more that Phoenix 1 footage covers for free.

### One stepfile cannot serve both mixes for those 16

`simfiles/` holds **one `.ssc` per chart**, and the annotation pipeline derives one set of
holds, ticks and NPS from it — but the site renders that analysis for both Phoenix 1 and
Phoenix 2. For a chart whose note count actually changed, no single file can be right for
both mixes.

This is already live, not hypothetical. **Destination SC D21 is repaired and verified exact
at 1,186 — the Phoenix 1 count — while Phoenix 2 lists it at 826.** The repair is correct for
P1 and wrong for P2 by 360 notes. Slam D24 (P1 1,004 → P2 704) is the other census chart in
this group, still open.

**Settled (owner ruling, 2026-09-02): one `.ssc` per chart, at the most recent mix we have
evidence for.** No per-mix variants and no mix-selected overrides. Phoenix 2 is the ideal and
is not reachable until Phoenix 2 footage exists; a file at Phoenix 1 is "infinitely better"
than one at an older mix. So Destination SC D21 at its Phoenix 1 count is correct as it
stands, and a chart moves to its Phoenix 2 shape only when Phoenix 2 footage certifies it.
The same ruling covers timing: model the file **as close to the game as possible**, which is
what decides Mental Rider's timing question and any gimmick like Ignis Fatuus's.

**Both charts are the owner's to revisit** (`sources/owner-revisit.json`, 2026-09-01). Their
current state is accepted: leave them alone, and do not raise them in an audit.

## What this implies

Groups A, B, D′ and G are 61 of the 70, and they need the same thing: **extracting the note
grid from footage and diffing it against the file**. That capability also answers the standing
goal of validating every Phoenix 2 chart note by note, since a full-corpus validation is the
same operation run over 4,582 charts instead of 61.

Everything the current tooling could reach has been reached, except Mental Rider (timing
model) and the eight footage-blocked charts in group E. The snapshot in `snapshots/` was
regenerated on the owner's word on 2026-09-21 (`piucenter-snapshot-092126.zip`, release
`p2-092126`): all 106 census repairs, the five tail repairs, the six Phoenix 2 v1.01 songs (59
charts) and The Resistance's three v1.01.0 fixes; then again the same evening as
`piucenter-snapshot-092226.zip` (release `p2-092226`, built on `092126`'s predictions) for the
four charts taken from their current files (the census, below). The snapshot is current. It is
regenerated only when the owner asks.

## Upstream, as of 2026-09-21

The corpus follows two upstream sources and they are not the same thing
(`simfiles/README.md`, `tools/resistance_packs.py`): the public mirror brings new arcade
songs, and The Resistance's MediaFire packs are the only place their fixes to charts already
published appear. Both were read on 2026-09-21, and everything The Resistance's v1.01.0
update changed in an official chart is in the tree. Later that day every pack on the hub was
compared with the whole corpus, block by block (`tools/pack_census.py`, below). The two charts
the mirror re-tags half-double (CALL ME BACK D6, L (PIU Edit) D19) are the pack's centre six
columns row for row, and the pack has nothing on the outer four panels there.

Seen and deliberately not taken, all from the packs:

- **Community UCS** on sixteen songs — the ingest filters UCS.
- **Relabels** in the PHOENIX, XX and PRIME 2 packs: Phoenix 2 re-rates (Passacaglia S8 → s7,
  Katkoi S11 → s10, Yoropiku Pikuyoro! S10 → s9, Asterios S10 → S11, All I Want For X-Mas
  S5 → s6 …) and "NEW" markers. Matched block to block on their notes they are the charts
  already here; this corpus keeps Phoenix 1 meters on purpose, because the charts lists match
  on the meter.
- **Asterios -ReEntry- S4** (PRIME 2 pack, entry dated 2026-08-25): same 120 taps and 8 holds,
  re-timed on a different `#BPMS` map over 33 measures instead of 17. First read here as "no
  note count can judge it" — wrong: the converter reads their file at 120 + 40 = 160, the
  catalog's count, where ours reads 144. It is one of the census's three, below.
- **Twist of Fate D21**: an `#ATTACKS` time moved from 50.000 to 51.163 — a display modifier,
  nothing the converter reads.

Fracture Temporelle D23 (1349 of 1350) and S15/S21 (one and three over) are still off after
the D26 fix; the pack's blocks are identical to ours there, so upstream has nothing for them.

### The whole-corpus census (2026-09-21): their current files against ours

`tools/pack_census.py` fetched, out of every pack on the hub, the 840 copies of our 664
stepfiles and compared every official block by its judged events and the six converter tags
(`sources/resistance-diff-2026-09-21.json`). 519 files and 4,393 of 4,689 blocks are
identical. 293 block pairs differ, and where the catalog can judge them:

| verdict | pairs | of the 2,207 tail charts |
|---|---|---|
| theirs exact, ours off | 3 | 3 |
| theirs closer | 23 | 22 |
| both exact — a redraw at the right count | 35 | — |
| same distance — both wrong by the same amount | 85 | 85 |
| ours closer | 23 | 23 |
| ours exact, theirs off | 119 | 5 |
| no reference | 5 | — |
| identical | — | 2,066 |

**The three they have fixed**, each re-checked with `tick_verify` on the pack copy:
DESTRUCIMATE S19 (ours 1478, theirs 1200 = catalog; the whole gimmick map re-encoded,
`#BPMS`/`#WARPS`/`#FAKES`, 1,712 events moved), Asterios -ReEntry- S4 (144 → 160 = catalog;
the `#BPMS` map re-timed) and Conflict D25 (1499 → 1500 = catalog; their D24, 140 events and
`#BPMS`/`#FAKES`). All three are block-level rewrites, which `apply_upstream_fix.py` refuses by
design — taking one means taking their whole block, with `tick_verify` as the gate.

**The 22 closer**: DESTRUCIMATE S21 (+165 → +10), D23 (+143 → +7) and D19 (+464 → +212),
Headless Chicken S21 (−45 → −5) and S19 (−30 → −15), Alice in Misanthrope S22 (+64 → −32,
ticks alone), and sixteen that move by one to four ticks — the Mahika charts, `* this game does
not exist *`, With my Lover D14, Good Night S23, Dream To Nightmare D22, Mental Rider D22,
Indestructible D25, Crossing Delta D23, Phalanx "RS2018 Edit" S22/D24. Closer is not fixed:
none of them reaches the count, so none would pass rule 2.

**Ours is ahead on 119**: the 106 census repairs and the 5 tail repairs, whose old versions
their files still carry, and eight where the seed was exact and their current file has drifted
off it — Maria D21 (1000 → 769), Club Night D12 (605 → 665), Scorpion King D16 (810 → 845),
Headless Chicken S15, Indestructible S12 and D15, Mahika D24, Solitary 2 D21. A newer file of
theirs is not a better one; a sync judges every block against the catalog and never adopts a
file.

**The same-count differences** (85 + 35) are mostly re-encodings — another beat grid or
`#BPMS` map carrying the same judged events, a thousand events "moved" at an unchanged total —
and touch nothing the converter derives. Of the five rows with no reference, three are Phoenix
2 songs with no Phoenix 1 count (Enjoy The Show D25, SUPER☆HARAGURO☆POP D24, Bassbook D25 —
same count both sides, not in the disagreement list) and two remain unjudged (Indestructible
D21, 1192 vs 1193; Phalanx "RS2018 Edit" D22, 1602 both).

**Odd ends**: their files no longer carry Adrenaline Blaster D23, Avalanche D19 (relabelled
"D19 OUCS", which the ingest filters) or Selfishness D20; the mirror's Murdoch vs Otada "D26
PENTAXEL UCS" is a plain "D26" in the pack, a UCS the catalog does not have; and the Phoenix 2
pack was **re-uploaded on 2026-09-21** (new quickkey, changelog unchanged) with one edit —
Can I friend you on Bassbook? lol D25 moves a two-arrow row at beat 66.25 one panel to the
right (`0000001100` → `0000000110`), count unchanged. The mirror does not have it.

Taken the same evening, on the owner's word: the three, as whole-block transplants
(`apply_upstream_fix.py --whole-block`, each gated by `tick_verify` at the catalog's count), and
the Bassbook row. The 22 closer were not — none reaches the count, and closer is not a repair.

(Compare half-double blocks by CELL, not by character: a `{…}` cell makes a row 22 or 26
characters wide, and slicing characters once reported The Last Rebellion D21 as a difference.
Tokenised, it is the pack's centre six columns on every row — the census does this.)

## The extraction loop (2026-09-22)

`tools/extract_repair.py` is the note-level loop the counter loop could not be: it reads each
certified chart off its footage, diffs it against the file, applies what the screen shows —
holds the file wrote as taps, releases in the wrong place, the odd missing note — and ships
only at the certified count (TOOLS.md has the rules). Proven before it ran: the five charts the
counter loop made exact came back untouched, and six manual repairs re-derived from their seed
files found the same holds in the same columns — Another Truth D18 all nine, Slam D22 640 of
642 events identical — parking only because their counts close on tick bursts the loop does
not author.

Two things it noticed on the way, both count-neutral under a closure-priced hold and both
for the frames to settle: the manual finale repairs on Csikos Post D16, Turkey March D13 and
2006. LOVE SONG D14 start their hold a row or a fraction of a beat *earlier* than the arrow
crosses on screen, and Get Your Groove On D10's hold head sits a quarter-beat later on screen
than the counter loop placed it.

### First corpus run (2026-09-22, four shards, ~2 min a chart, sprite passes cached)

All 1,342 certified tail charts (duplicate blocks skipped), per-chart record in
`sources/extract-loop-2026-09-22.json`:

| outcome | charts |
|---|---|
| **SHIP** — closed exactly and committed, one commit per chart | **13** |
| EXACT — already at the count | 7 |
| edits applied, count still off | 505 |
| extraction below the bar (recall or precision under 93%) | 478 |
| notes match the screen exactly; the count is ticks, not notes | 286 |
| stepf2 `{…}` cells in the note grid (the applier does not write them) | 49 |
| too many additions to believe | 4 |

The 13 (commits `a43f70c`..`df7516c`): PaPa Gonzales S16, Love is a Danger Zone pt. 2 S11,
Native S17 (holds the file wrote as taps); Higgledy Piggledy S15 and S16, With my Lover S12,
Life is PIANO S16, Lacrimosa S17, Kokugen Kairou Labyrinth S15, Dement ~After Legend~ S15
(releases moved to where the rail ends); Maria S12, Cleaner D26, Harmagedon D24 (a tap or two
added, each flashed at the receptor, and a release moved). Every commit lists its edits, what
the extraction saw, and what it did not apply. One of them did not survive the day: S15 and
S16 of Higgledy Piggledy share a song file, both candidates were whole-file copies made from
the file before either fix, and the S15 commit (`9e281f7`) put the S16 block back to +8 while
the in-place check read only S15 — re-landed as `f4767d1` from the file as it now stands, and
`commit` now refuses a candidate whose file changed outside its own block (TOOLS.md).

What the parks say, which is the census the loop was also for:

- **The reader is good on this corpus**: 1,293 charts read, recall against the file 99.6% at the
  median (99% or better on 805), precision 95.8%, timing error 4.5 ms.
- **The tail is mostly a tick problem, not a note problem.** 286 charts show the file's notes
  and holds exactly, count still off; and of every park, **493 sit within ±5 of the count** —
  181 at exactly +1, 108 at +2, 66 at +3. A release 40 ms off is one tick, and two experiments
  from cache showed the rail reader cannot place a release that finely (TOOLS.md). Those
  charts want the tick schedule and the release timing looked at together, with the counter as
  the judge — the counter loop's tools, aimed with this loop's hold list.
- **478 parked on the extraction itself**: 170 under 93% recall (the reader missing the chart's
  own notes — dense drills, gimmick scrolls, two of the owner's edge cases), the rest under 93%
  precision (extras a busy BGA throws); dropping the bar to 85% shipped nothing.
- **49 files write stepf2 cells** (`{2|n|1|0}`), which the applier did not edit. It does now
  (2026-09-23: the grid is edited by panel, and a fake-flagged cell is handed to the matcher as
  drawn-but-never-judged), so those files read like any other — the first of them through,
  Club Night D18, still parks at 83% precision, and its extras are *not* on its fakes: 133
  long streaks in columns 0 and 3 the file has nothing for, a BGA question for the frames.

Snapshot `092226` is now **13 charts behind**; it is regenerated only when the owner asks.
YouTube fetches are still refused from this network; the run read the 2,025 cached videos.

## Hold ticks are counted by the tick lattice (2026-09-23)

Pricing the first near miss from the counter (ASDF D10) found a pair of holds at beats 260–267
that piu-annotate's converter derived as 16 ticks and the game judged as 15: the converter
closed a segment on each release row and added a tick for it, so a pair whose holds let go on
different rows derived one tick per extra row, where the game judges the tick lattice once. It
also rounded rate × beats where the game counts whole lattice points (Cutie Song S11, Pumping Up
S10, ASDF D10's finale — each one tick over, each right as written). Counted over the 1,479
certified charts, 542 of the 1,364 off the count were over it by exactly their staggered release
rows, and the only exact charts carrying such rows were files we had fitted to the converter.

The model that carries both is the **beat-grid tick lattice** (EVIDENCE-RULES.md, "A staggered
release is not a tick", has the rule and the semantics the corpus settled). On the owner's go
the converter now counts by it — piu-annotate `piuscores-windows-port` commit `e01246d`,
`HOLD_TICK_MODEL = "lattice"`, the old counts still available as `hold_ticks="legacy"`:

| | old arithmetic | tick lattice |
|---|---|---|
| certified charts exact, of 1,479 (before any file changed) | 116 | **654** |
| charts the lattice broke that the old arithmetic had exact | — | 78 + 6 census-phase — every one a file we had fitted to the old arithmetic |
| hold regions the combo counter priced on full-combo plays (738) it agrees with | 698 | **719** — and 22 of the 23 where the two differ |

Every grading tool here now refuses a converter that does not count by the lattice, and a
snapshot built with upstream piu-annotate would carry the old counts (SNAPSHOT.md).

What it did to our own repairs (`tools/lattice_reauthor.py`, one commit per chart):

| | charts |
|---|---|
| reverted — the untouched upstream block is exact under the lattice (among them Conflict S22 and Sarabande S20, which the old arithmetic put 1,369 and 1,006 over) | 8 |
| reverted — a note-only repair that no longer closes, back to the loops (Higgledy Piggledy S15 and S16, Cleaner D26, Love is a Danger Zone pt. 2 S11) | 4 |
| re-authored — every region keeps its recorded count; only the regions the lattice counts differently get a new rate over their own span | 72 |
| of those, holds the repair had recorded below their own heads (zero events, possible only under the old arithmetic), raised to their heads with the difference taken off the closure they were priced from | 937 holds on 42 charts (508 on the four Tales of Pumpnia blocks) |

`sources/repairs.json` keeps every repair: **107 census charts exact** (106 before), Conflict
D26 joining on its untouched upstream block. Of the extraction loop's 13 ships of 2026-09-22,
nine were among the reverts — releases moved within the rail reader's tolerance that closed
only on the old arithmetic's staggered-release tick — and four stand (PaPa Gonzales S16, Native
S17, Maria S12, With my Lover S12).

## Both loops again, under the lattice (2026-09-23)

**The extraction loop's second corpus run** (`sources/extract-loop-2026-09-23.json`) re-graded
run 1's 1,342 tail charts and the census charts, reading footage only for charts not already
exact (`--exact-first`); the stepf2 files are read now too. On run 1's own charts:

| | run 1 (old arithmetic) | run 2 (lattice) |
|---|---|---|
| exact without an edit | 7 | **632** |
| shipped — closed exactly and committed | 13 | 8 |
| parked | 1,322 | 702 |
| parks within ±5 of the count | 516 | **98** |
| of them at exactly ±1 | 228 | 37 |
| parks: notes match the screen, the count is ticks | 286 | 133 |
| parks: stepf2 cells not read | 49 | 0 |

The eight (`2c374be`..`755b51a`): Imagination S12, Wedding Crashers S10, Fires of Destiny D22,
Star Command D22, Final Audition Ep. 2-X S17, Houseplan S17, Gun Rock D18 and Selfishness D18 —
releases moved later to where the rail ends, a tap or two each flashed at its receptor, one
hold the file wrote as a tap. Two of them (Imagination S12, Houseplan S17) are the same edits
run 1 proposed and parked at +2 and +3: under the lattice they land exactly.

**The tick loop's first run under the lattice** (`sources/tick-loop-2026-09-23.json`) took the
78 above-bar parks within ±10 of their count (420 under the old arithmetic) and shipped two,
each region re-ticked from counter plateaus within 0.6 s of it on both sides: Love is a Danger
Zone S11 (`8ee5b6b`; six regions each one event short, the running error stepping 0, -1 … -6
across them and flat in between) and YOU AND I D20 (`85c1edd`; the opening pair region, 48
judged where the file derives 53, read on sixteen of sixteen frames after it). 65 parks are
readings that do not sum to the deficit — the rest of the difference is in regions the counter
could not bracket, or in taps — 4 are plays with breaks where a region went unread, 4 had no
readable region. A first pass shipped three more and was stopped: one (Conflict S6) had priced
its last hold from a plateau 11 s earlier, carrying every tap between into the price, and the
tick loop now reads a region only from readings within 0.6 s of it (TOOLS.md).

After both: **738 of the 1,479 certified charts derive their judged count exactly** (116 under
the old arithmetic before any of this), and the census ledger stands at 107.

2026-09-27: the loaders had been dropping 11 eye-verified census certifications whose videos
the corpus ledger also read (a shallow merge in `corpus_map`); with them back it is **749 of
1,490** — 626 exact at the import itself (PROTECTED) and 123 by our edits (PROVISIONAL; 3 of
them since promoted by the trace audit, below, "The rails"). The live count is
`tools/corpus_grade.py grade`, recorded in `sources/corpus-grade.json`, and every loop's commit
pass goes through its gate (TOOLS.md, "The corpus grade").

Snapshot **`092326`** carries all of it — the first release whose hold ticks are counted by the lattice: of the
992 certified charts whose shipped ticks changed, 634 are now exact, 273 closer and 84 farther (files short on
ticks the old over-count had hidden). It is built, verified tick by tick against the converter, and waiting for
the owner's upload (snapshots/README.md).

## The rails (2026-09-27)

Bucket 1 of the loop plan (work/loop-buckets-2026-09-26.txt): the gate every loop commits
through, and the plumbing that lets loops run for days on this PC without corrupting the caches,
each other or main. Four parts were built and adversarially reviewed in their own worktrees and
integrated on the local branch `loops/rails` (grade, plumbing, supervise, audit; TOOLS.md has
each tool). No stepfile changed, so the snapshot is exactly as far behind as it was at
`8c9b5de`.

**The corpus grade, after the merge fix.** `corpus_map` had been dropping 11 eye-verified census
certifications whose videos the corpus ledger also read. With them back, the integrated tree
grades **1,490 certified, 749 exact: 626 PROTECTED** (exact at the import `a23cee5`) plus **3
promoted** by the trace audit (Get Your Groove On D10, Final Audition S18, Set me up S10), so
629 PROTECTED and **120 PROVISIONAL**, 0 errors (`sources/corpus-grade.json`). Under the old
merge the same tree was 738 of 1,479. Two grades of HEAD, cold (27 s on 6 workers) and warm
(3 s), are byte-identical. `corpus_grade.py gate --base main --head HEAD --oracle-pass
--declared 0` passes: exact 749 -> 749, PROTECTED 626 -> 629, the three PROMOTED, the oracle
and converter-pin change (none -> `e82d48350c50`) allowed as an oracle pass; without
`--oracle-pass` it fails on ORACLE alone. The planted-fault drills (24 gate cases, 11 oracle-pass
and tier cases, 7 on a hooked converter copy) all come out as intended on the integrated tree.

**The commit pass, after the integration review.** The gate now judges HEAD - the commits - unless
told `--worktree`, and it trace-audits every ship: a chart that becomes exact (audited against the
import) or a re-edited exact chart (against the pass base) must audit FLAT with every edit
covered, so OFF, UNCOVERED and UNAUDITED do not ship. `loopcommit.py pass begin` / `pass gate`
package the pass: the base is recorded, a FAIL halts the run and reverts its commits after the
base, and a "retry later" (the new exit 75, the machine and never the work) keeps the pass open
for the same base. Come to Me S17, re-shipped over its import block in a scratch loop worktree,
is refused and reverted; Get Your Groove On D10 the same way passes.

**No pass is judged by code the loop changed (round 2).** The second review found the gate ran
the worktree's own tools, so a loop could change what judged it: a commit that made the gate
forget its failures let a Slam D24 edit pass, and a `corpus_map.py` that dropped BRAIN POWER D14
from the population hid its break (PROTECTED 628 -> 628, PASS). `pass gate` now holds the gate's
code (every `tools/` module the gate imports - trace_audit's closure among them, 20 modules - the
atlases and childsite) to main's: a stepfile pass on a branch whose gate code differs is refused
and the run halts until the owner merges that code into main; a pass that changes no stepfile is
tools-only and passes without a gate. A loop never commits the rails' own code, the oracle,
`demotions.jsonl` (every row a change adds needs the owner's `owner` field, which the gate
enforces too), `protected-promotions.jsonl` or `footage-corrupt.json`; it commits only inside an
open pass, and no pass begins over a `Loop-Run` commit no gate saw. In a scratch clone the
review's probes - the neutered gate (committed through loopcommit, left in the working tree, or
committed around it), the corpus_map population shift (in one pass and in two supervised
passes), the two-pass self-demotion, a planted `tools/cv2.py` - are each refused before any gate
runs, and the merge gate run from main's checkout FAILs the branches that went around loopcommit
(OWNER-REVISIT Slam D24, LOST BRAIN POWER D14). **Before fast-forwarding any loop branch into
main, run `corpus_grade.py gate --base main --head loops/<x>` from main's own checkout.** Loops
must branch from a main that has the rails: until `loops/rails` is merged, every stepfile pass on
a loop branch is refused, because its gate code is not main's.

**The trace audit's corpus** (`sources/trace-audit-2026-09-27.json`, audit_version `d2cdb262`,
head `02ce4ff`; changes since - docstrings in `atomicio` and `combo_reader`, then round 2's
command-line check in `trace_audit` itself - moved the version to `1d0e0fac` without moving a
verdict: a `--no-decode` rerun reproduces all 123 chart records and the same three promotable
blocks. The ledger predates those moves, so a rerun marks its calibration and power sections
stale; it is re-recorded once, on the merged tools, when the rails merge into main - `trace_audit.py
controls`, `power` and then `corpus --out-dir sources`, which appends the three promotions again
under the new version):
the 123 edit-derived exact charts audit **3 FLAT, 10 OFF, 110 UNCOVERED**, 0 errors. FLAT means
a strong counter read at level 0 within 8 judged rows on both sides of every edit; only those
three are promoted. The 261 untouched exact controls give 0 OFF (17 FLAT, 244 UNCOVERED).

**What the audit cannot see.** Its FLAT is earned only on full-combo plays and the few plays with
breaks whose reads hold one run on both sides of an edit. On plays with breaks it detects
nothing: 0 of 235 planted compensating pairs audit OFF (233 UNCOVERED, 2 FLAT, both pairs one row
apart), because most such plays split into more runs than they have BADs and MISSes. A play with
GOODs never audits FLAT. Pairs within 8 judged rows are inside its resolution (34% of those
within 4 rows audit FLAT on full combos), and an edit the counter priced through hold lengths
under an unchanged `#TICKCOUNTS` is not bracketed, so its own pricing reads vouch for it. There
is no control at level 24+ with a full combo, so it has no measured power there.

**The OFF charts, listed, not demoted.** Ten edit-derived exact charts read OFF inside while the
total is exact. None is demoted or reverted here: the Phoenix 1 counter atlas misreads 9s (bucket
3), and each waits on that fix and a re-audit before anyone decides.
- Houseplan S17 (`3d17dae`) and Wedding Crashers S10 (`c40c089`) - already quarantined, with
  Imagination S12 (`2c374be`, UNCOVERED), for the owner's review.
- Seven census-phase counter-loop repairs, where small mid-chart tick cuts each step the
  counter's level by their own size and a closure-priced finale absorbs the total: K.O.A : Alice
  in Wonderworld SC D18, Pop The Track SC D16, Wedding Crashers SC S4, XX OPENING SC S6, Come to
  Me S17 (a distant +5, 42 rows away - possibly a misread beyond the documented 9-as-5), Dr. M S9
  and 2006. LOVE SONG D14.
- My Way S15, one of the 11 restored census charts: a +7 level held from 77.0 s to 96.3 s over
  267 reads, 8 rows before its finale edit.

**Housekeeping.** `tools/fsck.py` over the shared caches: no 0-byte or unloadable file (1,413
sprite passes, 4,462 receptor files, 724 counter scans, 195 reports); 1 truncated scan,
`-1hzF02vOFc.R` (44 s of a 185 s video that decodes on), quarantined to
`work/quarantine/fsck-20260927-103814/` and rescanned to 185.2 s, sealed. Five cached videos
are recorded as unusable in `sources/footage-corrupt.json`, and loops now give their charts
FOOTAGE_CORRUPT instead of PARK: D6Th6URU1Sk and E1LYZv8mCjE (no moov atom), 0T1_HBRTVLc (Chicken
Wing S9/S11, stops decoding at 76 s of 125 s), 1rcd4MaRTDg (Alone D18, 62 s of 128 s) and
AiNqD7lZjiM (Beat of The War S21, 66 decode errors and a stop at 15 s). The owner-revisit list is
now enforced in every worklist that can ship: Slam D24, which sat in the extraction loop's
worklist as a PARK, is skipped with its reason.

## Lane geometry, first checkpoint (2026-09-27)

Bucket 4 of the loop plan, on the local branch `loops/lanes-1`: fit the lanes right on every cached
video, because every reader looks through them and a misfit field is the largest measured
extractor bug class. Nothing here changes a stepfile, the extractor or `receptors.field()`; the
snapshot is exactly as far behind as it was at `f27b6ef`. Tools: `laneband.py`, `lanefit.py`
(TOOLS.md).

**The median-band cache.** `receptors.field()` fits a video's lanes from one picture, the median
of 64 seeked frames; `laneband.py` stores that picture per video (`work/lanes/medband/`, about
170 KB each, lossless, under its own key - the `.inset` caches other loops read are untouched), so a
rule is arithmetic over it. Two supervised runs build it: `lanes-1-medband-h264` (1,838 videos,
2 at a time) and `lanes-1-medband-av1` (181, 2 at a time), plus `lanes-1-medband-sample` (the band
sample below, finished). On a shared machine at 100% CPU a picture costs 15-20 s on h264 and a median
357 s on AV1 (58 s alone; one AV1 video, HQPXvKtFDtA, ran past its hour and waits for a sweep); at
this checkpoint 921 of 2,019 videos are cached. The preflight re-fits eight known videos from a
fresh decode through `_fit_field` itself and through the cached-picture arithmetic: 8 of 8 give
the cached `.inset` bytes, and the pictures the supervised run cached equal the fresh decodes.
Those eight are all h264, while every PHOENIX 2 held-out upload is AV1 (and four official uploads
are VP9), and no AV1 or VP9 video has a cached `.inset` fit; so the preflight now also probes one
AV1 and one VP9 official upload carrying only tune charts: the decode reports the named codec,
`_fit_field` and the arithmetic agree on the same fresh decode, and the cached picture equals it.
Run as `lanes-1-preflight2` (2026-09-27 20:11, cv2 5.0.0): the eight h264 videos again 8 of 8, and
both probes agree - AV1 (390 s under contention) and VP9 (64 s) give the same fit through
`_fit_field`, the fresh arithmetic and the cached picture, which equals the fresh decode.

**Frozen before any rule ran** (`sources/lanes/`, each with its own sha256). The **partitions**:
held out are the 101 PHOENIX 2 official-pack charts whose file converts to the map's count and
the 36 certified misfits; charts named in the docs, tools, loop proposal or a research note go to
`seen` (tune-only); the rest are grouped by song family and video and split into a validation and a
sealed half. The **BEFORE census**: 2,161 fits (certified charts, both fields of every official
singles upload - the pad is never taken from the map's stored side - and every cached `.inset`
fit), 1,351 with a fit on disk, each stamped `field.inset@627dede7f324b0d4`, with a template from
metadata (channel group, band, columns). The **pitch bands**, from a band sample chosen before any
band was computed, out of the sample fits that pass their independent invariant: NEVSISTER doubles
75.00-76.10 (centre 75.50), NEVSISTER singles 74.90-76.30 (75.80), official doubles 74.53-75.90
(75.30), official singles 73.90-75.50 (74.60). Only 30 of 175 official doubles fits and 126 of 253
official singles fields pass - the official uploads' fits are mostly misfits, at 66.9-67.4 for
doubles and 57.1-58.0 for singles fields, so the pitch histogram's own median (67.3 for official
doubles) would have set the band on the misfit.

**The partitions were corrected once (v2), before any F1.** Verification found v1's `seen` scan
too narrow: it matched only the exact string "Title Level", so a sealed chart the extraction notes
name as "Legendary Dominion S20 and S16" stayed sealed, and so did the census rows of its video,
which also carry the seen S20; a validation chart named as "DESTRUCIMATE S21 (...), D23 (...)"
stayed held out too. Partitions v2 reads the same text (the docs, tools and root notes as committed
at the v1 freeze, `9f8baf6`, so nothing written after a look can move a chart), matches a title and
its level token within one phrase, and makes every held-out chart on a video that carries a named
chart `seen`; a census row carrying a seen chart is seen. Four charts moved (DESTRUCIMATE D23,
Legendary Dominion S16 and S22, Magical Vacation S18), six census rows with them, and nothing moved
back. `seen` is now 31 charts; validate 55 (44 scorable), sealed 51 (41 scorable). The correction
is logged in `heldout-looks.jsonl`: the only held-out result seen before it was rule 1's verdict
counts, no extraction and no F1, and the V5gJ5gKqTi0 rows were not cached then.

Two things the partitions do not do, measured rather than fixed. The scan reads a research file
only when it is a script, text or JSON of at most 20 KB that names at most ten corpus charts (a
longer listing is a script's output over a population, not a look at a chart). 105 held-out charts
are named in research files it does not read, but none in a file naming ten or fewer: 29 appear at
best in files naming 11-30 (mostly the misfit stratum's own discovery listings, such as
`ext/lowsharp_below.txt`, and a counter probe of five official charts), 76 only in larger ones.
And the split is grouped by song family and video only between the two halves, not against the
tune side: 14 song families span `seen` and the halves, 86 tune census charts in 27 families share a
held-out family, and 7 band-sample videos - the videos the frozen bands and receptor library were
computed from - carry a held-out family. So the bands and the library were
recomputed without those 7 videos (`lanefit.py sensitivity`, after a recompute with nothing left
out that reproduced the frozen bands and library exactly): **no band edge or centre moves in any of
the 14 templates**; passing fits drop by at most 2 per template, and the NEVSISTER library is built
from 38 fits instead of 40 (its effect on singles NCC was not re-measured). Nothing was refrozen.

**The invariants.** Twin agreement for doubles (lane k against lane k+5, the same receptor): 0.92
at the lowest over 261 in-band doubles fits, 0.28-0.61 on the out-of-band ones. For singles the
pad twin - one field of a split screen against the other - does not work: both fields of an
official singles upload misfit the same way and agree at 0.97-0.999. So a singles fit is graded by
NCC against a receptor library built from twin-passing doubles fits of its channel group
(`receptor-library-2026-09-27.npz`): 0.85 at the lowest over 467 in-band singles fits, 0.32-0.74 on
the out-of-band ones.

**Rule 1** (`r1-oob-sym-respan`, registered with its stamp `ed51b24b80575c80` and the validation
effect it must show, before it ran): a fit out of its template's band whose picture is
mirror-symmetric re-searches its span - peaks standing symmetric about the mirror axis whose pitch
lands in the band, or, when no pair does, one peak mirrored about the axis (on split screens one
outer ridge often fails to stand as a peak of its own) - and a re-fit is kept only when its
invariant reaches 0.80 and beats the old fit's by 0.10. Over the finished part of the cache (904
videos when it ran): 1,083 fits recomputed, and the 482 that have a cached `.inset` fit came back
byte for byte - that is the identity evidence. 728 were in band and are left alone; the rule hands
an in-band fit back as the BEFORE fit itself, so "identical" is true there by construction and
proves nothing beyond the recompute (when the rule is promoted, in-band identity is checked through
the promoted `receptors.field()` against the `.inset` bytes). **351 re-fitted and accepted, 0
rejected by the invariant, 4 to the exceptions ledger.** The 197 doubles re-fits went from twin
0.28-0.61 to 0.89-0.98 (from pitches 51-72 to 75.2-75.6; 184 found a symmetric pair at the first
floor, 12 needed the mirrored peak); the 154 singles re-fits from NCC 0.32-0.74 to 0.81-0.99 (from
56-69 to 74.2-75.8; 53 by the mirrored peak). Of the 36 certified misfits, all cached: 35 re-fitted
and accepted, 1 an exception. The four exceptions, none re-fitted and the band never widened for
them: two asymmetric pictures (one a sealed-half chart at 49.4; an official singles field at 51.3),
one fit that raised at a 28 px pitch and whose picture is asymmetric, and one NEVSISTER singles fit
at 73.1 (NCC 0.67) with no peak that reaches its band. Nothing was rescued from a raise.

**What this is not yet.** Twin and NCC say the lanes now sit on receptors; they do not say the
extraction got better. That is the held-out gate: per-chart F1 against the count-exact files
through the old and the new lanes on the validation half (sign test, pre-registered effect), then
the sealed half once - which needs sprite passes through the re-fitted lanes, and waits for the
cache to finish. Nothing is promoted into `receptors.field()` before it passes. The held-out rows
were run through the rule for the checkpoint report (their verdict counts only, no extraction and
no F1), logged as one look per half in `sources/lanes/heldout-looks.jsonl`. That look and its
commit name one sealed chart; both are append-only, so the name stays there, the chart stays sealed
(moving it would select on a verdict already seen), and these notes no longer name sealed charts
until the sealed half is scored. Rule 1 now runs the tune side (`tune`, `seen`) by default, a
held-out half only with `--heldout-look` (logged, output under `work/lanes/heldout/`), and the
checkpoint's output was split the same way: the exceptions ledger a later rule is developed on
holds tune-side rows only (3 of the 4). Which pad is which on the official split screens is not
decided here and will not be taken from the map's stored sides: it needs a 2x2 column+time F1 matrix
from extractions of both fields.

## Beyond the census (sized 2026-09-06, listed in full 2026-09-08)

The census was the *blatantly* wrong 121 — its cut was narrow on purpose: taps above the
judged total, a hold-less file against a holdy game, or a total off by more than **50%**. A
chart off by 10% with holds in it was never in scope. `sources/tail-2026-09-08.json` is
everything else, measured the same way by `tools/catalog_sweep.py` — every block through the
converter (`tick_verify`'s own rule) against the catalog's Phoenix note count, matched through
the pack's own mix (a Rebirth-pack S13 is Phoenix's S17), videos from the site's banked
`ChartVideo` rows:

- 4,581 blocks converted; 4,495 matched to a catalog chart, 62 ambiguous, 24 unmatched
  (title variants: Allegro Piu Mosso, Bullfighting's Song, Close Your Eyes, Tream Vook of the
  war REMIX, the Baroque Virus / Gargoyle full-song v1/v2 pairs), 37 without a count yet.
- **2,234 exact.** 2,224 disagree: 17 census keys (the 15 open ones plus two matcher
  artifacts - Come to Me's S13-key and XX OPENING SC S6 are exact at their video counts) and
  **2,207 beyond the census — every one of them named in the file**, whatever the size of the
  gap: 1,181 within 1% (388 are a single note), 305 at 1-5%, 370 at 5-20%, 348 at 20-50%,
  3 past 50%. None has more taps than the game judges. All 2,207 have a banked video.
- By shape: **1,526 over-ticked** (authored `#TICKCOUNTS` above the game), **603
  under-ticked**, **30 single-region** (one hold carries the whole difference - closure would
  price it exactly), 10 hold-less, and 38 that are the *second* corpus block of a re-rated
  chart (an old pack's level). Of the 721 gaps past 5%, 570 sit at levels 15-24.

What the census taught applies unchanged: the game's tick counts follow no per-beat rule
(EVIDENCE-RULES, "No per-beat tick rate"), so a hold is priced by its footage or not at all.
A chart with one hold region can be closed on its total alone; Everybody Got 2 Know S21 has
**101** of them for a 131-note surplus, and splitting that without footage would be a guess.
Nothing here is authored: this is the worklist for a scope decision, not a batch in progress.

## The closed loop, and what a first batch of 80 actually yielded (2026-09-08)

`tools/batch_repair.py` runs the whole chain unattended - certify, measure, gate, author,
verify, commit - and parks everything it cannot prove, with a machine-readable reason. It is
real: **four charts beyond the census are repaired and committed by it** (Blazing S17, Love is
a Danger Zone SC S13, Smells Like A Chocolate S3, 2006. LOVE SONG S15), each verified by the
converter against the catalog count.

The first batch was 80 charts chosen to be *favourable* - the 30 single-region and 10
hold-less shapes plus 40 mid-sized gaps. `sources/tail-pilot-2026-09-08.json` is the full
result. **3 shipped, 1 was already exact, 76 parked**, and the parks are the interesting part:

| why it parked | charts |
|---|---|
| a hold region could not be priced from the counter | 30 |
| the file is an older revision (footage agrees with the FILE, not the catalog) | 15 |
| the priced total disagrees with what the chart owes | 9 |
| three-way disagreement between footage, file and catalog | 5 |
| no readable result screen / no offset fits the flashes | 8 |
| the grid is a re-step, not a re-tick | 3 |
| several hold regions need pinning - deliberately not automated | 2 |

Read it as three separate problems, because they have three different fixes:

- **28 of 80 are footage-limited** and no amount of tooling helps. Fifteen of those are files
  that are simply *correct for an older mix* - the play in the video and our .ssc agree to the
  note while only the catalog dissents. Twenty of the 79 videos are the old result-screen skin,
  which is what dates them. Those need Phoenix-era footage, not an edit.
- **34 are counter-limited**: the rails are visible, but the combo counter is unreadable or
  resets somewhere around one of them, so a region cannot be priced. This is the single
  biggest lever on throughput, and it is a reader problem, not a gate problem.
- **2 need multi-region pinning**, which is the shape of the whole over-ticked bulk (1,526
  charts). Blazing D21 already has every region priced and its total inside tolerance; it ships
  the day that mapping is automated.

So the loop works and is safe, and on this slice it converts about one chart in twenty. It is
not yet "point it at two thousand charts and walk away", and the honest order of work to make
it so is: the counter reader first, region pinning second, footage third.

## The other half of the repair: newer footage (2026-09-09)

A chart pointing at pre-Phoenix footage cannot be repaired *and* shows the player the wrong
video. Nevsister re-shot most of what changed between XX and Phoenix, so for a large group the
fix is a newer video rather than an edited stepfile.

`tools/video_freshness.py` matches the channel walk's 7,579 titled uploads against the catalog
and finds **218 charts whose banked video is provably older footage** than what exists - 203
XX -> Phoenix, 13 Phoenix -> Phoenix 2, 2 XX -> Phoenix 2 - over 182 videos, every one of them
still live (checked by keyless oEmbed). `tools/video_refresh_sql.py` writes those as guarded
UPDATEs, plus 9 side corrections where only one half of a split screen was moving.

**`Downloads\chart-video-refresh-2026-09-09.sql`** - run it, then Clear Cache. Every guard was
dry-run against the current ChartVideo rows: 218 of 218 match.

Six of the fifteen charts the repair loop had stuck on old-revision footage are repaired by
this script alone. The rest are in **`sources/footage-needed-2026-09-09.json`** - 16 charts
nobody has posted current-mix footage for, and they are the owner's to record: 7 whose note
count changed between Phoenix 1 and Phoenix 2 with no Phoenix 2 upload (BEMERA S24, Burn Out
D20, Crimson Hood S24, HTTP C2, Monolith D22, Necromancy S20, Windmill D18 - the other 9 of
those 16 changes Nevsister has already shot), and 9 whose footage and stepfile agree with each
other against the catalog, where the newest upload is still the old-era one.

## The counter reader was not the lever (2026-09-09)

The first batch said the top blocker was the combo counter: 34 of 80 charts parked because a
hold region could not be priced from it. Two changes went in, both measured:

- **`rail_ticks` now brackets from the whole window** rather than the single nearest read (see
  EVIDENCE-RULES). Judged against every chart's owed total: never worse than the old reading,
  right where it was wrong once.
- **`finale_ticks --pins-json` takes measured prices in chart seconds**, and the driver maps
  each measured hold onto exactly one of the file's regions or parks. Multi-region charts can
  now ship when the evidence covers every region.

**They bought one chart.** Get Your Groove On D10, whose raw bracket read 102 against the 2 it
owes. Re-running the batch: 1 new ship, 4 already exact, 75 parked - and the 30 charts blocked
on an unpriceable region **did not move at all**.

That is the finding, and it is worth more than the chart: those 30 are not a processing
problem. The counter is genuinely unreadable beside those rails - the rail is what covers it -
and no post-processing recovers information the frames do not contain. Two rejected approaches
are written up in EVIDENCE-RULES so nobody spends the day again: a global continuity repair
rewrites prices that were already right, and a lower confidence floor poisons the window.

Region pinning also turned out to be aimed at the wrong thing. The two charts that reached it
(Blazing D21, Money S14) have ONE hold region in the file and TWO on screen - the game holds
where the file has nothing at all. That is a missing note, not a mis-priced one, and it wants
`apply_rails` extended to a file that already holds elsewhere.

If the counter is the wall, the way through is a different measurement rather than a better
reading of the same one - the in-play SCORE display also steps on every judgement and does not
sit under the rails. That is the next thing worth trying.

## What guards the process (2026-09-09)

There are now three layers, and they fail differently:

| | what it proves | needs footage |
|---|---|---|
| `tools/selftest.py` | the parsers and title matchers still read what the tools print | no, ~1s |
| `tools/golden.py` | seventeen known charts still *analyse* the same way | yes |
| `tools/rebuild_repairs.py` | every census file still converts to its note count | no |

The golden set is the new one, and it is deliberately **nine parks to five repairs** (plus
three census charts whose evidence is documented and tricky - Bee S17, Leather D22's +0 drift
on a 37-reset play, Mr. Larpus D16 which only `run_drift` could clear). A gate that loosens is
the failure that costs something, and only a chart that must not ship can catch it.

It was verified by breaking the pipeline on purpose: disabling the rule that a pair shares one
bracket made Smells Like A Chocolate S3 fail with `rails_total: expected 15, got 27` - exactly
the bug that rule was written for.

**Charts to validate by eye**, if you want to spot-check what the loop decided: the five it
repaired - Blazing S17, Love is a Danger Zone SC S13, Smells Like A Chocolate S3, 2006. LOVE
SONG S15, Get Your Groove On D10. Each is one hold region whose rail the counter priced within
a couple of events of what the chart owed, and each verifies exactly against the catalog. The
census's own 106 are already validated by their own evidence.

## Where the closed loop actually stands (2026-09-09)

The loop is finished: `tools/run_corpus.py` fetches, certifies, surveys, authors, commits and
reports in one command, resumable, with no decision points. It is guarded by `selftest.py` and
`golden.py`. Autonomy is not what is limiting this any more.

**Evidence is.** The tail holds exactly **40** charts of the shapes that can be priced - one
hold region, or no holds at all - and the first batch ran **all forty**. What is left is 2,089
multi-region charts, and the batch went **0 for 40** on that shape. The reason is structural: a
multi-region chart only ships when EVERY region is priced from the counter, and the counter
sits in the middle of the play field where the rails cover it.

The idea of reading a different number instead is dead - **Pump It Up shows no score during
play**. The combo counter is the only per-judgement signal on screen, and it is the one the
rails cover. For these charts the information needed to price the interior is not in the
footage, and no reader improvement produces it.

So the corpus run now in progress is **a certification census, not a repair drive**, and its
value does not depend on the repair yield:

- it certifies all 1,927 videos, which is what tells a broken file from a file that is simply
  **correct for an older mix** - 19% of the first batch turned out to be that, not broken;
- every one of those feeds the video-refresh SQL and the recording list;
- whatever the gate can still prove, it repairs and commits on the way past.

Expect very few repairs out of it. The deliverable is knowing, chart by chart, which of the
2,206 are actually wrong.
