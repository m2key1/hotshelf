from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

PRIORITY_RESUME = 0
PRIORITY_PINNED = 1
PRIORITY_ACTIVE = 2
PRIORITY_FRESH = 3

REASON = {
    PRIORITY_RESUME: "resume",
    PRIORITY_PINNED: "pinned",
    PRIORITY_ACTIVE: "active series",
    PRIORITY_FRESH: "fresh import",
}

PARTIAL_SUFFIX = ".hotshelf.partial"


@dataclass(frozen=True)
class Want:
    relpath: str
    size: int
    priority: int
    reason: str
    group: str = ""


@dataclass
class Episode:
    relpath: str
    size: int
    season: int
    last_played: str = ""


@dataclass
class Series:
    key: str
    name: str
    episodes: list
    last_activity: str = ""
    next_index: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    resume: list = field(default_factory=list)
    series: list = field(default_factory=list)
    movies: dict = field(default_factory=dict)
    fast: dict = field(default_factory=dict)
    slow: dict = field(default_factory=dict)
    fast_mtime: dict = field(default_factory=dict)


def _episode_indices(series, granularity):
    """Indices of episodes to keep hot for one series under a granularity."""
    indices = set()
    starts = series.next_index.values() or [0]
    for start in starts:
        if start >= len(series.episodes):
            continue
        if granularity == "series":
            indices.update(range(start, len(series.episodes)))
        elif granularity == "season":
            season = series.episodes[start].season
            indices.update(
                i for i in range(start, len(series.episodes))
                if series.episodes[i].season == season
            )
        else:
            indices.update(range(start, min(start + int(granularity), len(series.episodes))))
    return sorted(indices)


def _series_wants(series, priority, granularity, grace_cutoff):
    """Wants for one series: upcoming episodes plus recently watched ones."""
    wants = []
    for i in _episode_indices(series, granularity):
        ep = series.episodes[i]
        wants.append(Want(ep.relpath, ep.size, priority, REASON[priority], series.name))
    for ep in series.episodes:
        if ep.last_played and ep.last_played >= grace_cutoff:
            wants.append(Want(ep.relpath, ep.size, priority, "watched recently", series.name))
    return wants


def desired(snapshot, cfg, pins, now=None):
    """Ordered hot set trimmed to budget; resume items are never trimmed."""
    now = now or datetime.now(timezone.utc)
    pol = cfg["policy"]
    grace_cutoff = (now - timedelta(days=pol["watched_grace_days"])).isoformat()
    pinned_series = {p["key"]: p for p in pins if p["kind"] == "series"}
    pinned_movies = [p["key"] for p in pins if p["kind"] == "movie"]

    seen = set()
    resume, rest = [], []

    def add(target, wants):
        for w in wants:
            if w.relpath not in seen:
                seen.add(w.relpath)
                target.append(w)

    resume_mode = pol["resume"]
    window_cutoff = (now - timedelta(days=pol["activity_window_days"])).isoformat()
    for relpath, size, user, last_played in snapshot.resume:
        if resume_mode == "off":
            break
        if resume_mode == "recent" and (not last_played or last_played < window_cutoff):
            continue
        add(resume, [Want(relpath, size, PRIORITY_RESUME, REASON[PRIORITY_RESUME], user)])

    for series in snapshot.series:
        pin = pinned_series.get(series.key)
        if pin:
            granularity = pin.get("granularity") or pol["episodes_ahead"]
            add(rest, _series_wants(series, PRIORITY_PINNED, granularity, grace_cutoff))
    for movie_dir in pinned_movies:
        files = snapshot.movies.get(movie_dir, {})
        add(rest, [Want(rp, sz, PRIORITY_PINNED, REASON[PRIORITY_PINNED], movie_dir)
                   for rp, sz in sorted(files.items())])

    active = [s for s in snapshot.series if s.last_activity and s.key not in pinned_series]
    active.sort(key=lambda s: s.last_activity, reverse=True)
    for series in active:
        add(rest, _series_wants(series, PRIORITY_ACTIVE, pol["episodes_ahead"], grace_cutoff))

    if pol["fresh_imports"] == "keep":
        fresh_cutoff = (now - timedelta(days=pol["fresh_keep_days"])).timestamp()
        for relpath, mtime in sorted(snapshot.fast_mtime.items()):
            if mtime >= fresh_cutoff and relpath in snapshot.fast:
                add(rest, [Want(relpath, snapshot.fast[relpath], PRIORITY_FRESH,
                                REASON[PRIORITY_FRESH])])

    budget = {**cfg["budget"],
              "movies_dir": cfg.get("library", {}).get("movies_dir", "movies")}
    return resume + _trim(rest, budget, sum(w.size for w in resume))


def _trim(wants, budget, used):
    """Cut the non-resume wants down to the configured budget."""
    if budget["mode"] == "size":
        limit = budget["size_gb"] * 10**9
        if not limit:
            return list(wants)
        kept = []
        for w in wants:
            if used + w.size > limit:
                continue
            used += w.size
            kept.append(w)
        return kept
    limit = budget["max_titles"]
    titles, kept = [], []
    for w in wants:
        title = w.group or "/".join(w.relpath.split("/")[:2])
        if title not in titles:
            if limit and len(titles) >= limit:
                continue
            titles.append(title)
        kept.append(w)
    return kept


def plan(wants, snapshot):
    """Split desired state into promotes, demotes and conflict warnings."""
    desired_paths = {w.relpath for w in wants}
    warnings = []
    skip = set()
    for relpath in sorted(desired_paths - snapshot.fast.keys() - snapshot.slow.keys()):
        warnings.append(f"not found in any branch: {relpath}")
        skip.add(relpath)
    for relpath in sorted(snapshot.fast.keys() & snapshot.slow.keys()):
        if snapshot.fast[relpath] != snapshot.slow[relpath]:
            warnings.append(f"size mismatch between branches, skipped: {relpath}")
            skip.add(relpath)

    promotes = [w for w in wants
                if w.relpath in snapshot.slow
                and w.relpath not in snapshot.fast
                and w.relpath not in skip]
    demotes = sorted(
        relpath for relpath in snapshot.fast
        if relpath not in desired_paths
        and relpath not in skip
        and not relpath.endswith(PARTIAL_SUFFIX)
    )
    return promotes, demotes, warnings
