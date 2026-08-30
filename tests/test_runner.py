from hotshelf.policy import Episode, Series, Snapshot
from hotshelf.runner import _execute, _fill_sizes, _merge_episodes


class FakeJellyfin:
    def __init__(self, rows_by_user):
        self.rows_by_user = rows_by_user

    def episodes(self, series_id, user_id):
        return self.rows_by_user[user_id]


def row(i, played, last_played=""):
    return {"id": f"ep{i}", "relpath": f"tv/s/E{i}.mkv", "size": 100,
            "season": 1, "played": played, "last_played": last_played}


def test_merge_episodes_two_users():
    jf = FakeJellyfin({
        "u1": [row(0, True, "2026-08-01"), row(1, False), row(2, False)],
        "u2": [row(0, True, "2026-08-20"), row(1, True, "2026-08-21"), row(2, False)],
    })
    episodes, next_index = _merge_episodes(jf, "sid", [("u1", "alice"), ("u2", "bob")])
    assert [e.relpath for e in episodes] == ["tv/s/E0.mkv", "tv/s/E1.mkv", "tv/s/E2.mkv"]
    assert next_index == {"alice": 1, "bob": 2}
    assert episodes[0].last_played == "2026-08-20"


def test_merge_episodes_fully_watched_user_has_no_next():
    jf = FakeJellyfin({"u1": [row(0, True), row(1, True)]})
    _, next_index = _merge_episodes(jf, "sid", [("u1", "alice")])
    assert next_index == {}


def test_fill_sizes_from_branches():
    series = Series("k", "n", [Episode("tv/a.mkv", 0, 1)])
    snap = Snapshot(series=[series], resume=[("tv/b.mkv", 0, "u", "")],
                    slow={"tv/a.mkv": 111, "tv/b.mkv": 222})
    _fill_sizes(snap)
    assert series.episodes[0].size == 111
    assert snap.resume[0][1] == 222


class FakeState:
    def __init__(self):
        self.entries = []

    def log(self, action, relpath="", size=0, ok=True, detail=""):
        self.entries.append((action, relpath, ok))


def test_execute_dry_run_moves_nothing():
    state, moved = FakeState(), {"promoted": 0, "demoted": 0, "failed": 0}
    _execute(state, lambda rp: 1 / 0, "promote", "tv/x.mkv", 5, True, moved)
    assert state.entries == [("would promote", "tv/x.mkv", True)]
    assert moved == {"promoted": 0, "demoted": 0, "failed": 0}


def test_execute_counts_failure():
    state, moved = FakeState(), {"promoted": 0, "demoted": 0, "failed": 0}

    def boom(relpath):
        raise OSError("disk gone")

    _execute(state, boom, "promote", "tv/x.mkv", 5, False, moved)
    assert moved["failed"] == 1
    assert state.entries[0][2] is False


def test_desired_accepts_config_object(tmp_path):
    from hotshelf.config import Config
    from hotshelf.policy import desired

    (tmp_path / "c.yaml").write_text("")
    cfg = Config(str(tmp_path / "c.yaml"))
    assert desired(Snapshot(), cfg, []) == []


def test_move_window():
    from datetime import datetime

    from hotshelf.runner import in_move_window

    def cfg(enabled, start="02:00", end="07:00"):
        return {"run": {"move_window_enabled": enabled,
                        "move_window_start": start, "move_window_end": end}}

    at = lambda h, m: datetime(2026, 8, 30, h, m)
    assert in_move_window(cfg(False), at(12, 0))
    assert in_move_window(cfg(True), at(3, 30))
    assert not in_move_window(cfg(True), at(12, 0))
    assert not in_move_window(cfg(True), at(7, 0))
    assert in_move_window(cfg(True, "22:00", "06:00"), at(23, 30))
    assert in_move_window(cfg(True, "22:00", "06:00"), at(2, 0))
    assert not in_move_window(cfg(True, "22:00", "06:00"), at(12, 0))
