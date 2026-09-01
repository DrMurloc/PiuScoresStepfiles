# Regenerating the annotation snapshot

> **Do not run any of this unless the owner explicitly asks for it.**
>
> A full regeneration is ~90 minutes of unattended pipeline plus a ~32 MB commit, and the
> owner is the one who uploads the result at `/Admin/PiuCenter`. When repairs land, the right
> move is to say *"the snapshot is now N charts behind"* and stop there.

## What the zip is

`snapshots/piucenter-snapshot-<MMDDYY>.zip` is the batch `/Admin/PiuCenter` imports:

```
version.txt                    the release stamp, compared by the importer
page-content/                  chart-table, stepchart-skills, tierlists
<CHART_KEY>.json               one per chart, at the zip root (4,582 currently)
stepfiles/<pack>/<song>/*.ssc  the 658-file corpus the release was generated from
```

Exactly one current zip lives at HEAD; superseded ones are deleted (history keeps them).

## Running it

```
cd ../piu-annotate
SIMFILES=/c/Users/jonec/repos/PiuScoresStepfiles/simfiles/ ./run-pipeline-union.sh p2-<name> \
    artifacts/accessible-stepcharts/050726-arroweclipse.json \
    artifacts/accessible-stepcharts/p2-phoenix2-082626.json

python package_snapshot.py p2-<name> <MMDDYY> \
    C:\Users\jonec\repos\PiuScoresStepfiles\snapshots\piucenter-snapshot-<MMDDYY>.zip
```

`SIMFILES` **must** point at this repo. The pipeline's own default is the upstream
`PIU-Simfiles` clone, which is the seed, not the source of truth — pointing at it silently
ships unrepaired stepfiles.

### Ingest the union of charts lists, not one list

A release's coverage is every accessible-stepcharts list ever ingested into its folder, not
the one named on the command line. `p2-082626` shipped 4,574 charts while its own run log says
its ingest matched 4,382 — the folder already held the Phoenix 1 corpus and the Phoenix 2 run
layered onto it. Rebuilding from the P2 list alone matches 4,386 and **silently drops 192
licensed K-pop songs** that exist only in the older list. `run-pipeline-union.sh` exists for
this and prints its coverage after ingest.

**Always diff the new release's chart keys against the previous release before packaging.**
Dropped charts must be zero.

### Timing

~90 minutes on a clean folder, most of it stages 2–3 (limb prediction). A folder that already
holds predictions reuses them and finishes in ~45, which is why the original run looked much
faster than a rebuild.

## Verifying before you ship it

```
cd ../PiuScoresStepfiles
python -X utf8 tools/verify_release.py p2-<name> --old p2-<previous>
```

Every repaired chart must agree three ways: the `.ssc` through the converter, the
`Hold ticks` in the release's chart JSON, and the judged count from its video. Then confirm
the blast radius is only the repairs — every other chart's hold-tick total should be
identical to the previous release — and read the repaired charts back **out of the packaged
zip** rather than trusting the release folder.

## Versioning

`version.txt` is what the importer compares, and the stamp is `MMDDYY`, which must parse as a
decimal and exceed the previous one.

A zip that has **not** been uploaded may be rebuilt in place at the same stamp — that is how
`083126` went from 35 to 42 charts, since a same-day rebuild cannot produce a higher number.
Once a version has been uploaded, a further batch **needs a new stamp**.

## Upload ordering (owner)

The P2 chart-list switch must be live first. The current zip also carries the `stepfiles/`
tree, which is what the step-chart failure map and hold-share features consume, so it is a
single upload covering those features *and* the tick repairs.
