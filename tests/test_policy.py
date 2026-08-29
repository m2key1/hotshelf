from datetime import datetime, timezone

from hotshelf.policy import Episode, Series, Snapshot, desired, plan

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)
GB = 10**9

CFG = {
    "policy": {
        "activity_window_days": 30,
        "episodes_ahead": 2,
        "fresh_imports": "keep",
        "fresh_keep_days": 14,
        "watched_grace_days": 7,
        "users": [],
        "move_sidecars": True,
    },
    "budget": {"mode": "size", "size_gb": 100, "max_series": 10, "max_movies": 5},
}


def series(key, n_eps, next_index, last_activity="2026-08-29", season=1):
    eps = [Episode(f"tv/{key}/S01E{i:02d}.mkv", 4 * GB, season) for i in range(n_eps)]
    return Series(key, key, eps, last_activity, next_index)


def test_resume_always_first():
    snap = Snapshot(resume=[("tv/a/S01E00.mkv", 4 * GB, "david")])
    wants = desired(snap, CFG, [], NOW)
    assert [w.relpath for w in wants] == ["tv/a/S01E00.mkv"]
    assert wants[0].reason == "resume"


def test_episodes_ahead():
    snap = Snapshot(series=[series("show", 10, {"david": 3})])
    wants = desired(snap, CFG, [], NOW)
    assert [w.relpath for w in wants] == ["tv/show/S01E03.mkv", "tv/show/S01E04.mkv"]


def test_season_granularity():
    cfg = {**CFG, "policy": {**CFG["policy"], "episodes_ahead": "season"}}
    s = series("show", 6, {"david": 2})
    for ep in s.episodes[4:]:
        ep.season = 2
    wants = desired(Snapshot(series=[s]), cfg, [], NOW)
    assert [w.relpath for w in wants] == ["tv/show/S01E02.mkv", "tv/show/S01E03.mkv"]


def test_two_users_union():
    snap = Snapshot(series=[series("show", 10, {"a": 0, "b": 8})])
    wants = desired(snap, CFG, [], NOW)
    got = [w.relpath for w in wants]
    assert "tv/show/S01E00.mkv" in got and "tv/show/S01E08.mkv" in got
    assert len(got) == 4


def test_inactive_series_excluded():
    snap = Snapshot(series=[series("cold", 10, {"david": 3}, last_activity="")])
    assert desired(snap, CFG, [], NOW) == []


def test_pin_overrides_inactivity_and_granularity():
    snap = Snapshot(series=[series("cold", 4, {"david": 1}, last_activity="")])
    pins = [{"kind": "series", "key": "cold", "granularity": "series"}]
    wants = desired(snap, CFG, pins, NOW)
    assert len(wants) == 3
    assert all(w.reason == "pinned" for w in wants)


def test_watched_grace():
    s = series("show", 5, {"david": 3})
    s.episodes[2].last_played = "2026-08-28T00:00:00+00:00"
    s.episodes[0].last_played = "2026-08-01T00:00:00+00:00"
    wants = desired(Snapshot(series=[s]), CFG, [], NOW)
    got = {w.relpath for w in wants}
    assert "tv/show/S01E02.mkv" in got
    assert "tv/show/S01E00.mkv" not in got


def test_size_budget_trims_by_recency():
    snap = Snapshot(series=[
        series("newer", 4, {"d": 0}, last_activity="2026-08-29"),
        series("older", 4, {"d": 0}, last_activity="2026-08-10"),
    ])
    cfg = {**CFG, "budget": {**CFG["budget"], "size_gb": 10}}
    wants = desired(snap, cfg, [], NOW)
    assert [w.group for w in wants] == ["newer", "newer"]


def test_resume_never_trimmed():
    snap = Snapshot(resume=[("tv/a/big.mkv", 500 * GB, "d")])
    cfg = {**CFG, "budget": {**CFG["budget"], "size_gb": 10}}
    assert len(desired(snap, cfg, [], NOW)) == 1


def test_count_budget():
    snap = Snapshot(series=[
        series("s1", 4, {"d": 0}, last_activity="2026-08-29"),
        series("s2", 4, {"d": 0}, last_activity="2026-08-28"),
        series("s3", 4, {"d": 0}, last_activity="2026-08-27"),
    ])
    cfg = {**CFG, "budget": {**CFG["budget"], "mode": "count", "max_series": 2}}
    groups = {w.group for w in desired(snap, cfg, [], NOW)}
    assert groups == {"s1", "s2"}


def test_fresh_keep_and_expiry():
    snap = Snapshot(
        nvme={"tv/x/new.mkv": GB, "tv/x/old.mkv": GB},
        nvme_mtime={"tv/x/new.mkv": NOW.timestamp() - 86400,
                    "tv/x/old.mkv": NOW.timestamp() - 30 * 86400},
    )
    wants = desired(snap, CFG, [], NOW)
    assert [w.relpath for w in wants] == ["tv/x/new.mkv"]
    cfg = {**CFG, "policy": {**CFG["policy"], "fresh_imports": "demote"}}
    assert desired(snap, cfg, [], NOW) == []


def test_plan_promote_demote_conflict():
    s = series("show", 4, {"d": 0})
    snap = Snapshot(
        series=[s],
        nvme={"tv/stale.mkv": GB, "tv/dup.mkv": GB, "tv/show/S01E00.mkv": 4 * GB},
        hdd={"tv/show/S01E01.mkv": 4 * GB, "tv/dup.mkv": 2 * GB},
    )
    wants = desired(snap, CFG, [], NOW)
    promotes, demotes, warnings = plan(wants, snap)
    assert [w.relpath for w in promotes] == ["tv/show/S01E01.mkv"]
    assert demotes == ["tv/stale.mkv"]
    assert any("size mismatch" in w for w in warnings)


def test_plan_missing_file_warns():
    s = series("ghost", 2, {"d": 0})
    snap = Snapshot(series=[s])
    wants = desired(snap, CFG, [], NOW)
    promotes, demotes, warnings = plan(wants, snap)
    assert promotes == [] and demotes == []
    assert len(warnings) == 2
