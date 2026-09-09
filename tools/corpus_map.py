# The two lookups every analysis tool needs, over BOTH the census and the wider corpus.
#
# The census's own evidence stays where it is and stays immutable: `sources/ssc-map.json`
# (121 charts) and `sources/certification-2026-08-30.json` (113 videos, eye-verified). Work
# beyond the census generates its own pair under work/ - `ssc-map-tail.json` from the catalog
# sweep, `certification-tail.json` from result_reader - and these loaders merge them, census
# first so a census entry always wins.
#
# Tools that must NOT see the merge: catalog_sweep (uses the census key set to exclude the
# 121 from its tail) and rebuild_repairs / audit_repair / triage (census bookkeeping). They
# read the source files directly.
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS_MAP = os.path.join(ROOT, "sources", "ssc-map.json")
CENSUS_CERT = os.path.join(ROOT, "sources", "certification-2026-08-30.json")
TAIL_MAP = os.path.join(ROOT, "work", "ssc-map-tail.json")
TAIL_CERT = os.path.join(ROOT, "work", "certification-tail.json")

def _load(path, default):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding="utf-8"))

def chart_map():
    """chart name -> {chart, key, ssc_rel, ...}."""
    out = {}
    for entry in _load(TAIL_MAP, []):
        out[entry["chart"]] = entry
    for entry in _load(CENSUS_MAP, []):
        out[entry["chart"]] = entry
    return out

def certification():
    """video id -> {vid, status, t, 1p, 2p, charts: {name: {expected, side, verdict}}}."""
    out = {}
    for src in (TAIL_CERT, CENSUS_CERT):
        raw = _load(src, {})
        entries = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
        for vid, entry in entries.items():
            if vid in out:                       # census wins, but keep both videos' charts
                out[vid] = {**entry, **out[vid]}
            else:
                out[vid] = entry
    return out
