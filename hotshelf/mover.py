import hashlib
import os
import shutil

from .policy import PARTIAL_SUFFIX

CHUNK = 1 << 20


def _checksum(path):
    digest = hashlib.blake2b()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecars(src_dir, stem):
    """Non-media files in src_dir sharing the media file's stem."""
    try:
        entries = os.listdir(src_dir)
    except FileNotFoundError:
        return []
    return sorted(e for e in entries
                  if e.startswith(stem + ".") and not e.endswith(PARTIAL_SUFFIX))


def _copy_verified(src, dst):
    """Copy src to dst atomically, verifying size and checksum."""
    partial = dst + PARTIAL_SUFFIX
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    free = shutil.disk_usage(os.path.dirname(dst)).free
    size = os.path.getsize(src)
    if free < size + (1 << 30):
        raise OSError(f"insufficient free space for {src}")
    try:
        shutil.copy2(src, partial)
        if os.path.getsize(partial) != size or _checksum(partial) != _checksum(src):
            raise OSError(f"verification failed for {src}")
        os.replace(partial, dst)
    finally:
        if os.path.exists(partial):
            os.unlink(partial)


def _prune_empty_dirs(root, relpath):
    current = os.path.dirname(os.path.join(root, relpath))
    root = os.path.abspath(root)
    while os.path.abspath(current) != root:
        try:
            os.rmdir(current)
        except OSError:
            return
        current = os.path.dirname(current)


class Mover:
    """Executes promotes and demotes between the two branches."""

    def __init__(self, nvme_root, hdd_root, move_sidecars=True):
        self.nvme_root = nvme_root
        self.hdd_root = hdd_root
        self.move_sidecars = move_sidecars

    def _move(self, relpath, src_root, dst_root):
        """Move one media file and its sidecars, copy-verify-delete."""
        src = os.path.join(src_root, relpath)
        dst = os.path.join(dst_root, relpath)
        names = [os.path.basename(relpath)]
        if self.move_sidecars:
            stem = os.path.splitext(os.path.basename(relpath))[0]
            names += _sidecars(os.path.dirname(src), stem)
        for name in dict.fromkeys(names):
            file_src = os.path.join(os.path.dirname(src), name)
            file_dst = os.path.join(os.path.dirname(dst), name)
            if os.path.exists(file_dst) and _checksum(file_dst) == _checksum(file_src):
                os.unlink(file_src)
                continue
            _copy_verified(file_src, file_dst)
            os.unlink(file_src)
        _prune_empty_dirs(src_root, relpath)

    def promote(self, relpath):
        self._move(relpath, self.hdd_root, self.nvme_root)

    def demote(self, relpath):
        self._move(relpath, self.nvme_root, self.hdd_root)
