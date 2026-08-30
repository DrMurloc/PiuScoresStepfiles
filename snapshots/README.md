# Snapshots

The zip here is the **current** full annotated batch for `/Admin/PiuCenter` upload.

| Current | Generated | Contents | Notes |
|---|---|---|---|
| `piucenter-snapshot-082626.zip` | 2026-08-26 | 4,574 chart JSONs (P1 ∪ P2 corpus) + `page-content/` (chart-table, stepchart-skills, tierlists) + `version.txt` = `082626` | First batch ever to include Phoenix 2 analysis. Built by the local piu-annotate pipeline (`../piu-annotate`, run-pipeline.sh → package_snapshot.py); `*`-restoring key fix applied (57 twin-key issue). ⚠ Upload order per the tracker project: the P2 chart-list switch (Chunk A) must be live first, and a re-upload owes the hold_share / arrows-payload features their data after their PRs deploy. |

Rules: exactly one current zip at HEAD; when a new batch is packaged, add the new zip, update
this table, delete the old one from HEAD (git history keeps it). The version string must parse
as a decimal and exceed the previous (MMDDYY convention: 082626 > 050726).
