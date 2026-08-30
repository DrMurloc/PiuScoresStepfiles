# Overrides

The .ssc files being repaired, pack-relative to the PIU-Simfiles checkout so the annotation
pipeline can copy them over the pack input before ingest:

```
overrides/<pack folder>/<song folder>/<file>.ssc
```

**The baseline commit holds these files exactly as they stand in
[rayden-61/PIU-Simfiles](https://github.com/rayden-61/PIU-Simfiles) (branch `stepp1-phoenix`,
commit `cff495bd`)** — the 75 files carrying the 121 charts the precision audit called blatantly
wrong (`sources/ssc-map.json` maps chart → file + chartstruct key; every mapping is verified by
tap-count fingerprint against the audited metrics). Fixes edit these files **in place**, so
`git diff` against the baseline is the review surface for exactly what changed in each chart.

Notes:

- A file carries a whole song's difficulty blocks; only audited blocks get edited — an
  untouched block diffing clean is part of the guarantee.
- Two targets are half-double blocks in the packs (First Love D15, Vook D15 —
  `HALFDOUBLE_ARCADE` keys) though the catalog types them Double.
- Every corrected block must pass the NoteCount gate (implied judged total within 1% of
  `ChartMix.NoteCount`, exact where the footage certifies exact) before the pipeline consumes it.
- These baseline files are the community's work, committed unmodified from the public rayden
  repo purely as a diff base; corrections layered on top are transcribed from
  certified Phoenix-era footage (`sources/certification-2026-08-30.json`).
