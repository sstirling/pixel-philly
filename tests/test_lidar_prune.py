"""Deleting raw LiDAR tiles once every area that needs them has a cached
height grid (scripts/04m_prune_lidar.py, pixelphilly.lidar_tiles).

Fake tile lists, fake tiles of a few bytes and fake grids; nothing real is
touched."""

import json

import numpy as np
import pytest

from pixelphilly.lidar_tiles import apply_prune, grid_valid, las_url, plan_prune

LIDAR_CFG = {"building_shapes": "lidar"}
PLAIN_CFG = {}


@pytest.fixture
def tree(tmp_path):
    """data/raw/lidar and data/processed in a temp dir, with helpers."""
    lidar = tmp_path / "raw" / "lidar"
    processed = tmp_path / "processed"
    lidar.mkdir(parents=True)
    processed.mkdir()

    class T:
        pass

    t = T()
    t.lidar, t.processed, t.manifest = lidar, processed, tmp_path / "raw" / "MANIFEST.json"

    def tile(name, nbytes=10):
        (lidar / name).write_bytes(b"x" * nbytes)

    def lists(area, names):
        (lidar / f"{area}_tiles.txt").write_text("\n".join(names) + "\n")

    def grid(area, struct=True):
        arrays = {"dsm": np.zeros((2, 2)), "ground": np.zeros((2, 2)), "origin": np.zeros(2)}
        if struct:
            arrays["struct"] = np.zeros((2, 2))
        np.savez_compressed(processed / f"{area}_lidar_grid.npz", **arrays)

    t.tile, t.lists, t.grid = tile, lists, grid
    return t


def _plan(t, configs, extra_needs=None):
    return {p["tile"]: p for p in plan_prune(t.lidar, t.processed, configs, extra_needs or {})}


def test_grid_needs_struct(tree):
    tree.grid("a", struct=True)
    tree.grid("b", struct=False)
    (tree.processed / "c_lidar_grid.npz").write_bytes(b"not a zip")
    assert grid_valid(tree.processed / "a_lidar_grid.npz")
    assert not grid_valid(tree.processed / "b_lidar_grid.npz")  # 05 would regrid from LAS
    assert not grid_valid(tree.processed / "c_lidar_grid.npz")
    assert not grid_valid(tree.processed / "missing_lidar_grid.npz")


def test_tile_shared_by_two_gridded_areas_is_deleted(tree):
    tree.tile("Philadelphia_1.las", 100)
    tree.lists("a", ["Philadelphia_1.las"])
    tree.lists("b", ["Philadelphia_1.las"])
    tree.grid("a")
    tree.grid("b")
    p = _plan(tree, {"a": LIDAR_CFG, "b": LIDAR_CFG})["Philadelphia_1.las"]
    assert p["delete"] and p["bytes"] == 100 and p["blockers"] == []
    assert p["areas"] == ["a", "b"]


@pytest.mark.parametrize("case,reason", [
    ("no_grid", "no valid grid"),
    ("grid_without_struct", "no valid grid"),
    ("not_lidar", "not a LiDAR config"),
    ("no_config", "no config"),
])
def test_one_unready_area_keeps_a_shared_tile(tree, case, reason):
    tree.tile("Philadelphia_1.las")
    tree.lists("done", ["Philadelphia_1.las"])
    tree.lists("other", ["Philadelphia_1.las"])
    tree.grid("done")
    configs = {"done": LIDAR_CFG, "other": LIDAR_CFG}
    if case == "grid_without_struct":
        tree.grid("other", struct=False)
    elif case == "not_lidar":
        tree.grid("other")
        configs["other"] = PLAIN_CFG
    elif case == "no_config":
        tree.grid("other")
        del configs["other"]
    p = _plan(tree, configs)["Philadelphia_1.las"]
    assert not p["delete"]
    assert p["blockers"] == [{"area": "other", "reason": reason}]


def test_tile_in_no_list_is_kept(tree):
    tree.tile("Philadelphia_9.las")
    p = _plan(tree, {})["Philadelphia_9.las"]
    assert not p["delete"] and p["blockers"][0]["reason"] == "in no tile list"


def test_area_without_a_list_yet_keeps_the_tiles_it_will_need(tree):
    # A new region (no 04c run yet, no grid) whose box covers tile 1
    tree.tile("Philadelphia_1.las")
    tree.tile("Philadelphia_2.las")
    tree.lists("a", ["Philadelphia_1.las", "Philadelphia_2.las"])
    tree.grid("a")
    plan = _plan(tree, {"a": LIDAR_CFG, "new": LIDAR_CFG}, extra_needs={"new": ["Philadelphia_1.las"]})
    assert not plan["Philadelphia_1.las"]["delete"]
    assert plan["Philadelphia_1.las"]["blockers"] == [{"area": "new", "reason": "needed, no grid yet (no tile list)"}]
    assert plan["Philadelphia_2.las"]["delete"]


def test_listed_tiles_not_on_disk_are_ignored(tree):
    tree.lists("a", ["Philadelphia_1.las"])
    tree.grid("a")
    assert _plan(tree, {"a": LIDAR_CFG}) == {}


def test_dry_run_changes_nothing_and_apply_records_the_deletions(tree):
    tree.tile("Philadelphia_1.las", 100)
    tree.tile("Philadelphia_2.las", 50)
    tree.lists("a", ["Philadelphia_1.las"])
    tree.lists("b", ["Philadelphia_2.las"])
    tree.grid("a")
    tree.manifest.write_text(json.dumps({"other.geojson": {"feature_count": 3},
                                         "lidar/Philadelphia_1.las": {"url": "u", "bytes": 100}}))
    plan = plan_prune(tree.lidar, tree.processed, {"a": LIDAR_CFG, "b": LIDAR_CFG}, {})
    before = tree.manifest.read_text()
    out = apply_prune(plan, tree.lidar, tree.manifest, dry_run=True)
    assert out["deleted"] == [] and out["would_delete"] == ["Philadelphia_1.las"] and out["would_free_bytes"] == 100
    assert (tree.lidar / "Philadelphia_1.las").exists() and tree.manifest.read_text() == before

    out = apply_prune(plan, tree.lidar, tree.manifest, dry_run=False)
    assert out["deleted"] == ["Philadelphia_1.las"] and out["freed_bytes"] == 100
    assert not (tree.lidar / "Philadelphia_1.las").exists()
    assert (tree.lidar / "Philadelphia_2.las").exists()
    m = json.loads(tree.manifest.read_text())
    assert m["other.geojson"] == {"feature_count": 3}
    e = m["lidar/Philadelphia_1.las"]
    assert e["path"] == "data/raw/lidar/Philadelphia_1.las" and e["bytes"] == 100
    assert e["url"] == las_url("Philadelphia_1.las") and e["deleted_at"]
    assert e["grids"] == ["a"]
    assert "lidar/Philadelphia_2.las" not in m


def test_apply_rechecks_grids_before_deleting(tree):
    # A grid that disappears between planning and applying blocks deletion
    tree.tile("Philadelphia_1.las")
    tree.lists("a", ["Philadelphia_1.las"])
    tree.grid("a")
    plan = plan_prune(tree.lidar, tree.processed, {"a": LIDAR_CFG}, {})
    (tree.processed / "a_lidar_grid.npz").unlink()
    out = apply_prune(plan, tree.lidar, tree.manifest, dry_run=False)
    assert out["deleted"] == [] and (tree.lidar / "Philadelphia_1.las").exists()


def test_las_url_is_04c_download_url():
    assert las_url("Philadelphia_455.las") == (
        "https://www.pasda.psu.edu/download/phillyLiDAR/2022/LAS/Classified_LAS/Philadelphia_455.las")
