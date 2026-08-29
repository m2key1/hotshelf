import os

import pytest

from hotshelf.mover import Mover


@pytest.fixture
def branches(tmp_path):
    nvme, hdd = tmp_path / "nvme", tmp_path / "hdd"
    nvme.mkdir()
    hdd.mkdir()
    return str(nvme), str(hdd)


def write(root, relpath, content=b"data"):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def test_promote_moves_file_and_sidecar(branches):
    nvme, hdd = branches
    write(hdd, "tv/show/ep.mkv", b"video")
    write(hdd, "tv/show/ep.en.srt", b"subs")
    write(hdd, "tv/show/other.mkv", b"other")
    Mover(nvme, hdd).promote("tv/show/ep.mkv")
    assert open(os.path.join(nvme, "tv/show/ep.mkv"), "rb").read() == b"video"
    assert os.path.exists(os.path.join(nvme, "tv/show/ep.en.srt"))
    assert not os.path.exists(os.path.join(hdd, "tv/show/ep.mkv"))
    assert os.path.exists(os.path.join(hdd, "tv/show/other.mkv"))


def test_demote_prunes_empty_dirs(branches):
    nvme, hdd = branches
    write(nvme, "tv/show/Season 01/ep.mkv")
    Mover(nvme, hdd).demote("tv/show/Season 01/ep.mkv")
    assert os.path.exists(os.path.join(hdd, "tv/show/Season 01/ep.mkv"))
    assert not os.path.exists(os.path.join(nvme, "tv"))


def test_demote_duplicate_deletes_without_copy(branches):
    nvme, hdd = branches
    write(nvme, "tv/ep.mkv", b"same")
    write(hdd, "tv/ep.mkv", b"same")
    Mover(nvme, hdd).demote("tv/ep.mkv")
    assert not os.path.exists(os.path.join(nvme, "tv/ep.mkv"))
    assert open(os.path.join(hdd, "tv/ep.mkv"), "rb").read() == b"same"


def test_source_kept_on_failure(branches, monkeypatch):
    nvme, hdd = branches
    write(hdd, "tv/ep.mkv", b"video")
    monkeypatch.setattr("hotshelf.mover._checksum", lambda p: os.urandom(8).hex())
    with pytest.raises(OSError):
        Mover(nvme, hdd).promote("tv/ep.mkv")
    assert os.path.exists(os.path.join(hdd, "tv/ep.mkv"))
    assert not os.path.exists(os.path.join(nvme, "tv/ep.mkv"))
    assert not os.path.exists(os.path.join(nvme, "tv/ep.mkv.hotshelf.partial"))


def test_sidecars_disabled(branches):
    nvme, hdd = branches
    write(hdd, "tv/ep.mkv")
    write(hdd, "tv/ep.srt")
    Mover(nvme, hdd, move_sidecars=False).promote("tv/ep.mkv")
    assert os.path.exists(os.path.join(hdd, "tv/ep.srt"))
    assert not os.path.exists(os.path.join(nvme, "tv/ep.srt"))
