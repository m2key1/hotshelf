import threading
import time

from . import metrics
from .jellyfin import Jellyfin
from .library import movie_dirs, scan
from .mover import Mover
from .policy import Episode, Series, Snapshot, desired, plan

run_lock = threading.Lock()


def collect(cfg, pins):
    """Build a policy snapshot from Jellyfin and both branch scans."""
    jf = Jellyfin(cfg["jellyfin"]["url"], cfg["jellyfin"]["api_key"],
                  cfg["jellyfin"]["union_prefix"])
    pol = cfg["policy"]
    users = jf.users(pol["users"])

    resume = []
    activity = {}
    for uid, uname in users:
        for relpath, size, last_played in jf.resume(uid):
            resume.append((relpath, size, uname, last_played))
        for sid, (name, played) in jf.played_series(uid, pol["activity_window_days"]).items():
            current = activity.setdefault(sid, {"name": name, "last": "", "users": []})
            current["last"] = max(current["last"], played)
            current["users"].append((uid, uname))

    pinned_ids = {p["key"] for p in pins if p["kind"] == "series"}
    for sid in pinned_ids - activity.keys():
        activity[sid] = {"name": sid, "last": "", "users": list(users)}

    series_list = []
    for sid, info in activity.items():
        episodes, next_index = _merge_episodes(jf, sid, info["users"])
        if episodes:
            series_list.append(Series(sid, info["name"], episodes, info["last"], next_index))

    nvme_scan = scan(cfg["branches"]["nvme"])
    hdd_scan = scan(cfg["branches"]["hdd"])
    snapshot = Snapshot(
        resume=resume,
        series=series_list,
        movies=movie_dirs(nvme_scan, hdd_scan),
        nvme={rp: s for rp, (s, _) in nvme_scan.items()},
        hdd={rp: s for rp, (s, _) in hdd_scan.items()},
        nvme_mtime={rp: m for rp, (_, m) in nvme_scan.items()},
    )
    _fill_sizes(snapshot)
    return snapshot


def _merge_episodes(jf, series_id, users):
    """Merge per-user episode watch state into shared Episode objects."""
    episodes, order = {}, []
    next_index = {}
    for uid, uname in users:
        rows = jf.episodes(series_id, uid)
        last_watched = -1
        for i, row in enumerate(rows):
            if row["id"] not in episodes:
                episodes[row["id"]] = Episode(row["relpath"], row["size"], row["season"])
                order.append(row["id"])
            ep = episodes[row["id"]]
            ep.last_played = max(ep.last_played, row["last_played"])
            if row["played"]:
                last_watched = i
        if 0 <= last_watched + 1 < len(rows):
            next_index[uname] = last_watched + 1
    return [episodes[eid] for eid in order], next_index


def _fill_sizes(snapshot):
    """Replace unknown Jellyfin sizes with actual branch file sizes."""
    lookup = {**snapshot.hdd, **snapshot.nvme}
    for series in snapshot.series:
        for ep in series.episodes:
            if not ep.size:
                ep.size = lookup.get(ep.relpath, 0)
    snapshot.resume = [
        (rp, size or lookup.get(rp, 0), user, played)
        for rp, size, user, played in snapshot.resume
    ]


def compute(cfg, state):
    """Snapshot, desired set and plan without touching any files."""
    pins = state.pins()
    snapshot = collect(cfg, pins)
    wants = desired(snapshot, cfg, pins)
    promotes, demotes, warnings = plan(wants, snapshot)
    return snapshot, wants, promotes, demotes, warnings


def run(cfg, state):
    """One full policy run; respects dry_run. Returns a summary dict."""
    if not run_lock.acquire(blocking=False):
        return {"skipped": "run already in progress"}
    try:
        return _run(cfg, state)
    finally:
        run_lock.release()


def _run(cfg, state):
    """The actual run body, called under run_lock."""
    dry = cfg["run"]["dry_run"]
    snapshot, wants, promotes, demotes, warnings = compute(cfg, state)
    mover = Mover(cfg["branches"]["nvme"], cfg["branches"]["hdd"],
                  cfg["policy"]["move_sidecars"])
    moved = {"promoted": 0, "demoted": 0, "failed": 0}

    for warning in warnings:
        state.log("warning", detail=warning)
    for want in promotes:
        _execute(state, mover.promote, "promote", want.relpath, want.size, dry, moved)
    for relpath in demotes:
        _execute(state, mover.demote, "demote", relpath, snapshot.nvme[relpath], dry, moved)

    _update_metrics(cfg, snapshot, moved, dry)
    summary = {
        "ts": time.time(), "dry_run": dry, "warnings": warnings, **moved,
        "hot": [{"relpath": w.relpath, "size": w.size, "reason": w.reason,
                 "group": w.group} for w in wants],
        "series": [{"key": s.key, "name": s.name, "last_activity": s.last_activity}
                   for s in snapshot.series],
        "movies": sorted(snapshot.movies),
        "cache_used": sum(snapshot.nvme.values()),
        "cache_items": len(snapshot.nvme),
    }
    state.set_kv("last_run", summary)
    state.log("run", detail=f"promoted={moved['promoted']} demoted={moved['demoted']} "
                            f"failed={moved['failed']} dry_run={dry}")
    return summary


def _execute(state, action, name, relpath, size, dry, moved):
    """Run or simulate one move, logging the outcome."""
    if dry:
        state.log(f"would {name}", relpath, size)
        return
    try:
        action(relpath)
    except OSError as exc:
        moved["failed"] += 1
        metrics.errors.inc()
        state.log(name, relpath, size, ok=False, detail=str(exc))
        return
    moved["promoted" if name == "promote" else "demoted"] += 1
    getattr(metrics, f"{name}s").inc()
    metrics.moved_bytes.inc(size)
    state.log(name, relpath, size)


def _update_metrics(cfg, snapshot, moved, dry):
    metrics.cache_bytes.set(sum(snapshot.nvme.values()))
    metrics.hot_items.set(len(snapshot.nvme))
    metrics.budget_bytes.set(cfg["budget"]["size_gb"] * 10**9)
    metrics.dry_run.set(int(dry))
    metrics.last_run.set(time.time())
