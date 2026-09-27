# PiuScoresStepfiles

The canonical `.ssc` corpus behind PIU Scores chart analysis, plus the evidence and tooling
used to correct it. `simfiles/` is the **source of truth**; community packs, chart videos and
game patches are *evidence* for changing it, never truth themselves.

Read [README.md](README.md) for the layout. This file holds the working rules.

## Hard rules

1. **Never generate or repackage a snapshot zip unless the owner explicitly asks.**
   A regeneration is a ~90-minute unattended pipeline run plus a 32 MB commit, and it is the
   owner who uploads the result. Land repairs as commits and say the snapshot is now N charts
   behind; do not start the pipeline on your own initiative. See [docs/SNAPSHOT.md](docs/SNAPSHOT.md).
2. **A repair is not real until it is verified against the video.** Every fix must make
   piu-annotate's own converter derive exactly the judged note count from the certified
   result screen: `taps + ticks == judged`. `tools/tick_verify.py` is that gate.
3. **Evidence over inference, and say which you used.** Where the counter was actually read,
   say so; where closure arithmetic or the file's own profile filled a blind stretch, say that
   too. A commit message that overstates its evidence is worse than one that admits a gap.
4. **Never author a chart whose note grid disagrees with the video.** `tools/grid_screen.py`
   decides. A file carrying taps the game never judged needs re-stepping, and no tick schedule
   can fix it — authoring one produces a file that is exactly wrong in a way that looks right.
5. **Revert rather than ship a distribution you cannot defend.** This has happened three times
   (Exceed2 S16, Ignis Fatuus D21, Pumpnia S20) and each revert is itself a commit explaining
   why. An exact total with a fabricated interior is still a fabrication.
6. **Footage is never committed.** `videos/` and `work/` are gitignored.

## Owner rulings (2026-09-02)

- **One `.ssc` per chart, at the most recent mix we have evidence for.** No per-mix variants,
  no mix-selected overrides. Phoenix 2 is the ideal and waits on Phoenix 2 footage; a file at
  Phoenix 1 is "infinitely better" than one at an older mix. A chart already exact against
  Phoenix 1 footage is correct as it stands even where Phoenix 2 changed its count.
- **Model the file as close to the game as possible.** Where the game's timing, hold layout or
  tick delivery disagrees with the file, the file changes — surgically, with the video as the
  evidence — rather than the ticks being bent to fit the file's shape.
- **The snapshot is regenerated at roughly 100 repaired charts, not per batch.** Rule 1 still
  governs; this is the cadence the owner intends, so "N charts behind" is expected state.

## Environment

All tooling runs on the piu-annotate virtualenv, which owns the converter these repairs are
graded against:

```
C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe -X utf8 tools/<script>.py ...
```

`-X utf8` is required — the scripts print chart names, and Windows defaults to cp1252.

The clone must be on the `piuscores-windows-port` branch of the owner's fork,
https://github.com/DrMurloc/piu-annotate (`origin` in the clone; maxwshen's original is
`upstream`, and has none of our changes). Since 2026-09-23 its converter counts hold ticks by
the tick lattice (`HOLD_TICK_MODEL = "lattice"`, commit `e01246d`), and every repair here is
graded by that arithmetic. The grading tools refuse to run against a converter without it. See
docs/EVIDENCE-RULES.md, "A staggered release is not a tick". To set the clone up on another
machine, see docs/SNAPSHOT.md, "Setting up the clone".

## Loops

Unattended loops run on the rails (docs/TOOLS.md, "Running loops unattended", "Caches, reports
and commits" and "The corpus grade"):

- Every loop runs under `tools/supervise.py` (slot pool, gaming freeze, per-job timeout,
  heartbeats, an append-only run ledger) in its own worktree on a local `loops/*` branch, made
  with `supervise.py worktree` from a main that has the rails. Loops never commit to main and
  never push; whoever merges into main holds `supervise.py mainlock` while doing it, and first
  runs `corpus_grade.py gate --base main --head loops/<x>` **from main's own checkout** (the
  backstop for anything a pass did not see).
- Loops commit only through `tools/loopcommit.py` (the one commit lock, explicit paths, a
  `Loop-Run` trailer, checked results), only inside an open pass, and take work back only with
  `loopcommit.py revert-run`. A loop never commits what only the owner changes: the rails' own
  code (corpus_grade, guards, trace_audit, loopcommit, supervise, atomicio, childsite, the
  hooks), the oracle, `sources/demotions.jsonl` (a demotion is the owner's call and carries his
  `owner` field), `sources/protected-promotions.jsonl` and `sources/footage-corrupt.json`.
- Every commit pass runs through `tools/loopcommit.py pass`: `pass begin --run <run>` records
  the pass base, the loop commits, and `pass gate --run <run> --declared <N>` runs
  `corpus_grade.py gate --base <pass base> --head <HEAD> --declared <N>` (the commits, never the
  working tree). **No pass is judged by code the loop changed**: when the gate's own code (every
  `tools/` module the gate imports, trace_audit's closure among them, and the atlases) differs
  from main's, a pass that changes a stepfile is refused and the run halts until the owner merges
  that code into main; a pass that changes no stepfile is tools-only and passes without a gate.
  And no rails tool runs at all while anything under `tools/` is named like a real module
  (`tools/tempfile.py`, `tools/tqdm.py`: Python would load it in the library's place inside the
  gate) - `tools/shadowcheck.py` refuses it, exit 2, committed or not.
  The gate requires: PROTECTED does not shrink except through a
  `sources/demotions.jsonl` row; the net gain equals the declared ships; owner-revisit blocks,
  the oracle and the converter pin stay put; and **every new ship's trace audit is FLAT with
  every edit covered** (a GAINED chart audited against the import `a23cee5`, a re-edited exact
  chart against the pass base) - OFF, UNCOVERED and UNAUDITED do not ship. On FAIL, `pass gate`
  halts the run (its STOP) and reverts this run's commits back to the pass base. On exit 75
  ("retry later": the machine stopped the judgement) the pass stays open and the next `pass gate`
  gates the same base; never begin a new pass over an open one (`pass begin` refuses). Oracle
  changes are their own `--oracle-pass` commits, never mixed with stepfile edits.
- `work/STOP` stops every loop (`work/runs/<run>/STOP` one run); only the owner clears it.
- The snapshot rule is unchanged (hard rule 1): no loop regenerates or repackages a snapshot;
  each run reports "snapshot now N charts behind" and nothing more.

## Where to start

| You want to | Read |
|---|---|
| Fix a chart | [docs/REPAIR-WORKFLOW.md](docs/REPAIR-WORKFLOW.md) |
| Understand what the combo counter is telling you | [docs/EVIDENCE-RULES.md](docs/EVIDENCE-RULES.md) |
| Know what each tool does | [docs/TOOLS.md](docs/TOOLS.md) |
| Regenerate the annotation data (owner-requested only) | [docs/SNAPSHOT.md](docs/SNAPSHOT.md) |
| Know what is fixed and what is left | [docs/STATUS.md](docs/STATUS.md) |

## What "fixed" means here

`sources/repairs.json` is generated by `tools/rebuild_repairs.py`, which re-derives every
census chart from the files themselves rather than trusting a list. Never hand-edit it; run
the script. Every chart it lists has been proven exact against a certified video.

## Commit style

One chart (or one file's blocks) per commit, subject `Fix <chart> hold ticks`. The body names
the video, its result-screen numbers, the offset and how it was determined, the run structure
and how the peaks were settled, what the audit said, and the closing arithmetic. Someone
reviewing a year from now should be able to re-derive the number without re-watching the
video. Tooling changes get their own commits and explain the failure that motivated them.
