# util.py - small shared helpers: clock, OS user, private file/dir creation, hashing, sync-folder check.
import getpass
import os
import tempfile
from datetime import datetime, timezone

_clock = None  # test override; a zero-arg callable returning an ISO-8601 'Z' string

# (marker name, lowercase path-component prefix) pairs; matched case-insensitively per component.
SYNC_FOLDER_MARKERS = [
    ("Nextcloud", "nextcloud"),
    ("Dropbox", "dropbox"),
    ("OneDrive", "onedrive"),
    ("iCloud Drive (Mobile Documents)", "mobile documents"),
    ("Google Drive", "google drive"),
    ("Google Drive", "googledrive"),
    ("Google Drive", "google-drive"),
    ("CloudStorage", "cloudstorage"),
    ("Syncthing", "syncthing"),
]


def now():
    """Return the current UTC time as ISO-8601 with Z (or the test clock's value)."""
    if _clock is not None:
        return _clock()
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(fn):
    """Override the clock with a zero-arg callable returning a string; None restores the real clock."""
    global _clock
    _clock = fn


def os_user():
    """Return the OS user name, or 'unknown' if it cannot be determined."""
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def sha256_hex(data):
    """Return the hex sha256 of bytes or str (str is utf-8 encoded)."""
    import hashlib
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ensure_private_dir(path):
    """Create path (and missing parents) with mode 0700; existing directories are left as they are."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        return path
    parent = os.path.dirname(path)
    if parent and parent != path and not os.path.isdir(parent):
        ensure_private_dir(parent)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    os.chmod(path, 0o700)
    return path


def secure_write(path, text):
    """Atomically write text to path with mode 0600 (temp file in same dir, then rename)."""
    path = os.path.abspath(os.path.expanduser(path))
    ensure_private_dir(os.path.dirname(path))
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def in_sync_folder(path):
    """Return the sync-folder marker name if any path component matches a known one, else None."""
    p = os.path.abspath(os.path.expanduser(str(path)))
    candidates = [p]
    try:
        candidates.append(os.path.realpath(p))
    except Exception:
        pass
    for cand in candidates:
        for comp in cand.replace("\\", "/").split("/"):
            low = comp.strip().lower()
            if not low:
                continue
            for name, prefix in SYNC_FOLDER_MARKERS:
                if low.startswith(prefix):
                    return name
    return None
