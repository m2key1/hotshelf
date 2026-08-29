import copy
import os

import yaml

DEFAULTS = {
    "jellyfin": {"url": "http://jellyfin:8096", "api_key": "", "union_prefix": "/data/media"},
    "branches": {"nvme": "/branches/nvme", "hdd": "/branches/hdd"},
    "library": {
        "movies_dir": "movies",
        "video_exts": [".mkv", ".mp4", ".avi", ".m4v", ".ts", ".webm", ".mov", ".wmv"],
    },
    "mover": {"verify": "checksum", "free_space_margin_gb": 1},
    "budget": {"mode": "size", "size_gb": 150, "max_series": 10, "max_movies": 5},
    "policy": {
        "activity_window_days": 30,
        "episodes_ahead": 3,
        "resume": "recent",
        "fresh_imports": "keep",
        "fresh_keep_days": 14,
        "watched_grace_days": 7,
        "users": [],
        "move_sidecars": True,
    },
    "run": {"interval_minutes": 15, "dry_run": True,
            "webhook_debounce_minutes": 5, "log_keep": 5000},
}


def _merge(base, override):
    """Deep-merge override into a copy of base."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Loads, validates and persists the single YAML config file."""

    def __init__(self, path):
        self.path = path
        self.data = DEFAULTS
        self.reload()

    def reload(self):
        loaded = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                loaded = yaml.safe_load(f) or {}
        self.data = _merge(DEFAULTS, loaded)
        key = os.environ.get("HOTSHELF_JELLYFIN_KEY")
        if key:
            self.data["jellyfin"]["api_key"] = key
        self.validate(self.data)

    @staticmethod
    def validate(data):
        if data["budget"]["mode"] not in ("size", "count"):
            raise ValueError("budget.mode must be size or count")
        if data["policy"]["fresh_imports"] not in ("keep", "demote"):
            raise ValueError("policy.fresh_imports must be keep or demote")
        if data["policy"]["resume"] not in ("recent", "always", "off"):
            raise ValueError("policy.resume must be recent, always or off")
        if data["mover"]["verify"] not in ("checksum", "size"):
            raise ValueError("mover.verify must be checksum or size")
        ahead = data["policy"]["episodes_ahead"]
        if not (ahead in ("season", "series") or isinstance(ahead, int) and ahead > 0):
            raise ValueError("policy.episodes_ahead must be a positive int, season or series")
        for section in DEFAULTS:
            if not isinstance(data.get(section), dict):
                raise ValueError(f"missing section: {section}")

    def save(self, text):
        parsed = yaml.safe_load(text) or {}
        self.validate(_merge(DEFAULTS, parsed))
        with open(self.path, "w") as f:
            f.write(text)
        self.reload()

    def raw(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                return f.read()
        return yaml.safe_dump(DEFAULTS, sort_keys=False)

    def __getitem__(self, key):
        return self.data[key]
