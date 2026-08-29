import pytest
from fastapi.testclient import TestClient

from hotshelf.web.app import app, cfg, state


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


SETTINGS = {
    "budget_mode": "size", "size_gb": "120", "max_series": "8", "max_movies": "3",
    "activity_window_days": "21", "episodes_ahead": "season", "resume": "recent",
    "fresh_imports": "keep", "fresh_keep_days": "10", "watched_grace_days": "5",
    "users": "M2key1, Villach", "interval_minutes": "30",
    "webhook_debounce_minutes": "5", "log_keep": "5000", "dry_run": "on",
    "jellyfin_url": "http://jellyfin:8096", "union_prefix": "/data/media",
    "movies_dir": "movies", "video_exts": ".mkv, mp4",
    "verify": "size", "free_space_margin_gb": "2",
}


def seed_last_run():
    state.set_kv("last_run", {
        "ts": 1756480000.0, "dry_run": True, "cache_used": 48_000_000_000,
        "cache_items": 12, "warnings": [],
        "hot": [{"relpath": "tv/Silo/S03E09.mkv", "size": 4_000_000_000,
                 "reason": "active series", "group": "Silo", "tier": "fast"}],
        "series": [{"key": "abc", "name": "Silo", "last_activity": "2026-08-29"}],
        "movies": ["movies/Dune (2021)"],
    })


def test_pages_render(client):
    seed_last_run()
    for path in ("/", "/pins", "/config", "/log", "/metrics", "/api/homepage"):
        assert client.get(path).status_code == 200


def test_settings_roundtrip(client):
    r = client.post("/settings", data={**SETTINGS, "api_key": "k123"})
    assert "Saved" in r.text
    assert cfg["budget"]["size_gb"] == 120
    assert cfg["policy"]["episodes_ahead"] == "season"
    assert cfg["library"]["video_exts"] == [".mkv", ".mp4"]
    assert cfg["jellyfin"]["api_key"] == "k123"

    r = client.post("/settings", data={**SETTINGS, "episodes_ahead": "3", "size_gb": "0"})
    assert cfg["jellyfin"]["api_key"] == "k123", "blank key must not overwrite"
    assert cfg["budget"]["size_gb"] == 0
    assert cfg["policy"]["episodes_ahead"] == 3


def test_settings_invalid_rejected(client):
    r = client.post("/settings", data={**SETTINGS, "verify": "bogus"})
    assert "must be checksum or size" in r.text


def test_raw_config_invalid_rejected(client):
    r = client.post("/config", data={"raw": "budget:\n  mode: bogus\n"})
    assert "must be size or count" in r.text


def test_pins_add_remove(client):
    client.post("/pins/add", data={"kind": "series", "key": "abc",
                                   "name": "Silo", "granularity": "season"})
    assert "Silo" in client.get("/pins").text
    client.post("/pins/remove", data={"kind": "series", "key": "abc"})
    assert "Nothing pinned" in client.get("/pins").text


def test_homepage_widget(client):
    seed_last_run()
    client.post("/settings", data={**SETTINGS, "size_gb": "120"})
    data = client.get("/api/homepage").json()
    assert data["used_gb"] == 48.0
    assert data["budget_gb"] == 120
    assert data["hot_items"] == 12


def test_webhook_accepts_garbage(client):
    assert client.post("/webhook/jellyfin", content=b"not json").json() == {"ok": True}


def test_flush_dry_run_logs_only(client, tmp_path):
    import yaml
    data = yaml.safe_load(cfg.raw())
    fast_dir = data["branches"]["fast"]
    (tmp_path / "dummy").mkdir()
    with open(f"{fast_dir}/flushme.mkv", "wb") as f:
        f.write(b"x" * 10)
    client.post("/settings", data={**SETTINGS, "dry_run": "on"})
    r = client.post("/flush", follow_redirects=False)
    assert r.status_code == 303
    entries = state.log_entries(limit=10)
    assert any(e["action"] == "would demote" and "flushme" in e["relpath"]
               for e in entries)


def test_localts_renders_local_time(monkeypatch):
    from hotshelf.web import app as webapp
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(webapp, "LOCAL_TZ", ZoneInfo("Europe/Vienna"))
    assert webapp._localts("2026-08-29T19:50:00+00:00") == "2026-08-29 21:50:00"
    assert webapp._localts("garbage") == "garbage"
