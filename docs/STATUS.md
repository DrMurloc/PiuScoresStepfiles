# Where the repair project stands

`sources/repairs.json` is the authority on what is **fixed** — it is regenerated from the
tree by `tools/rebuild_repairs.py`, so it cannot go stale. This file is the working ledger
for what is **left**, and it is hand-kept: re-derive the counts before trusting them.

As of 2026-09-05: **103 of the 121 census charts repaired**, 18 remaining. Twenty-nine of
the last thirty came through the extraction pipeline in two days (group A).

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
> contradict): Final Audition Ep. 1 S17, She Likes Pizza D18 (three rails price 153 of its
> 269; the closure solver's third run was built on junk reads and the rest cannot be located
> - a frame walk of the whole chart), Mr. Larpus S15 (frames show notes on col 1 the file
> does not have - a re-step), We will meet again S13 (the game's intro is visibly sparser
> than the file's 16th stream - a re-step, whatever the grid screen says), Leather D22 (31
> rails on screen against 227 holds in the file and a 37-reset play - a re-tick job not
> attempted), Conflict S22 (beat 5917 at 116s: a BPM gimmick), Bee
> S17 — **repaired 2026-09-05**: that mid-chart hold never existed. Its whole evidence was one
> sub-4 junk read, which ends a segment and charges the climb after it as accrual; the finale
> alone is the 389, fired in a tenth of a second. Grid **mismatch** (the tap grid itself is a different revision):
> Winter D21 (its finale pair is plain on screen, but the file carries ~40 taps the game never
> judged around 60-75s). **Extravaganza D18 came off this list too** - its 54 events are three
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

### B. Confirmed re-step, not re-tick — 2 charts

`grid_screen` says the file carries taps the game never judged, so the note grid is a
different chart revision: **Slam D24** and **Leather D22**. Same extraction capability as
group A. (Slam D24 keeping this verdict is consistent with its Phoenix 2 re-step, 1,004 →
704 notes; it is also on the owner's manual-pass list.)

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
regenerated at 97 charts on the owner's word (2026-09-04, `piucenter-snapshot-090326.zip`,
release `p2-090326`) and is current; it is regenerated only when the owner asks.
