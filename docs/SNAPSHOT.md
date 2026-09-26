# Regenerating the annotation snapshot

> **Do not run any of this unless the owner explicitly asks for it.**
>
> A full regeneration is ~90 minutes of unattended pipeline plus a ~32 MB commit, and the
> owner is the one who uploads the result at `/Admin/PiuCenter`. When repairs land, the right
> move is to say *"the snapshot is now N charts behind"* and stop there.
>
> The owner's intended cadence (2026-09-02) is one regeneration at roughly **100 repaired
> charts**, so a snapshot that is dozens of charts behind is the expected state, not a
> problem to fix.

## What the zip is

`snapshots/piucenter-snapshot-<MMDDYY>.zip` is the batch `/Admin/PiuCenter` imports:

```
version.txt                    the release stamp, compared by the importer
page-content/                  chart-table, stepchart-skills, tierlists
<CHART_KEY>.json               one per chart, at the zip root (4,641 currently)
stepfiles/<pack>/<song>/*.ssc  the 664-file corpus the release was generated from
```

Exactly one current zip lives at HEAD; superseded ones are deleted (history keeps them).

## Setting up the clone

The pipeline and every grading tool here run from a piu-annotate clone next to this repo
(the `../piu-annotate` in the commands below), on the `piuscores-windows-port` branch of the
owner's fork. On a machine that has none, from the folder that holds this repo:

```
git clone -c core.autocrlf=false -b piuscores-windows-port https://github.com/DrMurloc/piu-annotate.git
cd piu-annotate
<python 3.12> -m venv .venv
.venv/Scripts/python.exe -m pip install -e . hackerargs==1.1.1 lightgbm==4.7.0 loguru==0.7.3 \
    numpy==2.5.2 pandas==2.2.3 ruptures==1.1.10 scikit-learn==1.9.0 scipy==1.17.1 tqdm==4.70.0
```

`core.autocrlf=false` keeps the checkout byte-for-byte. Git for Windows converts text files to
CRLF by default, and LightGBM cannot read its limb models that way: limb prediction dies on
"Model format error, expect a tree here". The pins are the versions `092326` was built with.
Keep pandas on 2.2.3, upstream's own pin: pandas 3 changed defaults the pipeline has never
been run under.

Then create `artifacts/models/120524/model-config.local.yaml`, which both launchers read: a
copy of `model-config.yaml` beside it with `model.dir` set to that folder's absolute path on
this machine. It is gitignored because that path differs per machine; the models themselves
are in the repository. Copy in the two Phoenix 2 charts lists as well (below). The footage
tools also want `opencv-python-headless` and `yt-dlp` in the same venv, and the pack tools run
on a system Python with `pyzipper` (docs/TOOLS.md).

The clone needs `-b`: the fork's `main` mirrors maxwshen's original, which has none of our
changes, and the grading tools refuse its converter.

## Running it

```
cd ../piu-annotate
SIMFILES=/c/Users/jonec/repos/PiuScoresStepfiles/simfiles/ ./run-pipeline-union.sh p2-<name> \
    artifacts/accessible-stepcharts/050726-arroweclipse.json \
    artifacts/accessible-stepcharts/p2-phoenix2-082626.json \
    artifacts/accessible-stepcharts/p2-phoenix2-v101-092126.json

python package_snapshot.py p2-<name> <MMDDYY> \
    C:\Users\jonec\repos\PiuScoresStepfiles\snapshots\piucenter-snapshot-<MMDDYY>.zip
```

The pipeline outlives the Bash tool's ten-minute cap: launch it in the background with its
output in a log (`> pipeline-<name>.log 2>&1`) and watch the log, not the process list.

`SIMFILES` **must** point at this repo. The pipeline's own default is the upstream
`PIU-Simfiles` clone, which is the seed, not the source of truth — pointing at it silently
ships unrepaired stepfiles.

**Build from the `piuscores-windows-port` branch of the owner's fork**
(https://github.com/DrMurloc/piu-annotate). Since 2026-09-23 its converter
counts hold ticks by the tick lattice (commit `e01246d`; EVIDENCE-RULES.md, "A staggered release
is not a tick"). Upstream piu-annotate still counts them the old way; a snapshot built from it
would carry the old arithmetic's hold ticks for every chart and undo the re-authoring of our
repairs, which are now fitted to the lattice. Stage 4 (`update_chartstruct_holdticks_metadata
--rerun_all True`) re-derives every chart's `Hold ticks` from its `.ssc` with whatever converter
is installed, so a converter change needs no re-ingest: the reuse path below carries it to
every chart, and only charts whose notes changed need their CSVs deleted. `blast_radius.py`
compares hold ticks as well as grids and timing, so a release built across a converter change
moves every chart whose ticks the change moved; read its grid and timing verdicts for the
note-level blast radius, and check the ticks against the converter instead (`verify_zip.py`).

### Ingest the union of charts lists, not one list

A release's coverage is every accessible-stepcharts list ever ingested into its folder, not
the one named on the command line. `p2-082626` shipped 4,574 charts while its own run log says
its ingest matched 4,382 — the folder already held the Phoenix 1 corpus and the Phoenix 2 run
layered onto it. Rebuilding from the P2 list alone matches 4,386 and **silently drops 192
licensed K-pop songs** that exist only in the older list. `run-pipeline-union.sh` exists for
this and prints its coverage after ingest.

**Always diff the new release's chart keys against the previous release before packaging.**
Dropped charts must be zero.

### A content update needs a charts list of its own

The ingest converts only blocks that a charts list names, so new stepfiles in `simfiles/` do
nothing on their own: a song with no list row is skipped, silently, and the release simply
comes out without it. Each game content update therefore adds one small list beside the two
above. `p2-phoenix2-v101-092126.json` is the first — the six Phoenix 2 v1.01 songs, 59 rows —
built from the `/Admin/BulkAddCharts` batch JSON that put those songs in the site's catalog.
Its `id` and `imagePath` are null on purpose: the matcher
(`piu_annotate/formats/arroweclipse.py`) reads only the song's name and type and the chart's
type and level. A chart that existed in Phoenix 1 goes in at its **Phoenix 1** level, because
the stepfiles carry Phoenix 1 meters and the match is on the meter.

The piu-annotate clone gitignores `artifacts/`, so the two Phoenix 2 lists are tracked **here**,
in `sources/charts-lists/`. Copy them into `../piu-annotate/artifacts/accessible-stepcharts/`
if a fresh clone lacks them, and put each new list in both places.

Before the long run, convert the new blocks once with `stepchart_ssc_to_chartstruct` and
check each comes out at one row width. A block with a stray row is accepted by the converter
and by `tick_verify` and then kills limb prediction an hour in (First Love D15, `090326`).

### Rebuilding for a handful of charts

A release folder that already holds predictions reuses them, so a rebuild for a few changed
charts need not re-predict 4,600 limbs. `092226` — four charts on top of `092126` — was built
this way:

1. Copy the previous release's chartstruct CSVs at **both** levels, `<release>/*.csv` and
   `<release>/lgbm-120524/*.csv`, plus the two `__cs_to_manual_json.yaml` files, into the new
   folder. Do not copy `chart-json/` or `page-content/`; stages 8–9 regenerate them.
2. Delete the changed charts' CSVs at both levels. The ingest and limb prediction both skip a
   chart whose output already exists, so a CSV left behind ships the **old** chart with no
   error anywhere — the `090326` crash resumed into exactly that.

`tools/snapshot_reuse.py <previous snapshot commit> <previous release> <new release>` does both
steps from git: it leaves out, at both levels, every chart whose stepfile block differs by any
byte from the block at the previous snapshot's commit (`--dry-run` lists them without copying),
and names any changed block that has no chart in the release. `092326` was prepared with it
(`../piu-annotate/run-092326.sh`); `092226` named its four by hand.
3. Run the union pipeline as usual: the ingest converts only the deleted charts, prediction
   predicts only them, and stages 4–9 run over the whole corpus, which the corpus-relative
   badges need anyway.
4. `blast_radius.py` must then name exactly the changed charts, and the zip-against-zip
   comparison must show limb labels unchanged everywhere else — guaranteed for the reused
   charts, whose predictions are the previous release's own files.

`092226` took 58 minutes this way, against 2 h 52 min for the clean `092126` on the same
machine the same day; `blast_radius` named the four and nothing else, and on the other 4,637
charts the shipped JSON came out identical to `092126`, `stepchart-skills.json` and
`tierlists.json` included. The launcher is `../piu-annotate/run-092226.sh`.

### The blast radius can be checked as soon as stage 1 ends

```
cd ../PiuScoresStepfiles
python -X utf8 tools/blast_radius.py p2-<name> p2-<previous> <previous snapshot commit>
```

The ingest writes one chartstruct CSV per chart into `artifacts/chartstructs/<release>/`
within the first few minutes, and that is all this needs. It compares each chart's step grid,
timing and hold ticks against the previous release and holds the answer against git: every
chart that moved must sit in a stepfile edited since the previous snapshot's commit, and every
edited stepfile must account for a moved or an added chart. `092126`: 17 of 4,582 moved — the
14 repairs landed since `090326` and The Resistance's three fixes — none outside, 59 added,
0 dropped. A surprise here costs five minutes instead of ninety.

### Timing

~90 minutes on a clean folder, most of it stages 2–3 (limb prediction). A folder that already
holds predictions reuses them and finishes in ~45, which is why the original run looked much
faster than a rebuild. Those figures assume memory to spare: `092126` took 2 h 52 min with
under 1 GB free on the 16 GB machine (a browser, Discord and Docker holding the rest). It
paged rather than failed, and the output was unaffected — every untouched chart came out
identical to `090326`.

## Verifying before you ship it

```
cd ../PiuScoresStepfiles
python -X utf8 tools/verify_release.py p2-<name> --old p2-<previous>
python -X utf8 tools/verify_zip.py snapshots/piucenter-snapshot-<MMDDYY>.zip --old <previous zip>
```

Every repaired chart must agree three ways: the `.ssc` through the converter, the
`Hold ticks` in the release's chart JSON, and the judged count from its video. The blast
radius must be only the edits (`blast_radius.py`, above — it can run an hour and a half
earlier). Then `verify_zip` reads the result back **out of the packaged zip** rather than
trusting the release folder: the version stamp, chart-table against the entries, `stepfiles/`
against `simfiles/` byte for byte, every repair's tick total, and nothing dropped against the
previous zip. All three exit non-zero on a problem.

## Versioning

`version.txt` is what the importer compares, and the stamp is `MMDDYY`, which must parse as a
decimal and exceed the previous one.

A zip that has **not** been uploaded may be rebuilt in place at the same stamp — that is how
`083126` went from 35 to 42 charts, since a same-day rebuild cannot produce a higher number.
Once a version has been uploaded, a further batch **needs a new stamp**.

## Upload ordering (owner)

The importer matches this zip's keys against the **Phoenix 2** catalog
(`PiuCenterCrawlSaga.MatchCatalog`, shipped 2026-08-26) — a key carries the chart's level and
levels move between mixes, so a release read against Phoenix 1 mismatches every re-rated
chart and misses P2-only songs outright. The site's P2 chart list must therefore be current
in production. The current zip also carries the `stepfiles/`
tree, which is what the step-chart failure map and hold-share features consume, so it is a
single upload covering those features *and* the tick repairs.
