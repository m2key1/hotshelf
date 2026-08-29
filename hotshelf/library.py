import os

from .policy import PARTIAL_SUFFIX

def scan(root, video_exts):
    """Map of relpath -> (size, mtime) for all video files under root."""
    exts = {e.lower() for e in video_exts}
    out = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in exts or name.endswith(PARTIAL_SUFFIX):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            out[os.path.relpath(path, root)] = (stat.st_size, stat.st_mtime)
    return out


def movie_dirs(movies_dir, *scans):
    """Group movie files across branch scans: movie dir -> {relpath: size}."""
    movies = {}
    for entries in scans:
        for relpath, (size, _) in entries.items():
            parts = relpath.split(os.sep)
            if parts[0] == movies_dir and len(parts) > 1:
                movies.setdefault(os.sep.join(parts[:2]), {})[relpath] = size
    return movies
