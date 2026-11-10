"""Self-contained offline copy of a merged map for a talk (no internet).

    uv run python scripts/27_offline_copy.py --name philly --version v14 \
        [--out output/philly_offline_v14] [--no-photo]

Writes <out>/ with the viewer (OpenSeadragon is already vendored in
viewer/vendor/), the version's tiles under the same relative path the viewer
expects (output/<name>/tiles/<version>/), start scripts that serve the folder
with Python's built-in web server on 127.0.0.1, and a README. The copy's
index.html sets data-offline="1", which turns off address search (the only
feature that calls a remote API: the City's AIS) so the page makes no
request off the machine. Tiles are copied, not linked, so the folder can go
on a USB drive.
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

START_SH = """#!/bin/sh
# Serves this folder on http://127.0.0.1:{port}/ (no internet needed).
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "Python 3 is needed (python3 not found)."; exit 1; fi
URL="http://127.0.0.1:{port}/viewer/?area={name}&v={version}"
echo "Pixel Philly offline: open $URL  (Ctrl+C to stop)"
( sleep 1; open "$URL" || xdg-open "$URL" ) >/dev/null 2>&1 &
exec "$PY" -m http.server {port} --bind 127.0.0.1
"""

START_BAT = """@echo off
rem Serves this folder on http://127.0.0.1:{port}/ (no internet needed).
cd /d "%~dp0"
start "" "http://127.0.0.1:{port}/viewer/?area={name}&v={version}"
python -m http.server {port} --bind 127.0.0.1
"""

README = """Pixel Philly: offline copy of the {name} map, version {version}
=================================================================

This folder runs the map with no internet connection. Nothing is sent off
the computer: the map tiles, the viewer and its OpenSeadragon library are all
in this folder. Address search is turned off here, because it needs the City
of Philadelphia's AIS service online.

What you need
- Python 3 (any 3.x; macOS and Linux usually have it; on Windows install it
  from python.org and tick "Add python.exe to PATH").
- A current browser (Chrome, Firefox, Safari or Edge).

Start it
- macOS: double-click start.command. If macOS blocks it the first time,
  right-click > Open > Open. Or, in Terminal:  sh start.sh
- Linux:  sh start.sh
- Windows: double-click start.bat
The browser opens http://127.0.0.1:{port}/viewer/?area={name}&v={version}
(open that address yourself if it doesn't). Leave the terminal window open
while presenting; close it (or press Ctrl+C) to stop.

If port {port} is in use, run instead, from this folder:
    python3 -m http.server 8200 --bind 127.0.0.1
and open http://127.0.0.1:8200/viewer/?area={name}&v={version}

Using the map
- Drag to pan; scroll, the +/- buttons or the +/- keys to zoom; the house
  button shows the whole city.
{photo_line}- The view is kept in the address bar, so a bookmarked address reopens the
  same spot (on this computer, while the server runs).

About the map
- An AI-generated illustration, not a photograph or survey. Credits are under
  "credits" at the bottom of the page.
- Frozen version: see FROZEN_{version}.json (file count and a SHA-256 of
  every file) to check this copy is the talk map.

Contents
- viewer/        the web page (index.html, viewer.js, OpenSeadragon in vendor/)
- output/{name}/tiles/{version}/   the map tiles (Deep Zoom, WebP){layers}
- start.sh, start.command, start.bat   start scripts
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="philly")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out")
    ap.add_argument("--port", type=int, default=8137)
    ap.add_argument("--no-photo", action="store_true", help="leave out the photo (render) layer")
    args = ap.parse_args()

    src = REPO_ROOT / "output" / args.name / "tiles" / args.version
    if not (src / "map.json").exists():
        sys.exit(f"no map at {src}")
    out = Path(args.out) if args.out else REPO_ROOT / "output" / f"{args.name}_offline_{args.version}"
    if out.exists():
        sys.exit(f"{out} exists; remove it first")
    out.mkdir(parents=True)

    # Viewer, with the offline flag on the <html> element
    shutil.copytree(REPO_ROOT / "viewer", out / "viewer")
    index = out / "viewer" / "index.html"
    html = index.read_text()
    assert '<html lang="en">' in html
    index.write_text(html.replace('<html lang="en">', '<html lang="en" data-offline="1">', 1))
    # The hosted pages carry a GoatCounter visit counter, a remote request;
    # the offline copy promises none, so the counter is removed from both pages
    import re

    for page in ("index.html", "about.html"):
        p = out / "viewer" / page
        p.write_text(re.sub(r"<!-- Visit counter.*?</script>\n", "", p.read_text(), flags=re.S))
        assert "goatcounter" not in p.read_text(), f"counter left in offline {page}"

    # Tiles, at the path the viewer resolves (../output/<name>/tiles/<v>/)
    import json

    meta = json.loads((src / "map.json").read_text())
    dst = out / "output" / args.name / "tiles" / args.version
    skip = set()
    if args.no_photo and meta.get("layers", {}).get("photo"):
        photo = meta["layers"]["photo"]
        skip = {photo, photo.replace(".dzi", "_files")}
        meta["layers"].pop("photo")
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if Path(d) == src and n in skip])
    if skip:
        (dst / "map.json").write_text(json.dumps(meta, indent=1))
    frozen = REPO_ROOT / "output" / args.name / f"FROZEN_{args.version}.json"
    if frozen.exists():
        shutil.copy2(frozen, out / frozen.name)

    fmt = dict(name=args.name, version=args.version, port=args.port)
    for fn, body in (("start.sh", START_SH), ("start.command", START_SH), ("start.bat", START_BAT)):
        (out / fn).write_text(body.format(**fmt))
        (out / fn).chmod(0o755)
    has_photo = bool(meta.get("layers", {}).get("photo"))
    (out / "README.txt").write_text(README.format(
        **fmt,
        photo_line="- \"Show photo\" switches to the render the AI drew from (2024 City aerials\n"
                   "  on 3D buildings), lined up pixel for pixel.\n" if has_photo else "",
        layers=", illustration and photo layers" if has_photo else ", illustration layer"))
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"-> {out}: {size / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
