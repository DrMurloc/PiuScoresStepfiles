# Where the repair project stands

`sources/repairs.json` is the authority on what is **fixed** — it is regenerated from the
tree by `tools/rebuild_repairs.py`, so it cannot go stale. This file is the working ledger
for what is **left**, and it is hand-kept: re-derive the counts before trusting them.

As of 2026-09-01: **47 of the 121 census charts repaired**, 74 remaining.

## The remaining 79, by what actually blocks them

### A. Missing hold notes, not missing tick counts — 54 charts

This is the largest group and it is **not** the work the rest of this repo describes. These
files contain **zero hold heads** while the game judges 15–588 more events than the file has
taps (Slam D22: 506 tap rows, 0 holds, 494 events unaccounted). The holds exist in the real
chart and are simply absent from the stepfile, so there is nothing to re-tick — the notes
themselves have to be placed.

That needs a capability this repo does not yet have: reading hold starts, columns and
lengths out of footage. Authoring tick counts against holds that do not exist would produce
a file that is exactly wrong in a way that looks right.

Two Tier A charts sit here for the opposite reason — the file has **one or two more** taps
than the game judged (Set me up S10 at −2, Slam S5 at −1), so a phantom note has to be found
and deleted. Same capability, different direction.

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

### C. Needs frame forensics before a verdict — 4 charts

The observed run peaks already exceed `P + G`, so a counted "reset" is a misread and the
assembled curve is fiction until the boundaries are read off frames: Love is a Danger Zone
pt. 2 SC D23, Ignis Fatuus SC D21 (also shows missing content), Bad Apple D20, Desaparecer
D25 (51 breaks; its assembly comes out non-monotone, which is the tell that the run structure
itself is wrong).

### D. Reachable with the current pipeline — batch of 2026-09-01: 5 of 6 repaired

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

### F. OCR-blocked — 1 chart

Imagination S18. The video is legible to a human but the digit font does not match the atlas
and a hold rail runs through the digits. Five ground-truth readings are banked in the project
notes (148@40s, 267@60s, 386@80s, 059@100s, 179@120s) for a per-video atlas bootstrap.

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

Nothing here is wrong to fix against P1 footage — that is the mix the file describes. But a
Phoenix 2 validation pass has to decide what the corpus looks like when the mixes disagree:
per-mix stepfile variants, or a chart-level override that the pipeline selects by mix. That
is a design decision for the owner, and it should be settled **before** extraction work
starts, because it determines what extraction is even producing.

**Both charts are the owner's to revisit** (`sources/owner-revisit.json`, 2026-09-01). Their
current state is accepted: leave them alone, and do not raise them in an audit.

## What this implies

Groups A, B and D′ are 60 of the 79, and they need the same thing: **extracting the note grid
from footage and diffing it against the file**. That capability also answers the standing
goal of validating every Phoenix 2 chart note by note, since a full-corpus validation is the
same operation run over 4,582 charts instead of 60.

Groups C and F are 5 charts of hand work reachable with the existing tooling, plus Mental
Rider once its timing model is decided.
