"""Where the river is, in screen space, from the PWD hydrography layer.

The PWD layer stops at the state line in the middle of the Delaware, so it
covers only the Pennsylvania half of the river. Shares computed here are a
lower bound for frames that reach the New Jersey side.
"""

import json

import numpy as np
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from .projection import IsoCamera, LocalFrame
from .sources import RAW

WATER_THRESHOLD = 0.01  # share of a frame above which it is said to show water


def water_screen_geometry(cfg: dict, frame: LocalFrame, cam: IsoCamera):
    data = json.loads((RAW / f"{cfg['name']}_water.geojson").read_text())
    polys = []
    for feat in data["features"]:
        g = shape(feat["geometry"])
        for p in [g] if g.geom_type == "Polygon" else list(g.geoms):
            lon, lat = np.asarray(p.exterior.coords).T[:2]
            e, n = frame.to_local(lon, lat)
            sx, sy = cam.world_to_screen(e, n, 0.0)
            polys.append(Polygon(zip(sx, sy)).buffer(0))
    return unary_union(polys)


def water_share(water_geom, x0: int, y0: int, size: int) -> float:
    return water_geom.intersection(box(x0, y0, x0 + size, y0 + size)).area / (size * size)


def water_sentence(share: float) -> str:
    """One sentence of ground truth for the redraw prompt (tiny.london's trick:
    telling the model where water is stops it painting lawns as ponds and
    stops it inventing landmarks on the river).

    The British "colour" is deliberate: this text is part of the prompt, and
    every redraw so far was made with it. Changing it would change the prompt
    without a version bump."""
    if share < WATER_THRESHOLD:
        return (
            "WATER IN THIS VIEW: none. Nothing in this view is water, so nothing in it "
            "uses the water colour."
        )
    return (
        f"WATER IN THIS VIEW: about {round(share * 100)}% of the image is river. Draw it as "
        "calm water in one consistent water colour, exactly where the render shows it. "
        "Put nothing on the water that the render does not show there."
    )
