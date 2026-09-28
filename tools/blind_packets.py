# Blind, seeded eye-read packets (the owner's 2026-09-26 ruling on what agent eye-reads may count
# as: "blind, seeded contact-sheet review counts as 'looked at' for labeling atlas glyphs and
# certification cells"). A loop that needs a human-style look at frames never looks and decides
# itself: it writes packets, stops, and is resumed with two independent readers' answers.
#
#   A packet is a folder work/blind/<loop>/<batch>/<packet-id>/ holding only images with opaque
#   names and question.json {"id", "instructions", "items": [{"item", "images", "ask",
#   "answer_format"}]} - no expected value, no chart name, nothing but what the images show.
#   Seeded known-answer items are mixed in; the key (which items are seeds, their answers, and what
#   every real item is) is kept outside the packet, in work/blind-keys/<loop>/<batch>.json.
#   At most 20 packets a hop and 40 items a packet.
#
#   Answers: work/blind-answers/<loop>/<batch>/<reader>/<packet-id>.json, {"id": <packet-id>,
#   "answers": {<item>: <answer string>}} (a bare {<item>: <answer>} is accepted too).
#   score(): a reader who misses any seeded item in a packet has that whole packet voided; a real
#   item is AGREED only when two unvoided readers give the same answer, otherwise it is UNSURE
#   (disagreement, a voided reader, a missing answer). Answers are compared after normalize().
#
#   blind_packets.py score --keys <keys.json> --answers <dir> [--out <report.json>]
import argparse
import hashlib
import json
import os
import random
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import atomicio  # noqa: E402

MAX_PACKETS, MAX_ITEMS = 20, 40


def normalize(ans):
    """An answer as compared: whitespace removed, the separators '/', ',', ';', '|' and newlines all
    read as '/', letters upper-cased (a '?' stays a '?')."""
    s = str(ans if ans is not None else "").strip()
    for sep in (",", ";", "|", "\n", "\r", "\\"):
        s = s.replace(sep, "/")
    s = "".join(s.split())
    while "//" in s:
        s = s.replace("//", "/")
    return s.strip("/").upper()


def make(loop, batch, items, seeds, instructions, per_packet=24, seed_share=0.25, rng_seed=None, root=ROOT):
    """Write the packets of one batch. `items` and `seeds` are lists of dicts:
    {"images": [(name_hint, png_bytes), ...], "ask", "answer_format", "meta": {...}} and seeds also
    carry "answer". Real items are split across packets in order; each packet gets
    ceil(seed_share * its size) seeds (drawn without replacement while they last, then reused
    across packets, never twice in one packet), shuffled in. Every id and file name is opaque.
    Returns (packet dirs, keys path). Refuses to exceed 20 packets or 40 items a packet."""
    rng = random.Random(rng_seed if rng_seed is not None else int.from_bytes(os.urandom(8), "big"))
    salt = "%016x" % rng.getrandbits(64)

    def opaque(*parts):
        return hashlib.sha256(("%s|%s" % (salt, "|".join(map(str, parts)))).encode()).hexdigest()[:10]

    n_real = max(1, int(per_packet / (1 + seed_share)))      # real items a packet takes; its seeds fill the rest
    chunks = [items[i:i + n_real] for i in range(0, len(items), n_real)]
    if len(chunks) > MAX_PACKETS:
        raise SystemExit("%d packets: at most %d a hop" % (len(chunks), MAX_PACKETS))
    pool = list(range(len(seeds)))
    rng.shuffle(pool)
    out_dirs, keys = [], dict(loop=loop, batch=batch, salt_hash=hashlib.sha256(salt.encode()).hexdigest()[:16],
                               instructions=instructions, packets={})
    base = os.path.join(root, "work", "blind", loop, batch)
    for pi, chunk in enumerate(chunks):
        k = max(1, int(-(-len(chunk) * seed_share // 1)))
        if len(pool) < k:
            pool += [i for i in range(len(seeds)) if i not in pool]
        chosen = pool[:k]
        pool = pool[k:]
        entries = [("real", i, it) for i, it in enumerate(chunk)] + [("seed", si, seeds[si]) for si in chosen]
        if len(entries) > MAX_ITEMS:
            raise SystemExit("packet %d would hold %d items: at most %d" % (pi, len(entries), MAX_ITEMS))
        rng.shuffle(entries)
        pid = "p" + opaque("packet", pi)
        pdir = os.path.join(base, pid)
        os.makedirs(pdir, exist_ok=True)
        q, key_items = [], {}
        for kind, idx, it in entries:
            iid = "i" + opaque(pid, kind, idx)
            names = []
            for j, (_hint, png) in enumerate(it["images"]):
                name = "%s_%d.png" % (iid, j)
                atomicio.write_bytes(os.path.join(pdir, name), png)
                names.append(name)
            q.append(dict(item=iid, images=names, ask=it["ask"], answer_format=it["answer_format"]))
            key_items[iid] = dict(kind=kind, meta=it.get("meta", {}),
                                  **({"answer": it["answer"]} if kind == "seed" else {}))
        atomicio.write_json(os.path.join(pdir, "question.json"),
                            dict(id=pid, instructions=instructions, items=q), encoding="utf-8", indent=1)
        keys["packets"][pid] = dict(dir=os.path.relpath(pdir, root).replace("\\", "/"), items=key_items)
        out_dirs.append((pid, pdir))
    kpath = os.path.join(root, "work", "blind-keys", loop, batch + ".json")
    os.makedirs(os.path.dirname(kpath), exist_ok=True)
    atomicio.write_json(kpath, keys, encoding="utf-8", ensure_ascii=False, indent=1)
    return out_dirs, kpath


def load_answers(adir):
    """{reader: {packet-id: {item: answer}}} from <adir>/<reader>/<packet-id>.json."""
    out = {}
    if not os.path.isdir(adir):
        return out
    for reader in sorted(os.listdir(adir)):
        rdir = os.path.join(adir, reader)
        if not os.path.isdir(rdir):
            continue
        for fn in sorted(os.listdir(rdir)):
            if not fn.endswith(".json"):
                continue
            d = atomicio.load_json(os.path.join(rdir, fn)) or {}
            pid = d.get("id") or fn[:-5]
            ans = d.get("answers", d if "id" not in d else {})
            out.setdefault(reader, {})[pid] = {k: v for k, v in ans.items() if isinstance(k, str)}
    return out


def score(keys, answers):
    """-> {"readers": {reader: {packet: "ok" | "void: ..." | "absent"}}, "items": {item: {verdict,
    answer, packet, meta, votes}}}. verdict AGREED (two unvoided readers, same answer) or UNSURE."""
    readers = sorted(answers)
    rep = dict(readers={r: {} for r in readers}, items={})
    for pid, p in keys["packets"].items():
        valid = {}
        for r in readers:
            a = answers[r].get(pid)
            if a is None:
                rep["readers"][r][pid] = "absent"
                continue
            missed = [iid for iid, it in p["items"].items()
                      if it["kind"] == "seed" and normalize(a.get(iid)) != normalize(it["answer"])]
            if missed:
                rep["readers"][r][pid] = "void: missed %d of %d seeds" % (
                    len(missed), sum(1 for it in p["items"].values() if it["kind"] == "seed"))
                continue
            rep["readers"][r][pid] = "ok"
            valid[r] = a
        for iid, it in p["items"].items():
            if it["kind"] != "real":
                continue
            votes = {r: normalize(a.get(iid)) for r, a in valid.items() if a.get(iid) not in (None, "")}
            vals = set(votes.values())
            agreed = len(votes) >= 2 and len(vals) == 1 and "?" not in next(iter(vals))
            rep["items"][iid] = dict(packet=pid, meta=it["meta"], votes=votes,
                                     verdict="AGREED" if agreed else "UNSURE",
                                     answer=next(iter(vals)) if agreed else None,
                                     why=None if agreed else ("fewer than two valid readers" if len(votes) < 2
                                                              else "readers disagree" if len(vals) > 1
                                                              else "an unreadable digit"))
    return rep


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score")
    p.add_argument("--keys", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--out")
    a = ap.parse_args()
    keys = json.load(open(a.keys, encoding="utf-8"))
    rep = score(keys, load_answers(a.answers))
    if a.out:
        atomicio.write_json(a.out, rep, encoding="utf-8", ensure_ascii=False, indent=1)
    for r, ps in rep["readers"].items():
        print(r, {k: v for k, v in ps.items()})
    v = [it["verdict"] for it in rep["items"].values()]
    print("items: %d AGREED, %d UNSURE" % (v.count("AGREED"), v.count("UNSURE")))


if __name__ == "__main__":
    main()
