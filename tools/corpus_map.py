# The two lookups every analysis tool needs, over BOTH the census and the wider corpus.
#
# The census's own evidence stays where it is and stays immutable: `sources/ssc-map.json`
# (121 charts) and `sources/certification-2026-08-30.json` (113 videos, eye-verified). Work
# beyond the census generates its own pair - `sources/ssc-map-tail.json` from the catalog
# sweep (tail_worklist; committed, it was the only copy), `work/certification-tail.json` from
# result_reader - and these loaders merge them, census first so a census entry always wins.
#
# Tools that must NOT see the merge: catalog_sweep (uses the census key set to exclude the
# 121 from its tail) and rebuild_repairs / audit_repair / triage (census bookkeeping). They
# read the source files directly.
#
# The merges are also exposed as pure functions over already-loaded data (merge_chart_map,
# merge_certification, certified_charts), so tools/corpus_grade.py can build the same
# population from a git revision's copies of these files instead of the working tree's.
#
# Identity overlays (tools/identity.py) are applied LAST, over both merges, once the oracle
# manifest lists them (overlay_chart_map, overlay_certification; IDENTITY_OVERLAYS below).
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS_MAP = os.path.join(ROOT, "sources", "ssc-map.json")
CENSUS_CERT = os.path.join(ROOT, "sources", "certification-2026-08-30.json")
TAIL_MAP = os.path.join(ROOT, "sources", "ssc-map-tail.json")
TAIL_CERT = os.path.join(ROOT, "work", "certification-tail.json")
# The corpus certification took many hours over 1,914 videos and work/ is gitignored, so the
# ledger is also kept in sources/ as evidence. work/ wins when both exist - it is the live one
# result_reader appends to - and the committed copy is what survives a cleaned working tree.
CORPUS_CERT = os.path.join(ROOT, "sources", "certification-corpus-2026-09-10.json")
# Result screens the corpus ledger could not read - the XX screen's 2P column and the Prime
# screen - certified 2026-09-27 by tools/cert_land.py (bucket #12). It holds only what it adds:
# the new read of each video and the charts it newly certifies; the per-chart merge keeps every
# chart the older ledgers carry. It merges after the live tail (which mirrors the corpus ledger and
# would otherwise hand back the old, one-sided read) and before the census.
SKINS_CERT = os.path.join(ROOT, "sources", "certification-skins-2026-09-27.json")
# the two inputs certified_charts() reads besides the map and the ledgers
TAIL_SWEEP = os.path.join(ROOT, "sources", "tail-2026-09-08.json")
CENSUS = os.path.join(ROOT, "sources", "census-final.json")
# Identity overlays (tools/identity.py): corrections to WHICH block a chart is, or to whether a
# video's side shows a chart at all, found by fingerprinting the extraction against every block of
# the song. They never edit the human data above; they are applied LAST, over the merged map and
# ledgers. An overlay is applied only once the oracle manifest lists it (the owner's freeze), so
# the loops' populations and the corpus grade's cannot disagree about it: until corpus_grade reads
# the same file as oracle, applying it here alone would send a repair loop to a block the gate
# grades as another chart's.
IDENTITY_OVERLAYS = ("sources/identity-overlay-2026-09-27.json",)
ORACLE_MANIFEST = os.path.join(ROOT, "sources", "oracle-manifest.json")

def _load(path, default):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding="utf-8"))

def identity_overlays(accepted_only=True, manifest=None):
    """[(relative path, overlay doc), ...] in IDENTITY_OVERLAYS order. With `accepted_only`, only
    the files the oracle manifest lists (`manifest`: an already-loaded manifest, else the working
    tree's)."""
    listed = None
    if accepted_only:
        m = manifest if manifest is not None else _load(ORACLE_MANIFEST, {})
        listed = set(((m or {}).get("oracle") or {}))
    out = []
    for rel in IDENTITY_OVERLAYS:
        if listed is not None and rel not in listed:
            continue
        doc = _load(os.path.join(ROOT, *rel.split("/")), None)
        if doc is not None:
            out.append((rel, doc))
    return out

def overlay_chart_map(smap, overlays):
    """The merged map with every `rekey` row applied: chart -> another block of the SAME file.
    A row applies only while the chart still maps to the row's `from_key` in its `ssc_rel` (a map
    that moved since the overlay was written is left alone), and never when the result would
    leave two charts on one key - a crossed pair re-keys both of its charts or neither. The entry
    keeps what it was: `identity = {from_key, overlay}`."""
    rows = [(rel, r) for rel, doc in overlays for r in (doc or {}).get("rows", []) if r.get("kind") == "rekey"]
    if not rows:
        return smap
    out = dict(smap)
    moved = {}
    for rel, r in rows:
        e = out.get(r.get("chart"))
        if not e or e.get("key") != r.get("from_key") or e.get("ssc_rel") != r.get("ssc_rel") or not r.get("to_key"):
            continue
        out[r["chart"]] = dict(e, key=r["to_key"], identity=dict(from_key=r["from_key"], overlay=rel))
        moved[r["chart"]] = e
    while True:                     # a reverted row can clash with a chart that moved onto its key
        owners = {}
        for name, e in out.items():
            owners.setdefault((e.get("ssc_rel"), e.get("key")), []).append(name)
        back = [n for names in owners.values() if len(names) > 1 for n in names if n in moved and out[n] is not moved[n]]
        if not back:
            return out
        for n in back:
            out[n] = moved[n]

def overlay_certification(cert, overlays):
    """The merged ledgers with every `withdraw` row applied: this video's side does not show this
    chart (another chart's notes, a name the eye-verified census contradicts), so the chart's
    certification on that video is taken out. Nothing else in the entry changes."""
    rows = [r for rel, doc in overlays for r in (doc or {}).get("rows", []) if r.get("kind") == "withdraw"]
    if not rows:
        return cert
    out = dict(cert)
    for r in rows:
        e = out.get(r.get("vid"))
        charts = (e or {}).get("charts") or {}
        c = charts.get(r.get("chart"))
        if not c or (c.get("side") or "1p") != (r.get("side") or "1p"):
            continue
        out[r["vid"]] = dict(e, charts={n: v for n, v in charts.items() if n != r["chart"]})
    return out

def ledger_entries(raw):
    """A certification ledger as loaded (a dict by video, or a list of rows) -> {vid: entry}."""
    raw = raw or {}
    return raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}

def merge_chart_map(tail_map, census_map):
    """chart name -> entry; a census entry replaces a tail entry of the same name."""
    out = {}
    for entry in tail_map or []:
        out[entry["chart"]] = entry
    for entry in census_map or []:
        out[entry["chart"]] = entry
    return out

def chart_map(overlays=None):
    """chart name -> {chart, key, ssc_rel, ...}, the accepted identity overlays applied last
    (`overlays`: a list shaped like identity_overlays()'s to apply instead, [] for none)."""
    return overlay_chart_map(merge_chart_map(_load(TAIL_MAP, []), _load(CENSUS_MAP, [])),
                             identity_overlays() if overlays is None else overlays)

def merge_certification(ledgers):
    """[{vid: entry}, ...] lowest precedence first (corpus, work tail, census) -> {vid: entry}.
    A video in several ledgers keeps the charts of all of them: `charts` is merged per chart,
    and for a chart or a field both ledgers carry, the later ledger wins - census over corpus.
    (Until 2026-09-27 this was a shallow dict merge in which the corpus entry's `charts`
    replaced the census entry's whole, silently dropping the 11 census certifications whose
    videos the corpus ledger also read.)"""
    out = {}
    for entries in ledgers:
        for vid, entry in entries.items():
            if vid in out:
                charts = dict(out[vid].get("charts") or {})
                charts.update(entry.get("charts") or {})
                out[vid] = {**out[vid], **entry, "charts": charts}
            else:
                out[vid] = entry
    return out

def certification(sources_only=False, overlays=None):
    """video id -> {vid, status, t, 1p, 2p, charts: {name: {expected, side, verdict}}}.
    `sources_only` leaves out work/certification-tail.json, so the answer is exactly what the
    committed ledgers say; every other tool wants the live merge. The accepted identity overlays
    are applied last (`overlays` as for chart_map). (The corpus grade builds its population from
    its own list of oracle files, not from here: the skins ledger reaches it only once the owner
    adds the file to corpus_grade's oracle and refreezes the manifest.)"""
    srcs = (CORPUS_CERT, SKINS_CERT, CENSUS_CERT) if sources_only else (CORPUS_CERT, TAIL_CERT, SKINS_CERT, CENSUS_CERT)
    return overlay_certification(merge_certification([ledger_entries(_load(src, {})) for src in srcs]),
                                 identity_overlays() if overlays is None else overlays)

def certified_charts(cert, smap, tail_sweep, census):
    """name -> {chart, key, ssc_rel, vid, side, expected, shape, in_tail} for every chart with a
    certified result screen - the population the repair loops draw (extract_repair.charts()),
    built from already-loaded data: the merged ledgers, the merged map, the sweep
    (sources/tail-2026-09-08.json) and the census rows (sources/census-final.json). When two
    videos certify one chart, the later video in ledger order wins."""
    tail = {r["key"]: r for r in (tail_sweep or {}).get("charts", [])}
    judged = {c["chart"]: int(c["judged"]) for c in census or [] if str(c.get("judged", "")).strip().isdigit()}
    out = {}
    for vid, e in cert.items():
        for name, c in (e.get("charts") or {}).items():
            if c.get("verdict") != "CERTIFIED" or name not in smap:
                continue
            m = smap[name]
            row = tail.get(m["key"])
            expected = c.get("expected") or judged.get(name) or (row and row["implied"] - row["delta"])
            out[name] = dict(chart=name, key=m["key"], ssc_rel=m["ssc_rel"], vid=vid, side=c.get("side") or "1p",
                             expected=expected, shape=row["shape"] if row else "census", in_tail=bool(row))
    return out

def charts(sources_only=False, overlays=None):
    """certified_charts() over the files on disk (identity overlays as for chart_map)."""
    return certified_charts(certification(sources_only, overlays), chart_map(overlays), _load(TAIL_SWEEP, {}),
                            _load(CENSUS, []))
