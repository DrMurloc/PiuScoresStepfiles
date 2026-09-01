# Where the repair project stands

`sources/repairs.json` is the authority on what is **fixed** — it is regenerated from the
tree by `tools/rebuild_repairs.py`, so it cannot go stale. This file is the working ledger
for what is **left**, and it is hand-kept: re-derive the counts before trusting them.

As of 2026-09-01: **42 of the 121 census charts repaired**, 79 remaining.

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

### B. Confirmed re-step, not re-tick — 11 charts

`grid_screen` says the file carries taps the game never judged, so the note grid is a
different chart revision: Trotpris SC D15, Poseidon SC S21, Another Truth D21, Can-can SC
D17, Extravaganza SC D16, Naissance S20, Mental Rider D22, Slam D24, Conflict S22, Break it
Down D21, Leather D22. Same extraction capability as group A.

### C. Needs frame forensics before a verdict — 4 charts

The observed run peaks already exceed `P + G`, so a counted "reset" is a misread and the
assembled curve is fiction until the boundaries are read off frames: Love is a Danger Zone
pt. 2 SC D23, Ignis Fatuus SC D21 (also shows missing content), Bad Apple D20, Desaparecer
D25 (51 breaks; its assembly comes out non-monotone, which is the tell that the run structure
itself is wrong).

### D. Reachable with the current pipeline — 1 chart

Can-can SC D21 (15 breaks, 23 holds, 534 ticks owed). The last of the tick-authorable pile.

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

## What this implies

Groups A and B are 65 of the 79, and they need the same thing: **extracting the note grid
from footage and diffing it against the file**. That capability also answers the standing
goal of validating every Phoenix 2 chart note by note, since a full-corpus validation is the
same operation run over 4,582 charts instead of 65.

Groups C, D and F are roughly ten charts of hand work with the existing tooling.
