# Shared guards for the loops: what a block's content hash is, and which charts the owner has
# put out of bounds. A library, no command line; every loop and the corpus grade import it so
# there is exactly one definition of each.
#
# BLOCK HASH (the contract between corpus_grade, trace_audit and the repair loops):
#   block_sha = sha256 hex of one chart's #NOTEDATA block, where the block is the text from the
#   line that starts with "#NOTEDATA:" up to (not including) the next line that starts with
#   "#NOTEDATA:", or EOF. The file is decoded as UTF-8 (errors="replace"), CRLF and lone CR are
#   normalized to LF before the lines are found, and trailing whitespace at the end of the block
#   is stripped (Python str.rstrip(): the final line's trailing blanks, and with them the newline
#   and any blank lines that separate the block from the next one). The hash is over the UTF-8
#   bytes of what remains. A block therefore hashes the same whether it is read from a CRLF
#   working tree or an LF git blob, and whether it is the last block of the file or not.
#
#   header_sha is the same over the text BEFORE the first #NOTEDATA line: the song header, whose
#   #OFFSET / #BPMS / #TICKCOUNTS every block inherits unless it sets its own. A header edit moves
#   every chart of the file while leaving every block_sha alone, which is why it gets a hash too.
#
# A block is named either by its index (0 = the first #NOTEDATA block) or by its converter tag,
# "DESCRIPTION_SONGTYPE" ("S18_ARCADE", "S17 INFOBAR TITLE_ARCADE"), resolved the way
# piu-annotate's StepchartSSC.from_song_ssc_file resolves it: the song header's tags are
# inherited, and when two blocks carry the same tag the FIRST one is the chart.
#
# OWNER REVISIT: sources/owner-revisit.json lists charts the owner will revisit by hand. Their
# current state is accepted - no loop re-opens, re-fixes or flags them. is_owner_revisit() is
# the skip every loop checks (owner_revisit_skip() gives the reason it logs); the corpus grade's
# gate fails a commit pass that changes one of their blocks (by block_sha and header_sha,
# recorded in the file).
#
# FOOTAGE CORRUPT: sources/footage-corrupt.json lists cached videos no reader can use (the
# container does not open, or the footage stops decoding long before it ends). A loop gives a
# chart on one a FOOTAGE_CORRUPT verdict (footage_corrupt_reason()) rather than a PARK.
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER_REVISIT = os.path.join(ROOT, "sources", "owner-revisit.json")

_TAG = re.compile(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$")


def tag_of(key):
    """chartstruct key -> converter tag: "Slam_-_Novasonic_D24_ARCADE" -> "D24_ARCADE",
    "Bee_-_BanYa_S17_INFOBAR_TITLE_ARCADE" -> "S17 INFOBAR TITLE_ARCADE". The same rule as
    extract_repair.block_tag, which is what the repair loops edit by."""
    m = _TAG.search(key)
    if not m:
        raise ValueError("not a chartstruct key: %r" % key)
    return "%s_%s" % (m.group(1).replace("_", " "), m.group(2))


def normalize(data):
    """bytes or str -> str decoded as UTF-8 (errors="replace") with CRLF and CR made LF."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    return data.replace("\r\n", "\n").replace("\r", "\n")


_NOTEDATA = re.compile(r"^#NOTEDATA:", re.M)


def split_blocks(data):
    """(header text, [block text, ...]) by the contract above, each already rstripped."""
    text = normalize(data)
    starts = [m.start() for m in _NOTEDATA.finditer(text)]    # line starts only: text is LF-only
    if not starts:
        return text.rstrip(), []
    ends = starts[1:] + [len(text)]
    return text[:starts[0]].rstrip(), [text[a:b].rstrip() for a, b in zip(starts, ends)]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _kv(text):
    """piu-annotate's parse_ssc_to_dict, without its assert: #KEY:VALUE; pairs, value unstripped."""
    out = {}
    for kv in text.split(";"):
        if ":" in kv:
            k, *v = kv.strip().split(":")
            if k.startswith("#"):
                out[k[1:]] = ":".join(v)
    return out


def _tags(header, blocks):
    head = _kv(header)
    tags = []
    for b in blocks:
        d = dict(head)
        d.update(_kv(b))
        tags.append("%s_%s" % (d.get("DESCRIPTION", ""), d.get("SONGTYPE", "")))
    return tags


def block_tags(data):
    """The converter tag of every block, in file order (header tags inherited)."""
    return _tags(*split_blocks(data))


def file_index(data):
    """One pass over a file: {"header_sha": ..., "blocks": [(tag, block_sha), ...]} in file order."""
    header, blocks = split_blocks(data)
    return dict(header_sha=sha(header), blocks=list(zip(_tags(header, blocks), [sha(b) for b in blocks])))


def block_index(data, block_id):
    """block_id (an index or a converter tag) -> index into split_blocks' list, or None."""
    if isinstance(block_id, int):
        return block_id if 0 <= block_id < len(split_blocks(data)[1]) else None
    tags = block_tags(data)
    return tags.index(block_id) if block_id in tags else None


def block_sha_text(data, block_id):
    """block_sha of one block of a file's contents (bytes or str, e.g. a git blob)."""
    _, blocks = split_blocks(data)
    i = block_index(data, block_id)
    if i is None:
        raise LookupError("no block %r" % (block_id,))
    return sha(blocks[i])


def header_sha_text(data):
    return sha(split_blocks(data)[0])


def _read(ssc_path):
    with open(ssc_path, "rb") as f:
        return f.read()


def block_sha(ssc_path, block_id):
    """sha256 hex of block `block_id` (index or converter tag) of the .ssc at ssc_path."""
    return block_sha_text(_read(ssc_path), block_id)


def header_sha(ssc_path):
    return header_sha_text(_read(ssc_path))


# ---------------------------------------------------------------- owner revisit

def owner_revisit(path=OWNER_REVISIT):
    """The owner-revisit entries (chart, key, ssc_rel, block, block_sha, header_sha, ...)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("charts", [])


def is_owner_revisit(chart_or_key, path=OWNER_REVISIT):
    """True when a chart name ("Slam D24") or chartstruct key ("Slam_-_Novasonic_D24_ARCADE")
    is on the owner-revisit list. A loop that gets True skips the chart: it does not survey,
    re-fix or flag it."""
    return owner_revisit_entry(chart_or_key, path) is not None


def owner_revisit_entry(chart_or_key, path=OWNER_REVISIT):
    """The owner-revisit entry naming this chart (by name or key), or None."""
    for e in owner_revisit(path):
        if chart_or_key in (e.get("chart"), e.get("key")):
            return e
    return None


def owner_revisit_skip(*names, path=OWNER_REVISIT):
    """The reason a loop logs when it skips a chart for being on the owner-revisit list (any of
    `names` - a chart name, a key - matching), or None when it is not on the list. Every
    worklist that can ship a file checks this before a chart is surveyed or committed."""
    for n in names:
        e = owner_revisit_entry(n, path) if n else None
        if e is not None:
            why = e.get("why_revisit") or e.get("state") or ""
            return ("owner revisit: %s is on sources/owner-revisit.json, accepted as it stands until the owner "
                    "changes it himself - not surveyed, re-fixed or shipped%s" % (e.get("chart"), (" (%s)" % why) if why else ""))
    return None


# ---------------------------------------------------------------- footage that cannot be read

FOOTAGE_CORRUPT = os.path.join(ROOT, "sources", "footage-corrupt.json")


def footage_corrupt(path=FOOTAGE_CORRUPT):
    """{vid: entry} for every cached video recorded as unusable footage (sources/footage-corrupt.json):
    the container does not open, the video stops decoding long before it ends, or it decodes with
    errors. A loop that meets one gives the chart a FOOTAGE_CORRUPT verdict instead of parking it:
    no reader change can rescue it, and a rescan gives the same file. Only a fresh download does,
    which loops may not do."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {e["vid"]: e for e in json.load(f).get("videos", [])}


def footage_corrupt_reason(vid, band=None, path=FOOTAGE_CORRUPT):
    """"FOOTAGE_CORRUPT: <why>" when this video (and band, if the entry names bands) is recorded as
    unusable footage, else None."""
    e = footage_corrupt(path).get(vid)
    if e is None or (band and e.get("bands") and band not in e["bands"]):
        return None
    return "FOOTAGE_CORRUPT: videos/%s.mp4 %s (sources/footage-corrupt.json) - re-download it; loops may not" % (vid, e.get("problem", "is unusable"))
