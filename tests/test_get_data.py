"""scripts/00_get_data.py: unpack the raw-data snapshot safely.

The snapshot replaces the raw files that used to be tracked in git, so it must
reproduce them exactly and must never overwrite a raw file that differs
(raw data is immutable)."""

import hashlib
import importlib.util
import io
import tarfile

import pytest

from pixelphilly.projection import REPO_ROOT

_spec = importlib.util.spec_from_file_location("get_data", REPO_ROOT / "scripts" / "00_get_data.py")
gd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gd)

FILES = {"a_buildings.geojson": b'{"type": "FeatureCollection"}', "b_trees.geojson": b"[1, 2, 3]"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_archive(path, files):
    with tarfile.open(path, "w:xz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def write_sums(path, files):
    path.write_text("".join(f"{sha(d)}  {n}\n" for n, d in files.items()))
    return path


@pytest.fixture
def snap(tmp_path):
    arc = make_archive(tmp_path / "snap.tar.xz", FILES)
    sums = write_sums(tmp_path / "SHA256SUMS", FILES)
    dest = tmp_path / "raw"
    dest.mkdir()
    return arc, sums, dest


def test_extracts_every_file_exactly(snap):
    arc, sums, dest = snap
    n = gd.install(arc, dest, gd.read_sums(sums), expected_archive_sha=gd.sha256_file(arc))
    assert n == 2
    for name, data in FILES.items():
        assert (dest / name).read_bytes() == data


def test_rejects_archive_with_wrong_checksum(snap):
    arc, sums, dest = snap
    with pytest.raises(gd.GetDataError, match="archive checksum"):
        gd.install(arc, dest, gd.read_sums(sums), expected_archive_sha="0" * 64)
    assert not any(dest.iterdir())


def test_never_overwrites_a_differing_raw_file(snap):
    arc, sums, dest = snap
    (dest / "a_buildings.geojson").write_bytes(b"something else")
    with pytest.raises(gd.GetDataError, match="differs"):
        gd.install(arc, dest, gd.read_sums(sums))
    assert (dest / "a_buildings.geojson").read_bytes() == b"something else"
    assert not (dest / "b_trees.geojson").exists()  # nothing moved in after a refusal


def test_identical_existing_file_is_kept(snap):
    arc, sums, dest = snap
    (dest / "a_buildings.geojson").write_bytes(FILES["a_buildings.geojson"])
    assert gd.install(arc, dest, gd.read_sums(sums)) == 1  # only the missing file is added


def test_rejects_file_not_in_checksum_list(tmp_path):
    files = dict(FILES, **{"extra.json": b"{}"})
    arc = make_archive(tmp_path / "snap.tar.xz", files)
    sums = write_sums(tmp_path / "SHA256SUMS", FILES)
    (tmp_path / "raw").mkdir()
    with pytest.raises(gd.GetDataError, match="not in SHA256SUMS"):
        gd.install(arc, tmp_path / "raw", gd.read_sums(sums))


def test_rejects_content_that_fails_its_checksum(tmp_path):
    arc = make_archive(tmp_path / "snap.tar.xz", FILES)
    sums = write_sums(tmp_path / "SHA256SUMS", dict(FILES, **{"b_trees.geojson": b"other"}))
    (tmp_path / "raw").mkdir()
    with pytest.raises(gd.GetDataError, match="checksum"):
        gd.install(arc, tmp_path / "raw", gd.read_sums(sums))


def test_blocks_path_traversal(tmp_path):
    files = {"../escape.txt": b"x"}
    arc = make_archive(tmp_path / "snap.tar.xz", files)
    sums = write_sums(tmp_path / "SHA256SUMS", files)
    (tmp_path / "raw").mkdir()
    with pytest.raises(gd.GetDataError):
        gd.install(arc, tmp_path / "raw", gd.read_sums(sums))
    assert not (tmp_path / "escape.txt").exists()


def test_missing_files_are_reported(tmp_path):
    arc = make_archive(tmp_path / "snap.tar.xz", {"a_buildings.geojson": FILES["a_buildings.geojson"]})
    sums = write_sums(tmp_path / "SHA256SUMS", FILES)
    (tmp_path / "raw").mkdir()
    with pytest.raises(gd.GetDataError, match="missing"):
        gd.install(arc, tmp_path / "raw", gd.read_sums(sums))
