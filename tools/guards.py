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
# the skip every loop checks; the corpus grade's gate fails a commit pass that changes one of
# their blocks (by block_sha and header_sha, recorded in the file).
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
    for e in owner_revisit(path):
        if chart_or_key in (e.get("chart"), e.get("key")):
            return True
    return False
