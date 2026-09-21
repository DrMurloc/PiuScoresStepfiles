# Charts lists

Custody copies of the pipeline's own inputs. The annotation pipeline converts only the blocks
a charts list names, and it reads these from `../piu-annotate/artifacts/accessible-stepcharts/`
— a folder that clone's `.gitignore` excludes, so until 2026-09-21 the Phoenix 2 lists existed
on one disk and nowhere else. Copy them back there before a rebuild if they are missing.

| File | What |
|---|---|
| `p2-phoenix2-082626.json` | The Phoenix 2 catalog as of 2026-08-26, 4,616 rows, in the site's public `api/charts` shape. A chart that existed in Phoenix 1 carries its **Phoenix 1** level: the stepfiles hold Phoenix 1 meters and the match is on the meter, so its Phoenix 2 level would drop all 338 re-rated charts without a word. |
| `p2-phoenix2-v101-092126.json` | The six Phoenix 2 v1.01 songs, 59 rows, built from the `/Admin/BulkAddCharts` batch that put them in the catalog. `id` and `imagePath` are null: the matcher reads only the song's name and type and the chart's type and level. |

The third list a rebuild ingests, `050726-arroweclipse.json`, is piucenter's own and is tracked
in the piu-annotate repository. Ingest all three, oldest first — see
[docs/SNAPSHOT.md](../../docs/SNAPSHOT.md).
