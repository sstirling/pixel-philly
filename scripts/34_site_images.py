"""Cut the site's favicon, touch icon and social preview from a frozen map.

No drawing and no GPU: every image is a crop of the finished Deep Zoom tiles
(output/<area>/tiles/<version>/map_files), cut with the same Pyramid.window
that renders the flyover video (scripts/29_flyover.py). So the icons show the
map itself, not a separate logo.

Crops (chosen by eye from contact sheets in output/review/site_images/, Nov. 10):
- Social preview, 1200 x 630 (the size Facebook, LinkedIn, Slack and X use for
  large link cards): the Center City skyline, from Logan Square to the Comcast
  towers, at 3 map px per image px.
- Favicon (favicon.ico, 16/32/48 px) and apple-touch-icon.png (180 px): the top
  of City Hall's tower. A whole street scene turns to mush at 32 px; the white
  tower against darker buildings is the one shape that still reads.

Positions are lon/lat plus a height in meters: in the isometric view a tall
building's base is hidden, so the crops aim at the tower top (see
Pyramid.to_px). The pixel offsets below move from that aim point to the spire
and were also picked by eye.

Usage:
  .venv/bin/python scripts/34_site_images.py            # from v18
  .venv/bin/python scripts/34_site_images.py --version v19
Writes viewer/og-image.jpg, viewer/favicon.ico, viewer/apple-touch-icon.png
"""

import argparse
import importlib.util
from pathlib import Path

from PIL import Image

from pixelphilly.projection import REPO_ROOT

# Pyramid lives in a script whose name starts with a digit, so load it by path
_spec = importlib.util.spec_from_file_location("flyover", REPO_ROOT / "scripts" / "29_flyover.py")
_flyover = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_flyover)

# lon, lat, height aimed at (m), extra map-px offset (dx, dy), map px per out px
SOCIAL = dict(lonlat=(-75.1690, 39.9530), z=120, offset=(0, 0), scale=3)
# City Hall (same point as the viewer's START_VIEW), aimed 150 m up; the spire
# sits about 92 map px left of that aim point
TOWER = dict(lonlat=(-75.16355, 39.9524), z=150, offset=(-92, -20))
FAVICON_SCALE = 4      # 128 map px of tower -> 32 px; 16 and 48 px resampled from 128
TOUCH_SCALE = 1        # 180 map px of tower at 1:1 for the 180 px touch icon


def center(pyr, spec):
    x, y = pyr.to_px(*spec["lonlat"], spec["z"])
    return x + spec["offset"][0], y + spec["offset"][1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", default="philly")
    ap.add_argument("--version", default="v18")
    args = ap.parse_args()

    pyr = _flyover.Pyramid(REPO_ROOT / "output" / args.area / "tiles" / args.version)
    out = REPO_ROOT / "viewer"

    social = pyr.window(*center(pyr, SOCIAL), SOCIAL["scale"], 1200, 630)
    social.save(out / "og-image.jpg", quality=88, optimize=True, progressive=True)

    cx, cy = center(pyr, TOWER)
    # Box-filter down from a 128 px crop at 1 map px per px for every icon
    # size, so the 16, 32 and 48 px icons are all the same view
    base = pyr.window(cx, cy, FAVICON_SCALE * 32 / 128, 128, 128)
    base.save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    pyr.window(cx, cy, TOUCH_SCALE, 180, 180).save(out / "apple-touch-icon.png", optimize=True)

    for f in ("og-image.jpg", "favicon.ico", "apple-touch-icon.png"):
        print(f"{out / f}  {(out / f).stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
