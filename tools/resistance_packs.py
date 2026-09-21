# Looks inside The Resistance's songpacks on MediaFire WITHOUT downloading them. The packs
# run from 150 MB to 1.4 GB; what matters in one is a changelog and a handful of .ssc
# entries. MediaFire's direct links honour HTTP Range, so a zip library handed a
# range-backed file object reads the central directory and then only the entries it is asked
# for - the whole session that found the v1.01.0 update moved under 5 MB.
#
#   python -X utf8 tools/resistance_packs.py list
#   python -X utf8 tools/resistance_packs.py changelog "PHOENIX2"
#   python -X utf8 tools/resistance_packs.py recent "PHOENIX songpack" --since 2026-08-10
#   python -X utf8 tools/resistance_packs.py get "PHOENIX songpack" "Fracture Temporelle" --out <dir>
#
# RUN IT WITH THE SYSTEM PYTHON, not the piu-annotate venv: the packs are AES zips, the
# standard zipfile cannot open them, and pyzipper is installed only there.
#
# The entries are encrypted with the password The Resistance publish alongside each release.
# It is theirs to give out, so it is NOT written here: pass --password or set
# RESISTANCE_PACK_PASSWORD. `list` and `recent` read names, sizes and dates only and need none.
#
# Read-only, and deliberately light on their host: one page fetch per pack to resolve the
# link, then 256 KB ranges. Their CREDITS.txt says do not redistribute - what this fetches is
# evidence for editing our own files (apply_upstream_fix.py), never something to commit.
import argparse
import datetime
import io
import json
import os
import re
import sys
import urllib.request

HUB = "3jlhzq10y70jj"                      # The Resistance Simfiles, public folder key
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
BLOCK = 256 * 1024


def fetch(url, rng=None, timeout=120):
    headers = {"User-Agent": UA}
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read()


def hub_files():
    url = (f"https://www.mediafire.com/api/1.4/folder/get_content.php?folder_key={HUB}"
           "&content_type=files&response_format=json&chunk_size=200")
    return json.loads(fetch(url))["response"]["folder_content"].get("files", [])


def pick(name_part):
    hits = [f for f in hub_files() if name_part.lower() in f["filename"].lower()]
    if len(hits) != 1:
        sys.exit(f"{name_part!r} matches {len(hits)} packs: {[f['filename'] for f in hits]}")
    return hits[0]


def direct_link(quickkey):
    html = fetch(f"https://www.mediafire.com/file/{quickkey}", timeout=60).decode("utf-8", "replace")
    m = re.search(r"https://download\d*\.mediafire\.com/[^\"' ]+", html)
    if not m:
        sys.exit("no direct link on the file page (MediaFire changed its markup?)")
    return m.group(0)


class RangeFile(io.RawIOBase):
    """A seekable read-only file over HTTP Range, cached in 256 KB blocks."""

    def __init__(self, url, size):
        self.url, self.size, self.pos, self.blocks, self.fetched = url, size, 0, {}, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def _block(self, b):
        if b not in self.blocks:
            lo, hi = b * BLOCK, min((b + 1) * BLOCK, self.size) - 1
            data = fetch(self.url, (lo, hi))
            if len(data) != hi - lo + 1:
                raise IOError(f"range {lo}-{hi} came back as {len(data)} bytes")
            self.blocks[b] = data
            self.fetched += len(data)
        return self.blocks[b]

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else n
        n = max(0, min(n, self.size - self.pos))
        out = bytearray()
        while len(out) < n:
            b, o = divmod(self.pos, BLOCK)
            chunk = self._block(b)[o:o + n - len(out)]
            out += chunk
            self.pos += len(chunk)
        return bytes(out)

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)


def open_pack(name_part, password=None):
    import pyzipper
    f = pick(name_part)
    rf = RangeFile(direct_link(f["quickkey"]), int(f["size"]))
    z = pyzipper.AESZipFile(rf)
    if password:
        z.setpassword(password.encode())
    return f, rf, z


def need_password(a):
    pw = a.password or os.environ.get("RESISTANCE_PACK_PASSWORD")
    if not pw:
        sys.exit("this reads encrypted entries: pass --password or set RESISTANCE_PACK_PASSWORD")
    return pw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "changelog", "recent", "get"])
    ap.add_argument("pack", nargs="?")
    ap.add_argument("entry", nargs="?")
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--out", default=".")
    ap.add_argument("--password")
    a = ap.parse_args()

    if a.cmd == "list":
        for f in sorted(hub_files(), key=lambda f: f["created_utc"]):
            print(f"{f['created_utc']}  {int(f['size']) / 1048576:8.1f} MB  {f['quickkey']}  {f['filename']}")
        return
    if not a.pack:
        sys.exit("name the pack (any part of its file name)")

    if a.cmd == "recent":
        since = datetime.datetime.fromisoformat(a.since)
        f, rf, z = open_pack(a.pack)
        rows = [(datetime.datetime(*i.date_time), i.file_size, i.filename) for i in z.infolist()
                if not i.filename.endswith("/") and datetime.datetime(*i.date_time) >= since]
        print(f"{f['filename']}: {len(z.infolist())} entries, {len(rows)} modified since {a.since} (entry times are the packer's local clock)")
        for dt, size, name in sorted(rows):
            print(f"   {dt}  {size:>10,}  {name}")
    elif a.cmd == "changelog":
        f, rf, z = open_pack(a.pack, need_password(a))
        for i in z.infolist():
            if "changelog" in i.filename.lower() and i.filename.lower().endswith(".txt"):
                print(f"--- {f['filename']} :: {i.filename}  ({datetime.datetime(*i.date_time)})")
                print(z.read(i).decode("utf-8-sig", errors="replace"))
    else:
        if not a.entry:
            sys.exit("name the entry (any part of its path)")
        f, rf, z = open_pack(a.pack, need_password(a))
        os.makedirs(a.out, exist_ok=True)
        for i in z.infolist():
            if a.entry.lower() in i.filename.lower() and i.filename.lower().endswith(".ssc"):
                out = os.path.join(a.out, os.path.basename(i.filename))
                open(out, "wb").write(z.read(i))
                print(f"   {i.file_size:>10,}  {datetime.datetime(*i.date_time)}  {i.filename}  ->  {out}")
    print(f"[{rf.fetched:,} bytes fetched]")


if __name__ == "__main__":
    main()
