"""The training set must never touch the held-out columns used for evaluation."""

import importlib.util
import json

from pixelphilly.projection import REPO_ROOT, area_setup, load_config

spec = importlib.util.spec_from_file_location("trainset", REPO_ROOT / "scripts" / "13_build_trainset.py")
trainset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trainset)


def test_planned_views_stay_out_of_heldout_columns():
    cfg = load_config()
    _, _, frames = area_setup(cfg)
    views = trainset.plan_views(cfg, frames)
    ids = [v[0] for v in views]
    assert len(ids) == len(set(ids)), "duplicate view ids"
    for vid, kind, gx, gy, span in views:
        assert gx >= 0 and gy >= 0
        assert gx + span <= trainset.HELDOUT_X, vid


def test_manifest_targets_record_source_and_stay_out_of_heldout():
    path = REPO_ROOT / "output" / "trainset" / "manifest.jsonl"
    if not path.exists():
        return  # nothing generated yet
    for line in path.read_text().splitlines():
        row = json.loads(line)
        gx, gy, w, h = row["mosaic_xywh"]
        assert gx + w <= trainset.HELDOUT_X, row["id"]
        assert row["target_source"], row["id"]
