"""Bug (reported Oct. 21): on the New Jersey side of downtown the city's
aerial imagery ends; the scene builder filled those tiles with flat grey and
the model invented a scene there (a seaplane, a bridge, buildings and a large
cartoon person). Wherever there is no source imagery, the finished map must
show only the background, never generated content."""

import numpy as np
from PIL import Image

from pixelphilly.projection import area_dir, area_setup, load_config


def test_missing_imagery_is_located():
    from pixelphilly.nodata import missing_tile_boxes

    cfg = load_config("downtown")
    assert len(missing_tile_boxes(cfg)) > 0  # downtown has 350 no-coverage tiles
    assert missing_tile_boxes(load_config("oldcity")) == []


def test_no_generated_content_where_source_imagery_is_missing():
    from pixelphilly.nodata import BACKGROUND, NODATA_MARGIN_PX, nodata_geometry
    from pixelphilly.waterpaint import rasterize_view

    cfg = load_config("downtown")
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    out = area_dir(cfg, "postprocessed", "qwen_joint_light8", "water")
    if not out.exists():
        return  # pipeline outputs not on this machine
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    geom = nodata_geometry(cfg, frame, cam, x_origin, y_origin)
    checked = 0
    for f in frames:
        mask = rasterize_view(geom, f.col * size, f.row * size, 1.0, size, size)
        if mask.sum() < 1000:
            continue
        img = np.asarray(Image.open(out / f"{f.name}.png").convert("RGB"))
        assert (img[mask] == np.array(BACKGROUND, np.uint8)).all(), f"generated content in {f.name}"
        checked += 1
    assert checked > 0, "no frame overlaps the missing imagery; test would be vacuous"
    assert NODATA_MARGIN_PX >= 8
