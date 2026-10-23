"""Which scene files make up an area.

Small areas have one scene (data/processed/<area>_scene.json). Areas whose
aerial would exceed the GPU texture limit are split into render tiles, each
with its own scene, listed in data/processed/<area>_tiles.json (written by
scripts/05_build_scene.py). Renderers and checks just loop over these.
"""

import json

from .projection import REPO_ROOT


def scene_paths(cfg: dict) -> list[str]:
    """Scene files relative to the repo root (the renderer's web root)."""
    name = cfg["name"]
    if cfg.get("render_tile_frames"):
        index = json.loads((REPO_ROOT / "data" / "processed" / f"{name}_tiles.json").read_text())
        return [t["scene"] for t in index]
    return [f"data/processed/{name}_scene.json"]
