# Overrides

Corrected .ssc files we authored, pack-relative to the PIU-Simfiles checkout so the pipeline can
copy them over the pack input before ingest:

```
overrides/<pack folder>/<song folder>/<file>.ssc
```

Match the pack's exact folder and file names (including arcade song IDs) so an override shadows
its original one-to-one. Every file here must state its footage source in `sources/` (census
row) and pass the NoteCount gate before the pipeline consumes it. Currently empty — the 2026-08
repair project (121 charts) fills this.
