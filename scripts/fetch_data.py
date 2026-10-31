#!/usr/bin/env python3
"""Fetch and verify the oversized sources listed in metadata/sources.csv.

Most of data/raw/ is committed to this repository, so a fresh clone already
has the GeoJSON ward boundaries (2012, 2017, 2022 and the community-published
pre-2012 144-ward file), the tender PDFs, the Census xlsx and the ward-level
PMC Census CSV. The one exception is the ~212 MB OSM extract, which exceeds
GitHub's 100 MiB per-file push limit and is therefore git-ignored. This script
exists mainly to fetch that, and secondarily to let you re-download and
re-verify any source.

For each selected row:
  * if the file is present with the recorded SHA-256, it is kept as-is;
  * if it is absent and the URL is fetchable, it is downloaded and the hash
    checked BEFORE it is moved into place;
  * if the URL is not a retrievable artefact (e.g. "local-user-supplied", or a
    portal landing page), the file is reported as needing manual supply.

Nothing is ever written into data/raw/ unless its SHA-256 matches, so a bad or
interstitial-page download cannot masquerade as research data. Existing files
are never overwritten unless you pass --force.

Usage:
    python scripts/fetch_data.py            # large files only (default)
    python scripts/fetch_data.py --all      # every row, incl. committed files
    python scripts/fetch_data.py --check    # verify what is on disk, no network
    python scripts/fetch_data.py --force    # replace existing mismatched files

The default scope is governed by LARGE_PATTERNS below; add to it if other
sources ever grow past the 100 MiB limit. Keep it in step with .gitignore.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# All paths are anchored to the repository root (the parent of scripts/), so
# this script behaves identically whatever the working directory is - the same
# convention the extraction scripts follow.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "metadata" / "sources.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
CHUNK = 1 << 20
TIMEOUT = 120
USER_AGENT = "securities-to-spatial-surveillance/1.0 (reproducibility check)"

# Files too large to commit; keep in step with the ignore rules in .gitignore.
LARGE_PATTERNS = ("*.pbf", "*.osm.pbf")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def is_large(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in LARGE_PATTERNS)


def is_fetchable(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def download(url: str, dest_dir: str) -> str:
    """Download to a temp file in dest_dir and return its path."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".partial-")
    os.close(fd)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(CHUNK):
            out.write(chunk)
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch and verify oversized sources. Files committed to the "
                    "repository are already present in a clone."
    )
    ap.add_argument("--all", action="store_true",
                    help="include files that are already committed to the repo")
    ap.add_argument("--check", action="store_true", help="verify only, no network")
    ap.add_argument("--force", action="store_true", help="replace mismatched files")
    args = ap.parse_args()

    if not os.path.exists(CSV_PATH):
        print(f"error: {CSV_PATH} not found", file=sys.stderr)
        return 2

    os.makedirs(RAW_DIR, exist_ok=True)

    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if args.all or args.check:
        selected = rows
    else:
        selected = [r for r in rows if is_large(r["filename"])]
        print("default scope: large (git-ignored) files only; "
              "use --all for every source")
        print()

    ok, manual, failed = [], [], []

    for row in selected:
        name = row["filename"]
        url = (row["url"] or "").strip()
        want = row["sha256"].strip().lower()
        dest = os.path.join(RAW_DIR, name)

        # Already present and correct? Nothing to do.
        if os.path.exists(dest):
            got = sha256_of(dest)
            if got == want:
                print(f"OK        {name}")
                ok.append(name)
                continue
            print(f"MISMATCH  {name}")
            print(f"          expected {want}")
            print(f"          found    {got}")
            if not args.force:
                failed.append(name)
                continue
            os.remove(dest)

        if args.check:
            print(f"MISSING   {name}  (not downloaded; --check given)")
            manual.append(name)
            continue

        if not is_fetchable(url):
            print(f"MANUAL    {name}  (url = {url!r}; supply this file by hand)")
            manual.append(name)
            continue

        print(f"FETCH     {name}  <- {url}")
        tmp = None
        try:
            tmp = download(url, RAW_DIR)
            got = sha256_of(tmp)
            if got != want:
                print(f"MISMATCH  {name}")
                print(f"          expected {want}")
                print(f"          found    {got}")
                print("          the URL did not return the archived bytes "
                      "(landing page, session token, or updated file?)")
                failed.append(name)
                os.remove(tmp)
                continue
            os.replace(tmp, dest)
            tmp = None
            print(f"OK        {name}")
            ok.append(name)
        except (urllib.error.URLError, OSError) as exc:
            print(f"ERROR     {name}: {exc}")
            failed.append(name)
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    print()
    print(f"{len(ok)} verified, {len(manual)} need manual supply, {len(failed)} failed")
    if manual:
        print("\nSupply these manually, then re-run this script to verify:")
        for name in manual:
            print(f"  - {name}")
    if failed:
        print("\nUnresolved:")
        for name in failed:
            print(f"  - {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
