from hotshelf.state import State


def test_pins_roundtrip(tmp_path):
    state = State(str(tmp_path / "s.db"))
    state.add_pin("series", "abc", "Silo", "season")
    state.add_pin("series", "abc", "Silo", "series")
    assert state.pins() == [{"kind": "series", "key": "abc",
                             "name": "Silo", "granularity": "series"}]
    state.remove_pin("series", "abc")
    assert state.pins() == []


def test_log_and_prune(tmp_path):
    state = State(str(tmp_path / "s.db"))
    for i in range(30):
        state.log("promote", f"tv/e{i}.mkv", i)
    assert len(state.log_entries()) == 30
    assert state.log_entries(limit=5)[0]["relpath"] == "tv/e29.mkv"
    state.prune_log(keep=10)
    entries = state.log_entries()
    assert len(entries) == 10
    assert entries[-1]["relpath"] == "tv/e20.mkv"


def test_kv(tmp_path):
    state = State(str(tmp_path / "s.db"))
    assert state.get_kv("missing", {"a": 1}) == {"a": 1}
    state.set_kv("last_run", {"ts": 5})
    assert state.get_kv("last_run") == {"ts": 5}
