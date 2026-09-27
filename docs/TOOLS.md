# Tools

All run on the piu-annotate virtualenv with `-X utf8`:

```
C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe -X utf8 tools/<script>.py ...
```

Scratch output lands in `work/` (gitignored). Scripts are operator tools, not a library —
they print what they did and expect a human reading the output.

## Running loops unattended (the rails)

Loops run for days on the owner's own PC, which he also games on. Every loop runs through
these, and the rules they enforce are the loop-bucket rules of 2026-09-26/27: each loop in its
own worktree on a local `loops/<name>` branch, never committing to main, never pushing.

**`supervise.py run <run> --jobs <jobs.jsonl> [--timeout S] [--parallel N] [--grace S] [--threads 1|2] [--min-free-gb G] [--retry nonzero,timeout,launch-error] [--transient-budget S] [--detach] [--accept-pin-change] [--converter-unpinned]`**
**`supervise.py status [<run> ...] [--json]`** / **`stop [<run>] [--clear]`** / **`slots [--max N] [--gaming-max N] [--min-free-gb G]`**
Runs a loop's jobs, one subprocess per job (a job is usually one chart), and records each in
an append-only ledger. A jobs file is JSON lines, one `{"id", "cmd", "cwd"?, "timeout"?,
"slot"?, "env"?, "meta"?}` per job; `"{py}"` as a whole argument becomes this venv's Python with
`-X utf8 -B`, and `{root}`, `{tools}`, `{run}`, `{run_dir}`, `{job}` are substituted. A job may
print `VERDICT: <word>`; the last one is its verdict, otherwise OK or FAIL by exit code. A jobs
file that does not parse is refused with its line number, before any run folder is created; a
byte-order mark and CRLF line ends (what PowerShell 5.1's `Out-File` and pipes write) are fine,
as they are in `slots`' `config.json`.
Everything shared lives in `work/`, which in a loop worktree is a junction to the main
checkout's, so all loops see one copy:

- **The decode-slot pool** (`work/.slots/`): at most 6 jobs at once machine-wide, 2 while
  `Wow.exe` (or `WowClassic.exe`) runs. The game is looked for every 15 s in one Toolhelp32
  process snapshot (the image names `tasklist` prints, in about 30 ms; `tasklist` itself takes
  about 6 s with the few hundred processes this machine runs, and is kept as the fallback). The
  check fails closed: if neither answers, the pool drops to 2 as if the game were running. Slots
  are *counted* under an OS file lock, not numbered, and a slot whose supervisor and child are
  both dead is recovered by PID liveness (with the process creation time checked, so a reused
  PID does not keep it alive) and logged to `work/rails-events.jsonl`. `slots --max`/
  `--gaming-max` can lower the limits (never raise them past 6 and 2), live, for every running
  loop.
- **The limit binds jobs already running.** When it falls below the slots held (the game starts,
  or `slots --max` is lowered), the jobs past it are *frozen*: every process in the job's job
  object is suspended (`NtSuspendProcess`), so a frozen decoder uses no CPU while the owner
  plays, within about 15 s of the game starting. Which jobs freeze is decided machine-wide
  without coordination: every supervisor ranks the live slots by when they were taken and
  freezes its own jobs that rank past the limit, so the oldest keep running and the newest
  freeze. Frozen jobs keep their slots, so nothing new starts; they thaw oldest first as running
  jobs finish or when the game exits, and time spent frozen does not count against their
  timeout (the ledger row records `suspended_s` and `suspends`; `status` marks them FROZEN). A
  slot held in-process through `decode_slot()` cannot be frozen, so it ranks first and the
  supervised jobs freeze around it. A job whose child could not be put in a job object cannot
  be frozen as a whole, so it is killed and queued again instead (verdict PREEMPTED, not a
  finished row). A job a tool deliberately starts outside its job object (breakaway) is not
  frozen.
- **A freeze never strands a lock.** The supervisor freezes a job only while it holds every rails
  mutex itself (the commit lock's, the slot pool's and `rails-events.jsonl`'s, always in that
  order), so a frozen process is never inside one of them, and it cannot take or give up the
  commit lock while the supervisor looks. A job whose processes hold the commit lock (a
  `loopcommit` or `lock-exec` it runs) is not frozen until it lets go: frozen, it would hold every
  loop's commits and gate-failure `revert-run`s for as long as the owner plays. For that long the
  pool runs one job past its limit (the event is `freeze-deferred`; `status` says "past the limit:
  holds the commit lock"), and the job is frozen the moment it releases. If a mutex stays held
  for 5 s, nothing is frozen that round and the next round (1 s later) tries again. A lock or
  mutex wait counts only the time its process was awake (a gap between polls longer than the poll
  plus 2 s is time spent frozen or asleep), so a job frozen while it waited for the commit lock
  keeps waiting when it thaws instead of being refused at once.
- **STOP**: `work/STOP` stops every loop, `work/runs/<run>/STOP` one run (`supervise.py stop
  [<run>]` makes them). No new job starts; jobs frozen for the game are killed at once (they
  could not finish in the grace), and running ones get `--grace` (default 10 minutes) to
  finish, then `taskkill /T /F` kills them; all of them re-run on resume. A run refuses to start
  while a STOP applies to it — clearing one (`stop --clear`) is the owner's decision, never
  automatic.
- **Per-job timeout** (`--timeout`, default 2 h; a job's own `timeout` wins; frozen time does
  not count) kills the whole tree. Each child also runs in its own kill-on-close Windows job
  object, because the venv's `python.exe` is a launcher that starts the real interpreter as its
  child and a tool may start more. The child is created suspended (`CREATE_SUSPENDED`) and
  resumed only once it is in its job object, so the real interpreter can never start outside it
  (assigning after an ordinary launch lost it every time the supervisor was descheduled for a
  few hundred milliseconds, which is exactly when the machine is busy). The job object catches
  what taskkill's parent-PID walk cannot (an orphan whose parent already exited), a child that
  exits while its own children keep
  running has them killed (`orphans_killed` in its ledger row counts those processes), and if
  the supervisor itself dies its children die with it instead of decoding outside any slot.
- **Being a good guest**: children run at BELOW_NORMAL priority with `CREATE_NO_WINDOW` (without
  it a detached supervisor's children pop console windows over the game), OMP/BLAS threads
  capped at `--threads` (default 2), and `tools/childsite/` first on `PYTHONPATH`. Its
  `sitecustomize.py` calls `cv2.setNumThreads(--threads)` the moment a child imports cv2: the
  venv's OpenCV 5.0 (parallel framework "Concurrency") ignores `OMP_NUM_THREADS` and
  `OPENCV_FOR_THREADS_NUM` and starts one worker per core, 20 here. The supervisor asks Windows
  to stay awake (`SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)`) while it runs and
  releases it on exit; the machine still has to be on AC, since it sleeps after 3 minutes on
  battery whatever a process asks. Launches pause, not fail, while C: (or work/'s drive) has
  under 40 GiB free. That floor can be raised (`--min-free-gb`, or `slots --min-free-gb` live for
  every loop) but never lowered: a lower value is raised to 40 and says so.
- **Supervisor errors**: an OSError or subprocess timeout inside the supervisor's own step (a
  file an antivirus holds past the retries, a full disk, a hung `tasklist`) does not end a
  multi-day run. It is logged (`transient-error` in `events.jsonl`, with the traceback), the
  heartbeat says `retrying`, and the step is retried with backoff (5 s doubling to 5 min) until it
  succeeds (`recovered`) or the same trouble has lasted `--transient-budget` seconds (default
  1800). Past that, or on any other exception, the run ends as **crashed** (exit 5): the
  traceback goes to `events.jsonl` and `supervisor.log`, running jobs are killed and recorded
  CRASHED (not finished, so they re-run on resume), and slots are released. A run is only ever
  `finished` when every job has a finished row.
- **Pins**: the converter's source hash (sha256 over every `.py` under `piu_annotate/`, path and
  bytes) and `sources/oracle-manifest.json`'s hash are recorded in the run manifest and
  re-checked before every launch. Drift halts the run (exit 4): running jobs are killed and
  left unfinished, nothing is reverted, and resuming refuses the new pin without
  `--accept-pin-change`, because one run must not mix two converters. When the oracle manifest
  freezes a converter pin (`converter.pin` and `converter.files`, written by
  `corpus_grade.py`), a run also refuses to start unless the converter matches it, computed the
  same way (sha256 over `<path>\t<sha256 with CRLF read as LF>` lines for the files it lists);
  `--converter-unpinned` runs a deliberate candidate converter anyway and records that in the
  run manifest. `pins` shows both.
- **Records** in `work/runs/<run>/`: `manifest.json` (tool HEAD and `tools/` tree hash, the
  argv and options, the converter pin with its git HEAD and the frozen-pin comparison, the
  oracle hash — one entry per attempt), `jobs.jsonl` (the job list, frozen at the first run; a
  run id names one list, so a changed list needs a new id), `ledger.jsonl` (job, attempt, start,
  end, duration, exit code, outcome, verdict, log, frozen time), `events.jsonl`,
  `heartbeat.json` (after every job, every freeze and thaw, and every 30 s), `supervisor.log`,
  `logs/`.
- **Resume**: running the same run id again skips every job whose latest row finished (outcome
  `exit`, `timeout` or `launch-error`; `--retry` names kinds to re-run). A job killed by STOP, a
  halt, a crash or a preemption, or in flight when a supervisor died, has no finished row and
  runs again. One supervisor per run id at a time.
- **`--detach`** relaunches the supervisor with no window in its own process group and returns
  once its first heartbeat appears, or after 2 minutes without one (its output goes to
  `supervisor.log`). It outlives the terminal and the chat session that started it. It does not
  outlive the Claude desktop app for certain: the venv's base interpreter lives in that app's
  virtualized AppData, so a Python started outside the app cannot even find it, and the
  supervisor stays inside the app's process container. A run that dies that way resumes from
  its ledger.
- **`status`** reads every run's heartbeat and ledger: state (`running`, `waiting-slot`,
  `suspended` when every running job is frozen, `paused-disk`, `retrying`, `stopping`,
  `finished`, `stopped`, `halted`, `crashed` with its error, `DEAD` when the heartbeat says
  active but its PID is gone, or `INCOMPLETE` if a heartbeat says finished while jobs lack a
  finished row), done/total, verdict counts, what is running and what is frozen, plus the slot
  pool, the commit lock, the main lock and the global STOP. Only `finished` means done.

Exit codes: 0 finished (every job has a finished row, whatever its verdict), 3 stopped,
4 halted, 5 crashed.

**`supervise.py worktree <name> --base <rev>`** / **`supervise.py worktree-remove <name> [--delete-branch] [--force-branch]`** / **`supervise.py preflight [--videos] [--open-videos]`**
`worktree` creates `../psf-wt/<name>` on a new branch `loops/<name>` from `--base`, junctions
its `work/` and `videos/` to the main checkout's (`mklink /J`), and runs `preflight` there:
the junctions resolve to the main checkout, the converter imports from the clone and counts
ticks by the lattice, every tool imports (scripts without a `__main__` guard, and
`download_videos`, `run_corpus`, `catalog_sweep` and `video_refresh_sql` always, are only
compiled — importing them would run them), plus the branch, the hook setting, free space and
the slot pool; `--videos` checks every `video-map.json` video is present, `--open-videos` also
decodes a frame of each. `worktree-remove` first checks everything `git worktree remove` would
refuse over — uncommitted or untracked files, a locked worktree — and changes nothing if it
finds any. Then it removes each junction by itself (`rmdir` of the link, and it checks the
target's entry count did not change) before `git worktree remove`, and if git still refuses it
re-creates the junctions, so a loop worktree is never left without them (a tool run there would
create a real, unshared `work/`). It refuses if `work/` or `videos/` is a real folder — never
delete a loop worktree any other way, since a tool that recursed through a junction would be
deleting the shared caches.

**`supervise.py lock-exec [--run R] [--timeout S] -- <cmd ...>`** / **`commitlock [--break] [--force]`** / **`mainlock take --note TEXT | release | show`** / **`pins`**
`lock-exec` runs a command holding the commit lock (for a commit step that is not
`loopcommit`); it names its child in the lock, so killing lock-exec alone does not free the lock
while the command still runs, and a lock it cannot take within `--timeout` exits 2 with nothing
run (the timeout counts only time lock-exec was awake, not time a supervisor kept it frozen).
`commitlock` shows the holder; `--break` removes it only if its holder is dead, `--force` even
if not. `mainlock` takes and releases `work/.main.lock`, which whoever merges loop branches
into main holds for the duration and which the pre-push hook below honors; it is
existence-based (no PID), because the merge is done by a person or a session, not one process.
`pins` prints the converter and oracle pins.

Library use, for a tool that decodes in-process: `with supervise.decode_slot(): ...` (a no-op
inside a supervised job, which already holds one — `PSF_SLOT_HELD=1`; such a slot cannot be
frozen, so keep each hold short) and `with supervise.commit_lock(run): ...`.

**`loopcommit.py commit --run <run> -m "<subject>" [--body TEXT | --body-file F] [--lock-timeout S] -- <path> ...`**
**`loopcommit.py revert-run <run> --base <sha> [--reason TEXT] [--dry-run]`** / **`loopcommit.py list-run <run> --base <sha>`**
The only way a loop commits. `commit` takes the commit lock (`work/.commit.lock`, one for every
loop; a dead holder's lock is recovered), stages exactly the declared paths (files or folders,
relative to the repository root) and refuses if the index already holds a staged change outside
them, if a declared path has nothing to commit or is outside the repository (another drive
included), if HEAD is detached, or if the branch is main (or, without `--allow-branch`, anything
outside `loops/*`). Before staging it checks the converter, the loop-bucket rule that the pin
is checked at every commit pass: if the run has a manifest (`work/runs/<run>/manifest.json`),
the converter's source hash must still be the one the run began with, and if
`sources/oracle-manifest.json` freezes a converter pin, the converter must match it (unless the
run was started `--converter-unpinned`); a mismatch refuses the commit and reverts nothing. The
message gets `Loop-Run: <run>` and the Co-Authored-By trailer (the body may not carry either).
After committing it checks git's return code, that HEAD advanced by exactly one commit on the
old HEAD, that the commit touched exactly what was staged and nothing undeclared, and that the
trailer reads back; a failed check undoes that one commit with `reset --soft` and exits 3. It
passes `--cleanup=whitespace` explicitly, so no `commit.cleanup` setting can strip the lines
starting with `#` that stepfile commit bodies carry (`#TICKCOUNTS`). A byte-order mark at the
start of `--body-file` (a file, or `-` for stdin, where PowerShell 5.1 pipes one) is dropped
rather than committed into the message. This replaces the bare,
unchecked `git commit` that `extract_repair.py` and `tick_repair.py` used to run in a checkout
several loops shared.

`revert-run` reverts only the commits after `--base` whose `Loop-Run` trailer names the run,
newest first, stopping at the base and leaving every other commit alone (another run's, the
owner's). Each is reversed from its own binary diff with `git apply --index -R`, which applies
all of it or nothing, and committed with `Loop-Revert: <run>` and `Reverts: <sha>` — not
`Loop-Run`, or a second revert-run would revert the reverts. Already-reverted commits are
skipped, so it is safe to run twice. If a reversal no longer applies because a later commit
rewrote the same lines, it stops there and says so, with the reverts before it committed. A
revert commit that fails its post-commit check is undone with `reset --soft` like any other
(exit 3, the reversal left staged for inspection).

Exit codes: 0 done; 2 refused, nothing committed (every refusal above, and the commit lock not
taken within `--lock-timeout`, default 30 minutes of time it was awake); 3 a post-commit check
failed and the commit was undone; 1 an unexpected error, with a traceback.

**`.githooks/pre-push`** (enable once per clone: `git config core.hooksPath .githooks`)
Refuses every push while `work/.main.lock` exists and prints the lock's note, so nobody
publishes main halfway through a merge of loop branches. It reads nothing else: slots, the
commit lock and running loops never block a push. `.gitattributes` keeps the hook LF-only,
because `core.autocrlf` would otherwise check it out with CRLF endings `sh` cannot run.

**`supervise_selftest.py [--dir <scratch>] [--only name,...] [--list]`**
Proves the rails with toy jobs (python sleeps, no footage): the slot limit with 8 queued jobs
and across two supervisors, the gaming limit, the game starting mid-run (a renamed copy of
`ping.exe` stands in for `Wow.exe`) freezing the four newest of six running jobs with frozen
time kept off their timeout, a lowered `slots --max` freezing jobs and a STOP killing frozen
ones at once, a job holding the commit lock left running past a lowered limit until it lets go
(so the oldest job still commits, where a frozen holder made it `LOCK_REFUSED`), ten freezes of
a job that holds the commit lock's mutex 80% of the time each leaving the mutex free (the old
freeze left it held all ten times), a job frozen past its lock-exec `--timeout` while waiting
still taking the lock after it thaws, every interpreter inside its job object with the
assignment delayed 0.5 s (all four escaped before `CREATE_SUSPENDED`), BOM'd jobs files and slot
config, STOP within one job (run and global), the grace kill, the timeout kill with
grandchildren and orphan reaping, resume after killing a supervisor, a transient supervisor
error retried to completion and a persistent one or a planted bug ending as crashed (never
finished) with no slot leaked, two supervisors serialized by the commit lock, stale-lock and
stale-slot recovery (including a 0-byte lock, and a lock-exec killed without its child), the
disk pause and its 40 GiB floor, a converter-drift halt and the frozen-pin comparison,
`--detach`, loopcommit's refusals (other drive, lock timeout, changed converter), its undo of a
commit or a revert that fails its check and a BOM'd body file or stdin, revert-run, the pre-push
hook against a throwaway
remote, junction unlinking, and worktree-remove's refusals and re-linking in a throwaway
repository. Drills that need jobs to overlap make their toy jobs wait at a barrier until enough
have started, so a slow machine cannot fail a correct pool (a pool that lets too many run is
still caught). Faults are planted by small wrapper scripts that patch the tool in memory, never
by hooks in the tools themselves. Every drill uses its own state folder (`PSF_RAILS_STATE`) and
its own repositories under `--dir` (default `work/rails-selftest/<time>`), so the real pool,
locks and branches are never touched. About six minutes (more on a busy machine); run it after
any change to these tools.

Known limits of the freeze, not fixed: a slot a tool takes in-process through `decode_slot()`
cannot be frozen, so a tool holding two or more of them when the game starts keeps the machine
past the gaming limit until it lets them go. And jobs in one worktree share its git index: a job
frozen during the milliseconds a `git status` in it holds the worktree's `index.lock` would make
every git write there (a `loopcommit` included) fail until it thaws.

## Checking upstream for new steps

**`resistance_packs.py list | changelog <pack> | recent <pack> --since <date> | get <pack> <entry> --out <dir>`**
**The one tool here that runs on the SYSTEM python, not the venv** — the packs are AES zips and
`pyzipper` is installed only there. Looks inside The Resistance's MediaFire songpacks without
downloading them: the direct links honour HTTP Range, so it reads a pack's directory and then
only the entries asked for (the 1 GB PHOENIX pack gives up one stepfile for under 1 MB).
`list` shows the hub with upload dates — a changed date is the signal; `changelog` prints the
pack's `WHAT'S NEW AND CHANGELOG.txt`; `recent` lists entries by modified date, which catches
edits the changelog was written before (entry times are the packer's local clock); `get`
extracts `.ssc` entries to a scratch folder. `changelog` and `get` need the pack password The
Resistance publish with each release, from `--password` or `RESISTANCE_PACK_PASSWORD` — it is
theirs to hand out, so it is not in this repo. What it fetches is evidence, never a commit:
their credits ask that the packs not be redistributed.

The order that found the v1.01.0 update (2026-09-21): `git fetch` in `../PIU-Simfiles` for new
songs the public mirror has taken → `list` and `changelog` for what the mirror does not carry
(fixes to charts already published) → `pack_census.py` for everything the changelog does not
say → `get` the fixed files → `apply_upstream_fix.py` (under Authoring) → `tick_verify --file`.

**`pack_census.py fetch`** (system python) **/ `pack_census.py compare [--out <json>]`** (venv python)
The whole-corpus answer to "what does their current file say that ours does not": `fetch` pulls,
out of every pack on the hub, only the `.ssc` entries whose file name is one of ours (840 entries
for the 664 files, ~50 MB, resumable, into `work/packs/`); `compare` reads every official block
on both sides as the set of its judged events plus the six tags the converter reads, pairs blocks
identical-first and then by events, meter and overlap (so a re-rate or an old-mix label still
meets its own chart), converts every differing pair with the pipeline's converter, and judges
each against the catalog — the 2026-09-08 sweep's reference, a census chart's judged count, the
certification ledger, or `sources/p1-note-counts-2026-07-04.json` (the Phoenix 1 catalog count
per chart, exported from the owner's compiled Phoenix 2 chart list so the census does not need
the database up). Verdicts: theirs exact / theirs closer / both exact / same distance / ours
closer / ours exact. First run: `sources/resistance-diff-2026-09-21.json` — 519 of 664 files
identical, 4,393 of 4,689 blocks; of the 2,207 tail charts their current files fix **three**
(DESTRUCIMATE S19, Asterios -ReEntry- S4, Conflict D25, each re-checked with `tick_verify` on
the pack copy) and come closer on 22; ours is exact where theirs is off on 119, our 111 repairs
among them. Newer is not better: their current file drifted off an exact count on eight charts
(Maria D21 1000 → 769, Club Night D12 605 → 665, Scorpion King D16 810 → 845). Compare blocks by
their notes, never by their labels — a label-keyed diff hides exactly the blocks whose labels
changed, and a half-double block is compared by cell, since a `{…}` cell is one column.

## Caches, reports and commits: the plumbing every loop stands on

The loops run for days, several at once, over caches that cost hours to rebuild (the 1,413
sprite passes alone are about seven hours of decoding). Four small modules keep a killed process,
a changed parameter or a refused commit from turning into a silent wrong answer.

**`atomicio.py`** (library) **/ `atomicio.py drill <scratch dir> [--rounds N] [--modes naive,atomic,pickle,stream]`**
Every cache, report and ledger write goes through here. `open(path, "w")` truncates a file before
a byte of the new content exists, so a process killed in between leaves a 0-byte or half-written
file under the real name - two 0-byte receptor field caches, left by a probe that patched
`json.dump` after the file was already open, broke Another Truth D19 and Emperor S16 in every
tool. `write_json` / `write_text` / `write_bytes` / `write_pickle` / `write_npz` / `atomic_open`
write a temp file in the same directory, fsync it and `os.replace` it over the target, retrying
with backoff while Windows refuses the rename because a reader holds the file; they write exactly
the bytes the call they replaced wrote (same encoding, same text-mode CRLF), so a report is
byte-identical to one written before. `StreamWriter` is for scans too long to buffer: it writes
`<name>.partial`, renames it into place only when the stream completes, then writes
`<name>.done.json` (line count, size, sha256, and whatever the producer records about how it was
made). The loaders - `load_json`, `load_pickle`, `load_npz`, `read_jsonl` - return None for a
0-byte, truncated or unloadable file exactly as for a missing one, and say so on stderr, so the
caller rebuilds it; a stream with a sidecar must match it, a legacy stream without one is
trusted unless a line fails to parse. `forbid_writes(allow)` puts a read-only phase under an
audit hook that refuses every write, rename and delete outside `allow` (paths compared after
resolving junctions) - which patching `json.dump` cannot do, since by then the file is already
truncated. `drill` kills writers mid-write (TerminateProcess) and checks the target is the old
file or the new one and never a part of either, against a naive `open(..., "w")` writer that must
be caught leaving partial files for the drill to mean anything, plus a contended phase with a
reader holding the target open. First run (2026-09-27, 40 kills a mode): the naive writer left
a partial file 39 times (the 40th kill fell between two writes); the atomic JSON, pickle and
stream writers never did - every kill left the previous complete file, the new one, or, before
any write had completed, none; and of 100 writes under a busy reader, 90 needed a retried rename
and none of 13,773 reads saw a bad file.

**`cachekey.py`** (library)
Cache keys that carry everything the cached thing depends on. The sprite-pass name never held the
detection floor the pass was cut at (`FLOORS[0]` times the contrast scale), the strip watched or
the sprite box; the receptor-template name never held the box, the band's rows or the lanes
between the two ends; neither said which code built it. Each cache now states its full parameter
set plus a code stamp - a hash of the compute functions' syntax trees, docstrings and comments
removed, never of the caching wrapper around them - and `keyed()` gives it its old name while
every parameter equals its value when the existing files were built (the `*_LEGACY` stamps in the
tools, and the frozen derivations here: `legacy_sprite_box`, `legacy_rows`, `legacy_lanes`), and
`<old name minus suffix>.k<digest of the parameters><suffix>` the moment one differs. So today's
caches all still hit (proven on 2026-09-27: four charts re-read with zero frames decoded and
results byte-identical to main's) and a changed floor, box, band, fit or rule gets a file of its
own. New files carry a `<file>.meta.json` sidecar spelling the parameters out. Keyed this way:
sprite passes (`note_extract.pass_path`), receptor templates (`sprites.anchors_path`), field fits
(`receptors.field_path`, and `field_key()` which the two caches built on the lanes carry),
geometry fits (whose old name never said how many columns - a different count now gets its own
file instead of the other one's lanes) and counter scans (`combo_reader.scan_path`, by atlas
digest, reading code and range). The receptor scan npz is keyed by its name alone on purpose: it
has two producers whose output its readers use interchangeably; its sidecar says which. A change
that moves a stamp re-keys that cache and every file of it is rebuilt on next use -
`selftest.py` says so when it happens; if that is meant, update the stamp table in the selftest,
never a `*_LEGACY` constant, which names the code that built the files already on disk.

**`gitcommit.py`** (library)
`commit_exactly(root, paths, message)` for every commit pass (extract_repair, tick_repair,
batch_repair, lattice_reauthor). They used to run `git add` and a bare `git commit` with no return
code read, and record whatever `rev-parse HEAD` said as the chart's commit - so a refused commit
went unnoticed, and a bare commit took along anything anyone had staged. It commits with a
pathspec (only those paths), then requires git's return code 0, HEAD advanced by exactly one
commit onto the HEAD it started from, and that commit touching exactly the declared paths;
anything else raises `CommitError` and the pass stops there, loudly, after writing back the
commits that did land so a re-run does not repeat them.

**`fsck.py [--json <report.json>] [--quarantine] [--only spritepass,receptor,combo,reports]`**
What is wrong with the caches under `work/` before a loop trips over it. Report-only by default,
and it cannot be otherwise: it runs under `atomicio.forbid_writes`, allowing only the `--json`
report. It loads every sprite pass, receptor fit, template and scan npz, counter scan and loop
report, and names each broken one: 0 bytes, unloadable, incomplete (missing what its readers
need), disagreeing with its sidecar, an orphaned temp file or `.partial` stream, a SHIP report row
whose candidate is gone, and a counter scan that stops more than 3 s before its video ends - which
it settles by decoding forward from two seconds before the scan's last frame: if the video goes
on, the scan was cut short (`truncated scan`, rescan it); if the video stops decoding there too,
it is `short footage` and a rescan would give the same file. Stale key formats and the superseded
plain/`.sym` field fits are reported and left alone - nothing reads them, and the old fits are
kept on purpose. `--quarantine` moves the broken ones (with their sidecars) into
`work/quarantine/fsck-<time>/`, under their paths in `work/`, with a manifest of why; it never
deletes, and a quarantined cache is simply missing, so the next reader rebuilds it. First run
(2026-09-27): no 0-byte or unloadable file anywhere (the two 0-byte field caches were already
gone), 1 truncated scan (`-1hzF02vOFc.R`, ends at 44 s of a 185 s video that decodes on), 3 short
because the footage stops decoding (`0T1_HBRTVLc` L and R at 76 s of 125 s declared,
`1rcd4MaRTDg.C` at 62 s of 128 s), and stale formats: 49 sprite passes, 70 template files and 73
superseded field fits.

## The extraction loop

**`extract_repair.py survey [--shard i/n] [--only "<chart>"] [--shapes a,b] [--cache] [--redo] [--ssc <alt.ssc> --expected N] [--out <dir>]`**
**`extract_repair.py commit [--dry-run] [--only "<chart>"] [--out <dir>]`**
The note-level successor to `batch_repair.py`, for the two thousand charts the counter cannot
price. It reads each certified chart off its footage (`note_extract`), aligns the extraction to
the file's own notes — an anchor, then a straight line for the video's clock — matches note for
note in seconds, and classifies every difference: tap→hold, a moved release, an added hold or
tap, a hold read as a tap, a note the reader did not find. Only the first four are ever applied,
and each has to earn it. A hold needs a rail at least 0.15 s long that read as held on 55% of
its frames (real holds measured 0.65–2.3 s at 0.59–0.69; the false ones — a drill read as one
rail, bright art under a receptor — ≤ 0.10 s at ≤ 0.52) and may not span notes the file has in
that column. An addition needs the receptor to have flashed for it, a streak at least 0.6 of
the chart's typical one, no file note within 35 ms in its column (the same note seen twice) and
no missed file note within 60 ms in any column (a drill note read in the neighbouring lane);
additions are capped at 2% of the chart. A chart the extraction recalls or precisions below 93%
against its file is parked unread. The candidate is written under `work/extract-loop/`,
converted, and ships only at the certified count exactly. `commit` is a separate serial pass
over every shard's report that re-runs `tick_verify` in place before each commit, one commit
per chart carrying every edit. `note_extract` now hands back its receptor flashes in `meta`
and each rail's length and occupancy on the note, which is what these rules read.

Two things learned after the first run (2026-09-23). A candidate is a whole-file copy made
from the file as it stood when the survey ran, so when two charts of one song file both ship,
the second candidate still carries the first block unrepaired and copying it in undoes the
first fix — Higgledy Piggledy S15's commit put S16 back to its +8 state minutes after S16 had
shipped, and the in-place check, which reads only the block being committed, said MATCH.
`commit` now refuses a candidate whose file has changed outside its own block, and says to
re-run the survey for that chart (`--redo --only`); `--note "<text>"` appends a paragraph to
the commit message for exactly such a re-landing. And the note grid is edited by *panel*, not
by character: a StepF2 cell such as `{2|n|1|0}` is one panel to `edit_notes.cells/get/put`,
which the applier and `load_block`'s width now go through, so the 49 files that write those
cells are read and edited like any other (their fake-flagged cells and `F` letters are also
handed to the matcher as *drawn but never judged*, so an extracted note on one is that fake,
not an addition — `--redo-reason stepf2` re-runs the charts a report parked for that reason).
`--exact-first` grades the file before reading any footage and records an exact chart as EXACT
unread — for a re-grade (the second corpus run, after the converter changed), not for a census
of the reader.

The report, the candidates and the proofs are written atomically (`atomicio`), so a survey killed
mid-write leaves its resume report whole, and each commit goes through `gitcommit.commit_exactly`:
a commit git refuses, or one that touches anything but the chart's file, stops the pass with the
reason. `--out <dir>` puts the report and candidates under `<dir>` instead of `work/` (on both
verbs) - for a proof, a comparison or a re-run of charts whose report and candidates belong to an
earlier run and must not be written over; keep `<dir>` inside the repo (`work/...`), since
reports record candidates by their path from the repo root.

Proven before it ran (2026-09-22): the five charts the counter loop made exact came back with
no edit at all (before the rules they drew 4, 3, 6 and 8 stray additions), and six manual
repairs re-derived from their seed files found the same holds in the same columns — Another
Truth D18 all nine, Slam D22 640 of 642 events identical — parking only because their counts
close on tick bursts this loop does not author, which is the counter loop's job.
`--ssc`/`--expected` run the survey against another file for exactly that kind of proof.
`--cache` keeps the sprite passes (a few MB a chart) so a rule change re-scores without
decoding; the first corpus run kept them. `--redo-verdict FAIL` re-runs only those charts
from a shard's report; `--tail-tol` and `--precision-bar` override the two thresholds for an
experiment, and two were run from cache after the first corpus pass, both negative: a 25 ms
release threshold (against the 60 ms default) shipped 2 of 48 near misses but moved 33 of
them *further* from the count — the rail's last frame is noise at that scale, and one
candidate ran to +1.3 million ticks inside a BPM gimmick before the gate refused it — and an
85% precision bar (against 93%) shipped 0 of 24 precision-limited parks. Both defaults stay.

## The tick loop

**`tick_repair.py survey [--shard i/n] [--only "<chart>"] [--limit N] [--near N] [--census <file>] [--redo] [--redo-verdict V,V] [--redo-reason <text>] [--no-scan] [--out <dir>]`**
**`tick_repair.py commit [--dry-run] [--only "<chart>"] [--census <file>] [--out <dir>]`**
Where the extraction loop found the screen showing the file's notes and holds and the count
still off, this prices every hold region of the file from the combo counter and authors only
what the counter measured. Its worklist is the extraction loop's census (`--census`, else the
newest `sources/extract-loop-*.json`): the parks whose extraction cleared the bar, nearest the
count first (`--near`, default 10), full-combo plays before plays with breaks; a chart whose
extraction candidate applied edits is priced and authored on that candidate, so one commit
carries both.

How a region is read. The counter is a running count of judged events, so on a play that
counted every event, a read minus the file's own count up to the same instant is the file's
cumulative error there — and it changes only inside a region whose ticks the file has wrong.
The video clock is the extraction loop's (the file's notes matched on screen; `note_extract`
reloads from its cache in seconds), the display lag between a judgement and the counter's step
is measured on the chart's own isolated taps, and each region is read on the stretch before it
(back to the previous region, at most 0.6 s) and the stretch after it: the reads whose cut
falls there, clear of every judged event by 35 ms, must agree on that constant (two frames,
60% of them), or the stretch is not read. The change between the two readings is the region's
own error, its ticks plus that change its price; two regions with nothing readable between
them are priced together as one cluster. On a full-combo play the counter never falls, so only
the longest non-decreasing chain of confident reads is believed — a dropped hundred, a 9 read
as 5, a rail's leading 1 fall off it (ASDF D10: 135, 136, 137, 138, *135*, 140 — the fifth is
139) — and every reading is held to the file's count within what the chart's whole deficit
could explain. Two readings a full combo fixes without a frame: before the first hold the
counter shows the file's first taps (it is blank below 4), and after the last event it rests
at maxcombo, which *is* the judged count — a region priced off that end is priced by closure,
and the record says so. On a play with breaks the reads are cut into runs at each reset and
both readings of a region must come from one run.

What it authors, in this order and nothing else: a region priced N where the file derives M
gets the single integer `#TICKCOUNTS` rate over its own span under which the converter derives
N (found by bisection against the real converter; the file's rate returns at the region's end,
entries inside the span go); where no rate reaches N and the region ends on one release row,
the release moves by one of the block's own rows, or the half-row between, toward N — only if
the rail the extraction saw ends on that side of the file's release. Every priced cluster is
also derived by `tick_model.py`'s independent implementation of the tick lattice; since the
converter counts by the lattice itself (2026-09-23) the two agree, and a cluster where the
model matches the counter and the converter does not would be tagged and never authored
around. A window of more than four regions or four seconds priced as one is not authored: its
total is measured, its interior is not. Two adjacent clusters priced opposite ways share a
misread plateau and both are refused, and a gap read from both ends must give the same
constant.

**`tick_model.py test`** / **`tick_model.py census [--shard i/n]`** / **`tick_model.py summary`**
The hold-tick count as the game judges it, against the converter's old arithmetic. `census`
runs every certified chart through the real converter under the old arithmetic and the lattice
with its variants (points inside FAKES judged or not, a head under TICKCOUNTS 0 judged or not)
and through an independent implementation of the lattice on the converter's own rows, and
counts the exact ones, what each breaks that the old arithmetic had exact, what it fixes, and
where the converter and the model disagree region by region (`work/tick-model-census.*.json`;
`summary` totals the shards). `test` checks every cluster the tick loop's reports have priced
against the counter. The numbers, and the semantics they settled, are in EVIDENCE-RULES.md.

**`lattice_reauthor.py survey`** / **`lattice_reauthor.py apply [--only "<chart>"] [--dry-run]`**
Our repairs, re-graded under the lattice. `survey` finds every certified chart (the corpus
ledger and `census-final.json`) whose block our commits changed since the seed (`a23cee5`) and
grades the block and its untouched upstream version under both arithmetics
(`work/lattice-reauthor.json`). `apply` puts each repair the lattice breaks back on its own
evidence, one commit per chart: a block whose upstream version is exact under the lattice is
reverted to it; a repair that only edited notes and no longer closes is reverted for the loops
to survey again; a repair that authored its `#TICKCOUNTS` keeps every region's recorded count
(read back under the old arithmetic) and only the regions the lattice counts differently get a
new rate over their own span — the full rate range scanned, then two rates split on a
sixteenth-beat grid between the pair whose counts bracket the target — with the rate after
each region left as it was. A region recorded below its own heads is raised to them and the
difference comes off the closure it was priced from (the region carrying half the chart's hold
events, else one event at a time from the largest regions within three seconds). It counts
candidate schedules with the converter's own post-loop step (`context=` hands it the segments,
which do not depend on TICKCOUNTS), and writes a block only when the full converter re-derives
every region and the total, and `tick_verify` agrees in place. Its commits are checked
(`gitcommit.commit_exactly`) and its report and apply log are written atomically.

The gate: the priced clusters' differences must sum to the file's whole deficit (so every edit
is a measured number and the unread regions are, in total, right as they stand); on a play
with GOODs, BADs or MISSes every region must have been read, because a GOOD neither breaks nor
increments the counter and an unread region could hide the tick it took; and after authoring
the converter must derive the price on every edited cluster, the file's own ticks on every
other, and the certified count in total. Everything else parks with the full region table —
cut times, reads, the file's count at each, taps between — in `work/tick-loop-report[.i].json`.
The counter scan (`work/combo/<vid>.<band>.jsonl`, `combo_reader`) is made on demand at about
1.3× real time a video unless `--no-scan`; a scan that is there but broken (0 bytes, a last line
a killed scan cut short, a file its `.done.json` does not describe) is made again as if missing.
`commit` mirrors the extraction loop's: candidate in, `tick_verify` in place, the
outside-the-block guard, one checked commit per chart naming every reading. `--out`, the atomic
report and candidate writes and the checked commits are the extraction loop's too; the scratch
`.ssc` the converter reads while a rate is searched is now private to the process
(`tmp-<key>.<pid>.ssc`) and removed after use, where two surveys of one chart used to share one.

## The corpus grade (the gate every loop commits through)

**`corpus_grade.py grade [--rev <commit>] [--oracle-rev <commit>] [--out <path>|-]`**
**`corpus_grade.py gate --base <rev> [--head <rev>] [--oracle-pass] [--declared N] [--json <path>]`**
**`corpus_grade.py freeze [--repin]`** / **`conflicts [--write]`** / **`selfcheck`**
(all take `--workers N` (default 6), `--no-cache`, `--cache-dir <dir>`, `--unpinned`,
`--stall-timeout S` (default 600); run with `-X utf8 -B`, or it refuses)
Grades every certified chart — the population the repair loops draw, `corpus_map.charts()` over
the committed ledgers — through the converter, taps plus hold ticks against the certified count,
and ratchets the result. **`--rev` takes only the blocks from the commit** (its `.ssc` files, read
as git blobs, never the working tree); **the oracle — who is certified, and at what count — is
still read from the working tree unless `--oracle-rev` names a commit too.** Without `--rev` the
working tree's blocks are graded. The JSON is deterministic (sorted, no timings; timings go to
stderr), so two grades of one tree are byte-identical: 1,490 charts, plus the import commit's
blocks for the tiers, in about 40–60 s cold on 6 workers (depending on what else the shared box
is running) and about 4–7 s when every block is in the conversion cache (`work/corpus-grade-cache/`,
keyed by the converter pin, the conversion code's own source, the file's content with CRLF read
as LF, and the block tag; a 0-byte or torn entry is a miss and is rebuilt; writes are tmp +
`os.replace`). Workers run at BelowNormal priority.

Only a count is cached. An error row is converted again on every run, and a second time in a
fresh worker before it is believed; if the two answers differ the run refuses. (The converter
catches its own exceptions while it builds the beat map, so a MemoryError there looks like an
ordinary failure. A cached one would stay a wrong "not exact" until someone deleted it.) A
MemoryError or OSError that reaches the grade refuses the run with exit 2, and nothing is cached
for it. So does a pool that delivers no result for `--stall-timeout` seconds: a killed or hung
worker loses its block without a word, and the pool would otherwise wait for ever.

Two tiers. **PROTECTED**: exact when the import commit `a23cee5`'s blocks are graded under the
current oracle (the corpus as upstream published it; the tool checks that `simfiles/` first
appears in that commit), or promoted by a `sources/protected-promotions.jsonl` row whose
`block_sha` is the chart's current block — `{"chart", "key", "block_sha", "audit": "FLAT",
"covered": true, "audit_version", "run"}`, written by `trace_audit` when the interior passed a
covered audit, read here. **PROVISIONAL**: every other exact chart. A `sources/demotions.jsonl`
row takes the import protection away (a promotion of a block no demotion names gives it back).
Flags ride on each row: `oracle_conflict`, `owner_revisit`, `quarantine`, `demoted`.

The **oracle** is every file that decides who is certified and at what count — the census and
corpus certification ledgers, `ssc-map.json` and `ssc-map-tail.json`, `census-final.json`, the
sweep, the Phoenix 1 catalog counts, `video-map.json` — plus the three policy files the gate
enforces (`oracle-conflict.json`, `owner-revisit.json`, `quarantine.json`).
`sources/oracle-manifest.json` holds each one's sha256 (CRLF read as LF, so a CRLF checkout and
an LF blob agree) and the **converter pin**: the sha256 over every `piu_annotate` module the
conversion actually loads (`__init__`, `utils`, `formats/__init__`, `formats/notelines`,
`formats/sscfile`, `formats/ssc_to_chartstruct` — taken from `sys.modules`, not a hand list; a
worker that loads a module outside it after converting stops the grade), which catches a
converter that drifts while keeping the lattice flag (the converter is the piu-annotate clone
unless `PIU_ANNOTATE_ROOT` names another checkout, e.g. an exported copy of `e01246d`; the pin
decides either way). `grade` and `gate` refuse when the working
tree's oracle or the installed converter differs from the manifest. `freeze` rewrites the
manifest in an oracle commit, never together with stepfile edits, and moves the converter pin
only with `--repin`, as a commit of its own. Only committed ledgers are oracle:
`work/certification-tail.json` is the live file `result_reader` appends to, and `grade` says on
stderr when it holds videos the committed ledger does not.

The **gate** grades `--base` and `--head` (default: the working tree), each under its own tree's
oracle, prints every transition — LOST, GAINED, EDITED-EXACT (a block or its file header
changed and it stayed exact), EDITED-OFF, EXPECTED-CHANGED, UNPROTECTED and PROMOTED (the
PROTECTED tier changed and nothing else did: a demotion or promotion row, named with its reason
or run, or the import grade under a new oracle), ENTERED/LEFT the population — and
exits 1 when: a chart leaves exact without a `sources/demotions.jsonl` row naming the chart and
its `block_sha` before the change, with a `reason` and `evidence` (a quarantined chart's row
also needs `owner`, where he said yes); a PROTECTED chart leaves exact at all, or its block or
file header changes while it stays exact (unless a promotion row names the new block) —
protection is judged at the base, so demoting a PROTECTED chart is a commit of its own before
the change that breaks it; the oracle hash or the converter pin differs between base and head
(unless `--oracle-pass`, for commits that change only the oracle — and then any file under
`simfiles/` that differs between base and head fails, certified or not, in the population or
not, each named with the certified charts it holds; two commits compare blob ids, and the working
tree is compared by content with CRLF read as LF); an owner-revisit chart's block or file header no longer hashes to what
`owner-revisit.json` records; a chart in the ORACLE_CONFLICT set becomes exact (halt for review
instead of taking the credit); `demotions.jsonl` or `protected-promotions.jsonl` lost or rewrote
a line (both are append-only); `--declared N` is given and the net change in exact charts is not
N. It exits 2 when it cannot judge (drift at the head, a revision that does not resolve, a
conversion the machine failed or a worker that died, a converter that answered twice
differently). It writes nothing but `--json`, and never reads a grade file to decide anything —
both sides are re-graded from blobs.

The ledgers and lists it enforces. **`sources/demotions.jsonl`** (append-only, empty until the
first demotion): one JSON object per line, `{"chart": <census chart name>, "block_sha": <the
block being demoted, before the change>, "reason": <why the exact total is not to be trusted>,
"evidence": <what showed it: a trace audit, a video, a commit>, "owner": <where he said yes;
required for a quarantined chart>, "date", "commit"}` — the only way the exact set may shrink.
**`sources/quarantine.json`**: Houseplan S17 (3d17dae), Wedding Crashers S10 (c40c089) and
Imagination S12 (2c374be) — exact in total, the counter shows them wrong inside: a review list
for the owner, excluded from every benchmark, never reverted without his yes (each entry records
the quarantined `block_sha`). **`sources/owner-revisit.json`**: each entry's `block_sha` and
`header_sha` are the accepted state.

`conflicts` builds `sources/oracle-conflict.json` from the data: a video that certifies two or
more charts on one side (a result screen shows one total per side); a certified count that is
not the chart's Phoenix 1 catalog count (`p1-note-counts`, matched by song, type and level)
while the file already converts to that catalog count; a block whose converter inputs
(STEPSTYPE, NOTES, BPMS, STOPS, DELAYS, WARPS, FAKES, TICKCOUNTS, header inherited) are
identical to another block's in its file — HIDDEN / INFOBAR twins the grade cannot tell apart.
`selfcheck` confirms `guards` splits every file into the blocks the converter sees, with the
same tags.

Drilled on 2026-09-27 with faults planted in a scratch clone (never in a branch's files), 25
cases, each caught and named or passed as intended: `#TICKCOUNTS` doubled on a PROTECTED chart
(fail) and on a PROVISIONAL one (fail; passes with a demotion row naming its block, fails with a
row naming another block); a quarantined chart demoted without and with `owner`; one tap moved
in Slam D24's block and a comment added to its file header (owner-revisit fails; a comment line
inside a block breaks the converter for the whole file, which the gate also catches as every
sibling leaving exact); a certification value changed (refused while the manifest is stale; an
ORACLE failure once refrozen; with `--oracle-pass` the chart leaves exact without a demotion);
an owner-revisit entry removed and refrozen; a repaired sibling reverted to its import block (the
extract_repair whole-file-copy failure); an uncertified sibling edited (passes, no false alarm);
a header `#OFFSET` and an in-block `#BPMS` change on a PROTECTED chart that keep every total;
a compensating edit (one tap to another column, totals kept); Pump me Amadeus S16 padded to its
wrong certified 871 (ORACLE_CONFLICT); a gain declared as 0 and as 1; an oracle pass carrying a
stepfile edit; a line removed from `demotions.jsonl`; a converter copy that drifts but keeps the
lattice flag (`PIU_ANNOTATE_ROOT`, refused). A 0-byte and a torn cache entry are rebuilt and the
grade stays byte-identical.

The first review found a hole. `--oracle-pass` looked only at charts certified on both sides, so
an oracle commit could certify a chart, edit that chart's block, and take the credit. It was
fixed and drilled the same day, with 18 more cases in a fresh scratch clone, and the 24 cases
above were run again (all as intended). The oracle-pass cases: an untouched CRLF checkout
passes. The reviewer's case fails whether committed or in the working tree: one note flipped in
the uncertified Switronic SHORT CUT S17 block, and a ledger row certifying it at the new count.
So do an uncertified block edited, a file added and an uncertified file removed. A policy-file
change on its own passes with `--oracle-pass` and fails without it. The tier cases: a
demotion-only commit prints UNPROTECTED with its reason, and a promotion row prints PROMOTED with
its run. The conversion cases used a hooked copy of the converter, pinned in the clone. With no
fault set it grades exactly as the real converter does. A MemoryError or OSError that reaches
the grade is refused, and nothing is cached. A worker that kills itself is refused after
`--stall-timeout`. A failure the converter returns as `(None, message)` keeps its message, and
is converted again rather than cached. A swallowed MemoryError that does not repeat is refused.

**`guards.py`** (library)
The shared definitions the loops and the gate import. `block_sha(ssc_path, block_id)` is the
contract between them: sha256 of one `#NOTEDATA` block — from the line that starts with
`#NOTEDATA:` up to the next such line or EOF, decoded as UTF-8 (`errors="replace"`), CRLF and CR
made LF, trailing whitespace at the end of the block stripped (`str.rstrip()`, so the newline
and blank lines before the next block go too). `block_id` is an index or the converter's tag
(`"S18_ARCADE"`, the first block carrying it, header tags inherited). `header_sha` hashes the
text before the first block, which every block inherits. `is_owner_revisit(chart_or_key)` is the
skip for `sources/owner-revisit.json`'s charts: a loop that gets True does not survey, re-fix or
flag the chart. `tag_of(key)` is `extract_repair.block_tag`'s rule.

## Reading footage

**`combo_reader.py --scan <vid> side=<L|R|C> [atlas=tools/atlas-combo-p2]`**
OCRs the in-game combo counter frame by frame into `work/combo/<vid>.<band>.jsonl` as
`[time, value, confidence]`. The scan is written as `<file>.partial` and renamed into place only
when it completes, beside `<file>.done.json`: its line and byte counts and sha256, the atlas's
digest, the reading code's stamp, and whether it ran to the end of the video or the decoder
stopped early - a scan killed part-way is never left under the real name looking like a short
video. The file's name is its key (`scan_path`, see `cachekey.py`): today's atlases and code keep
the plain name, and a glyph added to an atlas or a change to how a frame is read gives new scans a
keyed name of their own. Finds the COMBO *label* first and hangs the digit window off it,
which is what stops a BGA's own numbers being read as combo (Tales of Pumpnia's RPG damage
popups). A digit-sized unknown glyph voids the read rather than truncating it; only
sub-digit-width edge fragments are dropped. Unknown glyphs are dumped to `work/combo-unknown/`
for atlas work.

`atlas=` picks the counter's font. Phoenix 2 redrew it - solid italics where Phoenix 1 has a
hollow outline - and the original atlas reads none of it: 0 of 14 held-out frames of L (PIU
Edit) D27, where `tools/atlas-combo-p2` reads 13 exactly and abstains on the fourteenth. A scan
with another font's atlas writes `work/combo/<vid>.<band>.<atlas>.jsonl` beside the default one.
`--bootstrap <vid> atlas=<dir> <t>=<digits> ...` harvests glyphs from frames whose value was read
by eye - never label a frame you have not looked at - and carries on numbering from what the
atlas already holds. A frame is skipped unless it splits into exactly as many glyphs as its
value has digits, which is what a note scrolling past the digits usually prevents.

**`combo_check.py <combo.jsonl> <notes.json> [<notes.json> ...] [--pass <sprite pass .pkl>] [--span 0] [--list]`**
Checks an extraction against the combo counter on autoplay footage, one quiet stretch at a time.
Between two instants where the counter reads the same value, the rows the extraction found (a
jump is ONE judgement, so rows, not arrows) must equal how far the counter moved. The stretches
come from the counter alone, so every extraction of a video is judged on the same ones and two
correlation floors can be compared. A stretch that holds something is reported, not judged - its
count includes hold ticks - and `--pass` decides which stretches those are from the pass's lane
rails, which are the same for every floor, rather than from each extraction's own holds.
`--span 0` uses every quiet stretch rather than ones at least two seconds long. With a single
notes file, or `--list`, it prints every stretch and marks the ones to look at (`LOOK +n`). A
notes file is the list `note_extract` returns, written out with `json.dump`.

**`cell_reader.py --calibrate|--bootstrap|--scan <vid> <side> ...`**
Fixed-cell OCR for videos whose digit font the shared atlas cannot read (Imagination S18) or
whose counter sits mid-field under the notes (2P doubles, Love is a Danger Zone pt. 2). Cells
are fixed boxes hung off the COMBO label; `--calibrate` fits the geometry from frames,
`--bootstrap` learns a per-video atlas from eye-read frames (`<t>=<digits>`, `?` for an
occluded cell), `--scan` writes the usual `work/combo/<vid>.<side>.jsonl` - deliberately the
name combo_reader's scan has, since it replaces a scan the shared atlas could not read - sealed
the same way, with `tool: cell_reader` in its `.done.json`. Atlases live in
`tools/atlas-cell/<vid>/`. Never label a frame you have not looked at.

**`receptor_reader.py <vid> <t0> <t1> [key] [offset]`** — note extraction
Reads the *receptors* instead of the counter: a judgement flashes its column's receptor
white for a few frames, and a hold's rail is a saturated *and bright* bar in the lane just
beneath it (the BGA that fools a saturation-only test is saturated but dark). Per column it
reports judged-event onsets (prominent peaks of the receptor's white level over its rolling
floor, so a 16th-note drill re-peaks per hit) and hold spans (lane occupancy ≥ 0.3s). With a
key it matches onsets against the file's taps and reports the best offset and the
file-only / video-only events per column. Geometry — receptor band and column centres — is
fitted once per video from the temporal median of the band (the receptors are the only
static thing there) by `receptors.geometry` and cached in `work/receptor/<vid>.<band>.geometry.json`
(this tool used to carry its own copy of that fit, writing the same file); the centres come from
the field's extent (outermost strong profile peaks are the outer borders; `ncols` equal
receptors fill the span), because every comb fit tried locked onto a harmonic of the
receptors' inner ridges. `RR_COLS=5` for singles; `RR_THRESH` (flash, default 40; 60–70 on
bright BGA) and `RR_OCC` (rail occupancy, 0.45) tune it. Known limit: through a drill the
white level clips and hits merge, so it under-counts drills — the taps are already in the
file; what this tool is for is the holds.

**`receptors.py`** (library) — the reader's functions (`geometry`, `scan`, `onsets`, `rails`,
`chartstruct`, `match_offset`, `snap_beat`), used by the two drivers below. Its caches (the
geometry and field fits, the scan npz) are written atomically and read back through `atomicio`: a
0-byte or unreadable one is refitted in place rather than handed to every tool. The fits are
keyed by their parameters and code (`field_path`, `field_key`, see `cachekey.py`); the compute is
in `_fit_geometry` / `_fit_field`, which is what the stamp covers.

**`extract_holds.py "<chart>" [offset]`**
The per-chart extraction survey: scans the whole certified video, derives the offset from the
flashes, lists every rail inside the chart with its head flash (the head *is* a judged event,
so its flash is the exact head time), converts to snapped beats, says whether the head lands
on a file tap, shows what the counter accrued across the rail, and prints the `add-hold`
commands. Then a grid line: file events without a flash and flashes without a file event.
Layout comes from the certification (full-screen → band C; split → L/R by side; 5 or 10
columns by chart type). Prints only.

**`rail_ticks.py "<chart>" <offset> [--lag 0.2]`**
Prices every rail **locally**, with no run structure: the combo read just before the head
and the read just after the tail bracket the hold, and `after − before − taps inside` is its
ticks - *every* file tap between the two reads is subtracted, not just the taps inside the
rail's span, and the head's own row stays in (the converter counts a hold's head as its first
tick, whether or not the old file wrote a tap there). Works wherever the counter
is readable at both ends; a drop anywhere between the two reads is reported as a reset,
never priced - a reset just *before* the head hides when the bomb outruns it (Naissance
S20 read 110 before a MISS and 457 after the finale); a missing bracket read writes the two frames to `work/frames/rails/<vid>/` for eye
reading. Dr. M D18's nine rails and Mr. Larpus D18's four all priced this way — including the
"reset" that was a leading 1 (151 for 51) and the "+143" that was a covered hundred.

**`apply_rails.py "<chart>" <offset> <rails.json> [--burst ...]`**
Turns a rail list (`[{"col", "head", "tail", "ticks"|null}]`, video seconds) into the file:
the head goes on the file's own row for that column when one sits within 120ms (the old
files wrote hold heads as taps), else on the snapped beat; the tail on the snapped beat;
then `regen_chartstruct` and `finale_ticks` with `--pin` for every rail whose ticks were
read and closure for the `null` ones. One run per chart.

**`excess_scan.py "<chart>" <offset> [--conf 0.8] [--min 2]`**
Where does the counter outrun the file's taps? Between consecutive persisting reads inside
one run, the counter's rise minus the file's taps in that span is accrual; clusters are
holds the file lacks. Structure-free, and the way to see that a chart's whole deficit sits
on one finale (Pump me Amadeus D15's +86 = its 86 owed). Its numbers are still read-noisy -
dropped hundreds show as +100 and a covered counter as +1xx - so it points, it does not price.

**`phantom_scan.py "<chart>" <offset>|--fit [--until <video s>] [--conf 0.85] [--tail]`**
The phantom hunt for a (near-)perfect play — taps the file has that the game never judges.
Raw high-confidence reads only: at each read the taps judged ≥150ms earlier must already be
in the counter, so `n_lo − counter` is 0 through a clean stretch and steps to +1 for good at
the phantom. **Its `--fit` is orientation only** — the offset that zeroes the most reads is
the *late* alias, because being one tap interval late absorbs a phantom (Slam S5 read clean
at 10.40 and +1 from the first readable value at the frame-verified 10.30). Take the offset
from the frames and read the step; then `edit_notes.py remove`. `--until` restricts the fit
to the reads before the first hold, where the counter must equal the tap count exactly.

**`finale_ticks.py "<chart>" [--pin b0-b1=N ...] [--burst <beat> [--pre <rate>]]`**
After the edit and the regen: prices every hold region in the file by closure
(`judged − taps`, split by length across the unpinned regions), authors, verifies. `--pin`
keeps an observed count on a region (Another Truth D18's mid-chart pairs read 6/5/5/30 off
a perfect-play counter) and sends the remainder to the rest. `--burst` rewrites the tuner
region's schedule as a tail burst — `--pre` per beat up to the burst beat (default 2), then a
rate tuned against the converter to land exactly — for finales the counter shows firing in
the last stretch (Slam D22 009 → 463 in 0.2s; FA2 SC D19 577 ticks in one frame; My Way
D16 47 steady then 101 at once, `--burst 193 --pre 16`). **Not on a gimmick beat map**: Conflict
S22 runs ~19 beats a second through its ending, and a burst there came out of the converter at
729 ticks against 204 owed; that chart ships flat, priced by closure alone.

**`auto_anchors.py "<chart>" <offset>`**
The grid verdict without hand forensics: reads → `continuity_repair` (dropped hundreds, a
rail's leading 1, and the atlas reading 9 as 5) → runs split at drops that persist *and*
restart near zero → peaks scaled to close on P+G (a final run resting at maxcombo is exact)
→ anchors → `align_schedule` + `grid_screen`. It refuses, and prints its runs, when the read
peaks exceed P+G or there are more runs than resets — that is the FORENSICS signal, and
frames are the answer.

**`regen_chartstruct.py "<ssc>" <BLOCK> <key>`**
After a note-grid edit, rewrites the chart's chartstruct CSV from the `.ssc` in this tree
(keeping the pipeline's extra columns; the first run saves `<key>.csv.pre-edit`). Every
tool here reads that CSV and the pipeline only rewrites it on a full ingest, so an added hold
is invisible until this runs.

**`result_reader.py`**
Certifies a video from its result screen — the `P/G/Gd/B/M` and `maxcombo` that make a video
usable as evidence. Output is the certification ledger in `sources/`.

**`run_drift.py "<chart>" <offset> [--conf 0.85] [--gap 2.0]`**
The tap-grid check that needs **no run structure**. Inside one rising stretch of the counter
the delta must equal the file's tap rows over the same span, so a file carrying taps the game
never judges drifts persistently NEGATIVE (past its miss count) and a file missing a hold
drifts positive. Use it wherever `grid_screen`'s curve cannot be built — many resets, or a
video where the rails cross the counter. Reads below 4 are dropped (the counter is blank
there, so a sub-4 read is the reader inventing a number from an empty box, and one of those
opens a bogus run that double-counts the climb before it); a drop only starts a new run if
the next read continues from it. A lone `+99`/`+100` run is a dropped hundred, not evidence.

## Deciding whether a chart is fixable

**`grid_screen.py "<chart>" <vid> <band> <offset>`**
Re-tick versus re-step. Reports the slack profile (`cum − taps`) by 15-second zone and a
verdict. **Takes the offset as an argument on purpose** — sweeping for the offset that
minimises drift always finds one, and the answer becomes self-fulfilling. Calibrated against
eight charts of known outcome. See [EVIDENCE-RULES.md](EVIDENCE-RULES.md) for why the
invariant is one-sided.

**`triage.py "<chart>" ...`**
Rough-assembles a curve and screens it, for sorting a pile before spending forensics on it.
Three verdicts: OK, MISMATCH, and **FORENSICS** — the last means the naive peaks already
exceed `P + G`, so a counted "reset" is a misread and the curve built on it is fiction.
Deliberately crude: good enough to sort, never good enough to author from.

## Building the curve

**`curve_tools.py`** (library)
`continuity_repair` restores dropped hundreds and decides resets with lookahead; `lis_chain`
keeps the longest monotone chain of a segment; `build_anchors(pts, offsets, total)` turns raw
reads plus a descending list of `(boundary_time, cumulative_offset)` run boundaries into the
anchors file. The run boundaries are the operator's call, made from frames — the tools only
assemble what has been decided.

**`fit2.py <vid> <band> <key>`**
Two-sided offset fit, scored only inside tap-only windows where the observed combo delta must
equal the tap count exactly. Reports the window count — under ~15 windows, distrust it.

**`align_schedule.py <vid> <key> <judged> <band> [offset]`**
Aligns the curve to the chart's schedule; reports violation score, observed-versus-expected
tick coverage, and a per-anchor accrual map flagging whether the file has a hold there.
Reading its output honestly is covered in [EVIDENCE-RULES.md](EVIDENCE-RULES.md).

**`hold_observe.py <vid> "<key>" <offset> <judged> <band> [pins.json]`**
Per-hold tick brackets from the anchors, splitting merged spans at gap midpoints. Emits
`work/combo/<vid>.holds.json` with pinned holds, unpinned holds and the closure remainder.

**`storm_fill.py <vid> <band> <w0> <w1> [runOffset] [conf]`**
For windows ticking faster than persistence-based anchoring can follow: keeps the maximal
isotonic subset of single-frame reads and emits synthetic pins.

**`solve_holds.py`** — per-hold events as a bounded linear system over pin intervals.

## Authoring

**`make_targets.py <vid> <out.json>`**
Turns observations into targets: pinned holds keep their observed counts, the remainder
distributes over unpinned holds by beat weight, largest becomes the tuner. **Its beat-weight
distribution is a guess and must be checked** — see step 5 of
[REPAIR-WORKFLOW.md](REPAIR-WORKFLOW.md).

**`window_targets.py <vid> <band> <key> <offset> <judged> <out.json> [windowSec] [clusterGap] [t0-t1=N ...] [spread=length]`**
For drill charts — hundreds of tenth-second holds the curve cannot bracket one at a time.
Clusters the file's holds, tiles each cluster into ~2s windows (never cutting a hold), reads
each window's ticks straight off the curve, pins any window the frames settled (`t0-t1=N`),
and spreads the closure remainder over the unpinned windows by what the curve saw there or,
with `spread=length`, by hold length (the right choice when a player dropped holds: a window
that read zero because of a BAD still owes the ticks the chart judges there).

**`windows_to_holds.py <key> <windows.json> <out.json>`**
Splits window targets into converter regions — overlapping and tail-sharing holds merged
first, globally — because `author_ticks` converges on regions and cycles on multi-hold
windows. A window's ticks go to the regions inside it by overlap length.

**`wall_targets.py <vid> <band> <key> <offset> <judged> <out.json> [windowSec]`**
Alternative for wall-class charts: tiles observed hold spans into fixed windows read straight
off the anchor curve, so the interior is observation-driven rather than profile-driven. Only
usable where the curve actually has reads through the span.

**`author_ticks.py "<ssc>" <BLOCK> <targets.json> <judged>`**
Patches the block's `#TICKCOUNTS` and iterates against the real converter until
`taps + ticks == judged`, with a brute-force two-segment finisher for the rounding plateaus
the incremental loop cannot cross. Restores the file if it cannot converge — but **`git
checkout` the `.ssc` after any failure**, since a failed run can leave a partial schedule.
Aggregates converter segments into target regions by **maximum overlap**; the older midpoint
rule silently starved regions on drill charts and made the loop diverge.

**Read its closing report.** A converged *total* says nothing about the interior: the tuner
absorbs whatever the other regions could not reach, and on Bad Apple D20 a "CONVERGED" run
had parked 182 ticks on one 0.2s hold. The tool now prints authored-versus-target per region
and the count of regions over and under; a tuner more than a handful off its target means the
targets were unreachable as given, not that the file is right. Every region under two beats is
nudged to exact (the old "within ±1" slack pooled 41 ticks onto one hold on Desaparecer), a
region that flips sign every step is locked at its closer grid value, and the finisher starts
from the best state seen rather than the last.

**`edit_notes.py add-hold|move-release <ssc> <BLOCK> <col> <startBeat> <endBeat>`**
**`edit_notes.py remove <ssc> <BLOCK> <col> <beat>`**
**Its `<col>` is a FILE column, not a chartstruct column** — see the padding rule in
EVIDENCE-RULES. It now refuses a column past the row's width; before that guard, python
slicing appended instead of failing and First Love D15 shipped a hold on a seventh panel.
`apply_rails` takes chartstruct columns and does the mapping itself.
Surgical note-grid edits, for content the file is genuinely missing rather than mis-ticking.
`add-hold` clears the column's taps inside the span (the old files wrote holds as repeated
taps and the converter refuses a hold laid over them). `remove` deletes a phantom — one note
of a row; a jump row needs one call per column, because a jump is one judged event and half
of it is still one. First uses: Slam S5's intro jump, Set me up S10's two extra drill notes.

**`apply_upstream_fix.py --ours <ssc> --new <upstream_fixed.ssc> --block <DESC> [--old <upstream_before.ssc>] [--tags TICKCOUNTS,...] [--apply]`**
Transplants a fix the upstream transcribers made to one block into our copy of the file, and
nothing else: only the note rows that differ are rewritten, in place, and only the differing
entries of the tags named. The other blocks, our own repairs, the line endings and the tags the
public mirror adds all stay byte for byte, so `git diff` shows the fix alone. It reports without
`--apply`. With `--old` it refuses when our block is no longer the upstream block the fix was
made to - a repair of ours would otherwise be overwritten by a file that never had it. It
refuses a measure whose row count changes, because then which row moved is a judgement and
belongs to `edit_notes.py`. Finish with `tick_verify --file`. First uses: The Resistance's
v1.01.0 fixes to Fracture Temporelle D26, Digitalis D24 and 404 (New Era) S16 - fixes that
reach their MediaFire songpack and never the public mirror (see `simfiles/README.md`).
`--whole-block` takes their entire block instead, for a fix that re-encodes the timing map and
so has no row-for-row form: their notes and every timing, scroll and metadata tag come across,
while the tags that name the chart — DESCRIPTION, METER, DIFFICULTY, CHARTNAME — stay ours, so
the chart keeps its key and the ingest still matches it on the meter (`--new-block` names their
label where a re-rate moved it: our Conflict D25 is their D24), as do the mirror's
CHARTSTYLE/LASTSECONDHINT and any tag only our block carries. After writing, it re-reads both
files with the pipeline's parser and restores our bytes unless the block's judged events and
six converter tags equal theirs. That mode runs on the venv. First uses: DESTRUCIMATE S19,
Asterios -ReEntry- S4 and Conflict D25, the three the census found exact upstream.

**`author_new.py <vid> --title "<title>" --level <n> --cols 10 [--ticks 4] [--combo <combo.jsonl>] [--cache]`**
Writes a stepfile for a chart the repo has no file for - a song Andamiro has just released - from
its video alone, into `work/authored-new/`. It re-times every note at the local scroll speed
(lanes under the judgement text lose half of each streak and read late), fits ONE BPM from how
well the rows align with a twelfth-of-a-beat lattice and refuses a chart whose two halves want
different tempos, takes out a video clock that drifts against the song (the median distance from
that lattice over ten seconds at a time), chooses the lattice by how many notes it holds within
the fitting tolerance and reports a finer one that would put notes between its lines, puts beat
0 where the rows land on the coarsest subdivisions, writes one empty
measure before the first row - a choice, since nothing in the footage says which beat starts a
measure - and sets `#OFFSET` so beat 0 falls at its video time. With `--combo`, a jump of the
counter in the video's last frames is read as the rest of a hold the video faded out on, and the
last hold is lengthened by it. It ends by running `tick_verify` against the counter's final value
and printing the difference; it does not tune `#TICKCOUNTS`. **piu-annotate's converter ignores
`#OFFSET`**: a converted row's time counts from beat 0, so add the offset back before laying a
converted file against the counter.

## Verifying

**`tick_verify.py "<chart>" [expected]`**
The acceptance gate. Runs piu-annotate's converter over the block in our tree and reports
`taps + ticks = implied`. A repair is not real until this matches.

**`verify_release.py <release> [--old <release>]`**
Checks a packaged release actually carries the repairs: the `.ssc` through the converter, the
`Hold ticks` in the release's chart JSON, and the judged count must all agree.

**`snapshot_reuse.py <previous snapshot commit> <previous release> <new release> [--dry-run]`**
Prepares a release folder for SNAPSHOT.md's reuse path: copies the previous release's
chartstruct CSVs at both levels and the manual-annotation yamls, and leaves out every chart
whose stepfile block differs from the previous snapshot's commit, so ingest and limb prediction
redo exactly those. It matches a CSV to its block by the stepfile path and the DESCRIPTION and
SONGTYPE in its metadata, reading a tag a block does not carry from the song header as the
chartstruct does, and names any changed block with no chart in the release.

**`verify_zip.py <snapshot.zip> [--old <previous.zip>] [--ticks]`**
Checks the PACKAGED zip, the thing that gets uploaded. `--ticks` also re-derives every chart's
`Hold ticks` from the stepfile the zip banks with the installed (lattice) converter and requires
the chart json to match segment by segment — the check that a release built across a converter
change carries the new arithmetic on every chart, not only on the repairs (several minutes). `verify_release` reads the release
folder; packaging then rewrites keys (the `*` restoration), walks `simfiles/` a second time and
stamps a version, and nothing looked at the result. It checks the version stamp against the
file name and the previous zip, that chart-table names exactly the chart entries, that
`stepfiles/` is `simfiles/` byte for byte with nothing missing, that every chart json's
`ssc_file` is in the zip (the import joins on that path), that every entry name is the key its
own metadata rebuilds, and that every repair in `repairs.json` ships its tick total **read out
of the zip**. With `--old`: no chart dropped, and the added ones by song. Proven by pointing it
at `090326` after the tree had moved on: it named the 6 missing files, the 17 changed stepfiles
and the 9 repairs that zip predates, and passed every structural check.

**`blast_radius.py <new_release> <old_release> <previous snapshot commit>`**
Which charts a new release actually changed, answerable minutes into the pipeline — it reads
only the chartstruct CSVs the ingest stage writes. Compares every shared chart's step grid,
timing and hold ticks, then holds that against `git diff <commit> HEAD -- simfiles`: a chart
that moved with no stepfile edit behind it is the pipeline or the corpus drifting, and an
edited stepfile that moved nothing is a repair the release did not pick up (both the ingest
and limb prediction skip a chart whose output already exists, so a reused folder serves the
stale one). `verify_release` cannot see either: it checks the charts in `repairs.json`, not
the other four and a half thousand. Exits non-zero on a dropped chart, a stray or a silent
edit.

**`video_freshness.py <walk.tsv> <catalog.txt> <videos.txt> <out.json>`**
Which charts point at footage older than what exists. Reads a channel walk (the census's cache
under `%USERPROFILE%\.piu-score-tracker\video-backfill\walks\`) and matches every titled
upload to a chart, because Nevsister stamps the mix on each one. Three traps it handles, all of
which produced wrong matches first: the rerate note lives in PARENTHESES and is full of chart
codes (`1949 D22 (pre D21 -> D22)`), `8 6 - FULL SONG -` normalises to the same name as the
arcade `8 6` unless the song type is matched too, and the code in a Phoenix title is the
PHOENIX level, so a chart is looked up at the level it holds in that video's own mix. Reports
`upgrade` only where the banked video is a known-era upload OLDER than the best available -
never where the banked era is simply unknown.

**`video_refresh_sql.py <freshness.json> <catalog.txt> <out.sql> <needs.json> [--oembed ...] [--pilot ...]`**
Writes the SQL the owner runs, and the list he records. Every UPDATE is guarded on the video it
replaces, so the script is idempotent and cannot overwrite a hand-fix. Side comes from the new
video (Left/Right for a split-screen singles pair, NULL when the chart has it alone), and where
only one half of a split screen moves, the partner's Side is corrected in the same script.
`--oembed` drops any target that no longer resolves; `--pilot` folds the repair loop's own
"the footage is an older revision" charts into the recording list.

**`selftest.py`** - the parts that need no footage
Every case is a bug that shipped once: the pair that shared one bracket and got counted twice,
the rerate note in parentheses read as chart codes, the full song that took the arcade song's
video, the sweep that took the first offset instead of the best. Runs in a few seconds, needs
nothing but a temp directory and git. Run it after touching a regex, a parser or a matching rule.
The plumbing has cases too: atomic writes byte-identical to the plain ones, a 0-byte or cut-short
cache loading as missing, a stream sealed by its sidecar, cache keys keeping their old names
until a parameter moves, a checked commit carrying only its own file, a read-only phase that
cannot open a file for writing - and a table of the code stamps every cache is keyed by, which
fails when a change would re-key a cache without saying so.

**`golden.py [--only "<chart>"] [--record]`** - the charts whose answer we know
Re-derives seventeen charts from the footage and fails if the analysis reaches a different
conclusion: the offset it fits, the drift it measures, the rails it prices, the verdict the
gate reaches, and (for repaired ones) the count the converter still gets. `rebuild_repairs`
proves the FILES are still right; this proves we can still DERIVE them, which is a different
failure - a repair can sit correct in the tree while a change to the reader quietly stops being
able to reach it, and the next batch parks everything.

Nine of the seventeen are charts that must **NOT** ship, one per park cause, because a gate
that loosens is the failure that actually costs something. A repaired chart stops at "already
exact", so its pricing is probed separately rather than left unguarded. `--record` rewrites the
expectations - only do that when a change is *meant* to move them, and read the diff first.

**`run_corpus.py <video-map.json> [--skip-download] [--no-commit]`**
The whole pipeline as one command: fetch the footage, certify it, survey every chart, author
what the gate allows, commit each repair, and print what it produced. Every stage skips what is
already done, so it can be killed and restarted and picks up where it stopped. It makes no
judgement calls of its own - the gate in `batch_repair` decides what ships and everything it
refuses is written down with a reason. This is what a batch should be run through; the
individual tools are for looking into a chart afterwards.

**`batch_repair.py <video-map.json> --survey|--author [--commit] [--limit N] [--only "<chart>"]`**
The closed loop. `--survey` walks a batch and classifies every chart without touching anything;
`--author` does the edits the survey called for, re-verifies each with the real converter, and
reverts any that does not land. `--commit` commits them one chart at a time, titled like the
census repairs, each through `gitcommit.commit_exactly` (a refused commit stops the batch). Both
write `work/<tag>-report.json` atomically, one row per chart with its measurements and a
machine-readable reason. A counter scan that is there but broken is scanned again.

The gate ships a chart only when four things hold: the footage is **certified** (a result
screen's judgement sum equals the catalog count), the **grid is clean** (`run_drift` is not
negative past the play's own misses - one-sided, because positive drift IS the missing holds
and a dropped hundred reads as +100), the events are **evidenced** (one hold region takes the
remainder by closure, or every rail is priced from its own bracketing counter reads and the
priced total equals what the chart owes), and the converter agrees **exactly**. Multi-region
pinning is deliberately not automated: a mis-mapped pin is a wrong distribution that still
verifies. Everything else parks - including a chart whose footage agrees with the file rather
than the catalog, which is an older revision needing newer footage (see EVIDENCE-RULES).

**`corpus_map.py`** (library)
`chart_map()` and `certification()` merge the census's own evidence (`sources/ssc-map.json`,
`sources/certification-2026-08-30.json`, both immutable) with whatever a batch beyond the
census has generated under `work/`. Every analysis tool reads through it, so a chart outside
the 121 looks up exactly like one inside it. `catalog_sweep` and `rebuild_repairs` deliberately
do NOT use it - they need the census key set to stay the census key set. `charts()` is the
certified population (the same rows as `extract_repair.charts()`), and the merges are also
pure functions over loaded data (`merge_chart_map`, `merge_certification`, `certified_charts`)
so `corpus_grade` can build the population from a commit's copies of the files;
`certification(sources_only=True)` leaves out the live `work/certification-tail.json`. A video
in more than one ledger keeps every ledger's charts: `charts` merges per chart, and where two
ledgers carry the same chart or field the census wins. Until 2026-09-27 the merge was a shallow
dict merge in which the corpus ledger's `charts` replaced the census entry's whole, silently
dropping the 11 eye-verified census certifications whose videos the corpus certification had
also read (Set me up S10, Chase Me S20, Final Audition S18, ...); restoring them took the
certified population from 1,479 to 1,490 and the exact count from 738 to 749.

**`tail_worklist.py <tail.json> [--shape ...] [--min-pct N] [--max-pct N] [--limit N] [--out-tag T]`**
Turns rows of the catalog sweep into the two inputs a batch needs: `sources/ssc-map-tail.json`
(always the whole sweep - it is a lookup, and a later batch must not erase an earlier one's
entries; committed since 2026-09-27, when the gitignored `work/` copy was the only one, and part
of the corpus grade's oracle, so rewriting it is an oracle commit followed by
`corpus_grade.py freeze`) and `work/<tag>-video-map.json` (just this batch, in `video-map.json`'s shape, so
`download_videos --map` and `result_reader --map` take it unchanged).

**`catalog_sweep.py <chart-json folder> <catalog.txt> <videos.txt> <out.json> [--pct 5]`**
Sizes what is wrong *beyond* the census: every corpus block through the converter against the
catalog's Phoenix note count (two sqlcmd dumps, the queries are in its header), matched
through the pack's own mix - a Rebirth-pack S13 block is Phoenix's S17, so a key's level is
never compared with Phoenix directly. Writes the tail past the threshold with each chart's
shape (over-ticked / under-ticked / single-region / hold-less / duplicate block) and its banked
video. `--pct 0` lists every chart that disagrees at all (a one-note gap on a 2,400-note
chart rounds to 0.0%, so the threshold is skipped rather than applied); `--pct 5` keeps only
the large gaps. `sources/tail-2026-09-08.json` is its output; nothing in it is authored here.

**`rebuild_repairs.py`**
Regenerates `sources/repairs.json` from the tree — any census chart whose file now converts to
exactly its judged count is a repaired one. Never hand-edit the manifest; run this.

**`audit_repair.py` [chart ...]**
Re-audits a shipped repair without trusting how it was made: re-derives the offset with the
two-sided fitter, screens the grid at that offset, and compares the file's per-hold ticks
against what the combo curve says happened there. The total is already guaranteed by
`tick_verify`, so this checks the *interior*.

Its comparator refuses to answer more often than it answers, on purpose. A hold is only
compared when the curve genuinely resolves it: at least three distinct anchor values spanning
60% of the hold, and a tick rate under ~30/s. Above that rate no combo value persists long
enough to anchor, so comparing reports the reader's blindness rather than the file's accuracy
— before those guards were added it invented a 485-tick "disagreement" against a 386/s bomb
and a *negative* observed count on a hold the curve had barely read.

The consequence is worth knowing: on the 13 charts audited in 2026-09 only 0–3 holds per
chart were verifiable at all. **These repairs' totals are proven and their interiors are
largely not**, which is a standing argument for note extraction rather than more curve work.
