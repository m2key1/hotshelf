import os

from .policy import PARTIAL_SUFFIX

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".webm", ".mov", ".wmv"}


def scan(root):
    """Map of relpath -> (size, mtime) for all video files under root."""
    out = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTS or name.endswith(PARTIAL_SUFFIX):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            out[os.path.relpath(path, root)] = (stat.st_size, stat.st_mtime)
    return out


def movie_dirs(*scans):
    """Group movie files across branch scans: movie dir -> {relpath: size}."""
    movies = {}
    for entries in scans:
        for relpath, (size, _) in entries.items():
            parts = relpath.split(os.sep)
            if parts[0] == "movies" and len(parts) > 1:
                movies.setdefault(os.sep.join(parts[:2]), {})[relpath] = size
    return movies
