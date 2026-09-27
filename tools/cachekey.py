# Cache keys that carry everything the cached thing depends on, without throwing away the caches
# that exist.
#
# A cache named by some of its inputs hands back a stale answer the day one of the others moves.
# The sprite-pass key (note_extract) named the video, lanes and contrast scale but not the
# detection floor the pass was cut at, the band it watched or the sprite box it matched with; the
# receptor-template key (sprites.anchors) named the lanes but not the sprite size or the band's
# rows; and neither said which version of the code built it. Change any of those and the old file
# comes back under the old name, silently.
#
# The fix keeps the old names working. Each cache states its FULL parameter set - every input,
# plus a stamp of the code that computes it - and today's values of everything the old name left
# out (its LEGACY values, frozen here and in the callers). While every parameter equals its
# legacy value the key is the old name, so the 1,413 sprite passes (about seven hours of decoding)
# and every other existing cache still hit. The moment one differs - a floor, a band, a rule in
# the code - the name gains a suffix `.k<digest of the full parameter set>`, and that parameter
# set gets its own file instead of someone else's. New files also get a <file>.meta.json sidecar
# (atomicio.write_meta) that spells the parameters out.
#
# The code stamp is a hash of the functions' syntax trees with docstrings removed, so a comment
# or a docstring can change freely and a change to what the code does moves the stamp. It is the
# COMPUTE functions that are stamped, never the caching wrapper around them - a wrapper change
# does not change what is cached. A new Python version may print syntax trees differently; the
# stamp would then move and the caches rebuild, which is the safe direction to fail in.
import ast
import hashlib
import inspect
import json
import textwrap


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return tree


_stamps = {}


def code_stamp(*funcs):
    """16 hex digits over the syntax trees of `funcs` (docstrings and comments ignored)."""
    key = tuple(funcs)
    if key not in _stamps:
        h = hashlib.sha256()
        for fn in funcs:
            tree = _strip_docstrings(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            h.update(ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8"))
            h.update(b"\0")
        _stamps[key] = h.hexdigest()[:16]
    return _stamps[key]


def canon(params):
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=repr)


def digest(params):
    return hashlib.sha256(canon(params).encode("utf-8")).hexdigest()[:12]


def keyed(legacy_path, suffix, params, legacy_params):
    """`legacy_path` while every parameter equals its legacy value; otherwise the same name with
    `.k<digest>` inserted before `suffix` (the part of the name that says what kind of file it is:
    ".pkl", ".sprites.npz", ".field.json", ".jsonl" ...)."""
    if canon(params) == canon(legacy_params):
        return legacy_path
    return suffixed(legacy_path, suffix, params)


def suffixed(legacy_path, suffix, params):
    """The name `params` gets when it cannot have the legacy one."""
    if not legacy_path.endswith(suffix):
        raise ValueError("%s does not end with %s" % (legacy_path, suffix))
    return legacy_path[:-len(suffix)] + ".k" + digest(params) + suffix


# Today's values of the things the old names left out are not all constants: some are derived
# from the video. These are those derivations as they stood when the existing caches were built,
# frozen here so that a later change to the live code cannot make an old file look current.

def legacy_sprite_box(pitch):
    """sprites.size_for as it stood when the existing template and pass caches were built."""
    tw = int(round(pitch * 0.86)) | 1
    return tw, tw


def legacy_rows(frame_h):
    """The receptor band's rows, as receptors.geometry and field cut it from a frame this tall."""
    return int(frame_h * 0.07), int(frame_h * 0.21)


def legacy_lanes(xs):
    """The lanes as every fit so far spread them: evenly between the first and last, to the pixel
    a rounding moves them. Anything else is a different fit - None, which never equals a list."""
    xs = [int(x) for x in xs]
    if len(xs) < 2:
        return xs
    step = (xs[-1] - xs[0]) / (len(xs) - 1)
    return xs if all(abs(x - (xs[0] + k * step)) <= 1.0 for k, x in enumerate(xs)) else None
