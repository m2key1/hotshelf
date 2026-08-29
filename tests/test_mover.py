import os

import pytest

from hotshelf.mover import Mover


@pytest.fixture
def branches(tmp_path):
    fast_dir, slow_dir = tmp_path / "fast", tmp_path / "slow"
    fast_dir.mkdir()
    slow_dir.mkdir()
    return str(fast_dir), str(slow_dir)


def write(root, relpath, content=b"data"):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def test_promote_moves_file_and_sidecar(branches):
    fast_dir, slow_dir = branches
    write(slow_dir, "tv/show/ep.mkv", b"video")
    write(slow_dir, "tv/show/ep.en.srt", b"subs")
    write(slow_dir, "tv/show/other.mkv", b"other")
    Mover(fast_dir, slow_dir).promote("tv/show/ep.mkv")
    assert open(os.path.join(fast_dir, "tv/show/ep.mkv"), "rb").read() == b"video"
    assert os.path.exists(os.path.join(fast_dir, "tv/show/ep.en.srt"))
    assert not os.path.exists(os.path.join(slow_dir, "tv/show/ep.mkv"))
    assert os.path.exists(os.path.join(slow_dir, "tv/show/other.mkv"))


def test_demote_prunes_empty_dirs(branches):
    fast_dir, slow_dir = branches
    write(fast_dir, "tv/show/Season 01/ep.mkv")
    Mover(fast_dir, slow_dir).demote("tv/show/Season 01/ep.mkv")
    assert os.path.exists(os.path.join(slow_dir, "tv/show/Season 01/ep.mkv"))
    assert not os.path.exists(os.path.join(fast_dir, "tv"))


def test_demote_duplicate_deletes_without_copy(branches):
    fast_dir, slow_dir = branches
    write(fast_dir, "tv/ep.mkv", b"same")
    write(slow_dir, "tv/ep.mkv", b"same")
    Mover(fast_dir, slow_dir).demote("tv/ep.mkv")
    assert not os.path.exists(os.path.join(fast_dir, "tv/ep.mkv"))
    assert open(os.path.join(slow_dir, "tv/ep.mkv"), "rb").read() == b"same"


def test_source_kept_on_failure(branches, monkeypatch):
    fast_dir, slow_dir = branches
    write(slow_dir, "tv/ep.mkv", b"video")
    monkeypatch.setattr("hotshelf.mover._checksum", lambda p: os.urandom(8).hex())
    with pytest.raises(OSError):
        Mover(fast_dir, slow_dir).promote("tv/ep.mkv")
    assert os.path.exists(os.path.join(slow_dir, "tv/ep.mkv"))
    assert not os.path.exists(os.path.join(fast_dir, "tv/ep.mkv"))
    assert not os.path.exists(os.path.join(fast_dir, "tv/ep.mkv.hotshelf.partial"))


def test_sidecars_disabled(branches):
    fast_dir, slow_dir = branches
    write(slow_dir, "tv/ep.mkv")
    write(slow_dir, "tv/ep.srt")
    Mover(fast_dir, slow_dir, move_sidecars=False).promote("tv/ep.mkv")
    assert os.path.exists(os.path.join(slow_dir, "tv/ep.srt"))
    assert not os.path.exists(os.path.join(fast_dir, "tv/ep.srt"))
