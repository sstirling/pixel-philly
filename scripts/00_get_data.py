"""Download the raw-data snapshot the map was built from into data/raw/.

The downloads in data/raw/ (City of Philadelphia, USGS, OpenStreetMap and other
layers; 478 files, about 1.6 GB) used to be tracked in git. They are now one
compressed archive attached to a GitHub release, so the repository stays small.
This script gets that exact snapshot. The fetch scripts (01-04q) download the
live layers instead, which may have changed since the map was drawn.

What it checks:
- the archive's SHA-256 (ARCHIVE_SHA256 below);
- every unpacked file against data/raw/SHA256SUMS (tracked in git), and that
  the archive holds exactly those files;
- raw data is immutable: a file already in data/raw/ that differs from the
  snapshot is never overwritten; the run stops and nothing is changed.
Unpacking uses tarfile's "data" filter, which refuses absolute paths, links
and anything that would land outside the destination.

data/raw/MANIFEST.json (every query, extent and fetch time) stays in git and
is not part of the archive.

Usage:
  uv run python scripts/00_get_data.py                     # download (~190 MB) and unpack
  uv run python scripts/00_get_data.py --archive FILE      # use a copy already on disk
Standard library only, so it runs before `uv sync` too:
  python3 scripts/00_get_data.py
"""

import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw"
SUMS = RAW / "SHA256SUMS"

RELEASE_TAG = "data-2026-11-11"
ARCHIVE_NAME = "pixel-philly-data-raw-2026-11-11.tar.xz"
URL = f"https://github.com/sstirling/pixel-philly/releases/download/{RELEASE_TAG}/{ARCHIVE_NAME}"
ARCHIVE_SHA256 = "92c7284c150a4749441b9bae25c9ed07761f0e62c4c174e06c7c8093cb44742f"


class GetDataError(Exception):
    pass


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def read_sums(path):
    """{file name: sha256} from a `shasum -a 256` listing."""
    sums = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.lstrip("*")] = digest
    return sums


def install(archive, dest, sums, expected_archive_sha=None):
    """Unpack `archive` into `dest`, checked against `sums`. Returns the number
    of files added. Everything is checked in a staging folder first, so a
    failed check leaves `dest` exactly as it was."""
    archive, dest = Path(archive), Path(dest)
    if expected_archive_sha is not None and sha256_file(archive) != expected_archive_sha:
        raise GetDataError(f"archive checksum doesn't match: {archive} is damaged or not the expected snapshot")
    stage = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=dest.parent))
    try:
        try:
            with tarfile.open(archive, "r:*") as tar:
                for m in tar.getmembers():
                    if not m.isfile() or "/" in m.name or m.name not in sums:
                        raise GetDataError(f"{m.name}: not in SHA256SUMS (or not a plain file); refusing the archive")
                tar.extractall(stage, filter="data")
        except tarfile.TarError as e:
            raise GetDataError(f"unsafe or unreadable archive: {e}") from e
        missing = sorted(n for n in sums if not (stage / n).is_file())
        if missing:
            raise GetDataError(f"{len(missing)} files missing from the archive, e.g. {missing[:3]}")
        for name, digest in sums.items():
            if sha256_file(stage / name) != digest:
                raise GetDataError(f"{name}: checksum doesn't match SHA256SUMS")
        to_add = []
        for name, digest in sums.items():
            target = dest / name
            if target.exists():
                if sha256_file(target) != digest:
                    raise GetDataError(f"{target} differs from the snapshot; raw data is never overwritten. "
                                       "Move it aside to replace it.")
            else:
                to_add.append(name)
        for name in to_add:
            (stage / name).replace(dest / name)
        return len(to_add)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def download(url, out):
    part = out.with_suffix(out.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "pixel-philly 00_get_data.py"})
    with urllib.request.urlopen(req) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while block := r.read(1 << 20):
            f.write(block)
            done += len(block)
            if total:
                print(f"\r  {done / 1e6:,.0f} of {total / 1e6:,.0f} MB", end="", flush=True)
    print()
    part.replace(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", type=Path, help="use this local copy of the archive instead of downloading")
    ap.add_argument("--keep", action="store_true", help="keep the downloaded archive (in output/release/)")
    args = ap.parse_args()

    sums = read_sums(SUMS)
    RAW.mkdir(parents=True, exist_ok=True)
    if all((RAW / n).exists() for n in sums):
        print(f"data/raw already has all {len(sums)} snapshot files; checking them.")
        bad = [n for n, d in sums.items() if sha256_file(RAW / n) != d]
        if bad:
            sys.exit(f"{len(bad)} files differ from the snapshot, e.g. {bad[:3]}")
        print("All match.")
        return

    archive = args.archive
    if archive is None:
        archive = REPO_ROOT / "output" / "release" / ARCHIVE_NAME
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            print(f"Downloading {URL}")
            download(URL, archive)
    print(f"Checking and unpacking {archive}")
    try:
        added = install(archive, RAW, sums, expected_archive_sha=ARCHIVE_SHA256)
    except GetDataError as e:
        sys.exit(f"Stopped: {e}")
    print(f"Added {added} files to data/raw/ ({len(sums) - added} were already there and match).")
    if args.archive is None and not args.keep:
        archive.unlink()


if __name__ == "__main__":
    main()
