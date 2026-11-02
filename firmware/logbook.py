"""Logbook on the fan's flash: one line per event (start, every few minutes), kept across restarts.

GET /api/log returns it (/api/log?old=1 the previous file), streamed from flash, so a long test (or "why did it restart last night?") can be read later over
Wi-Fi without USB. When the file passes MAX_BYTES it becomes log.old.txt (one old file kept), so the
log never fills the flash. Pure Python apart from file access: host-tested.
"""
import os

PATH = "log.txt"
OLD = "log.old.txt"
MAX_BYTES = 128 * 1024         # per file, two files: about 9 days of a busy fan, weeks of an idle one


def _size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return 0


def write(line, path=PATH, old=OLD, max_bytes=MAX_BYTES):
    """Append one line; rotate first if the file is full. Never raises (the fan must not care)."""
    try:
        if _size(path) + len(line) + 1 > max_bytes:
            try:
                os.remove(old)
            except OSError:
                pass
            os.rename(path, old)
        with open(path, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        print("logbook:", e)


def event(text):
    """One event line, stamped with the uptime. Never raises."""
    try:
        import state
        write("up={} {}".format(state.uptime_s, text))
    except Exception:
        pass


class StatusDue:
    """Whether the periodic status line is due: when what counts (mode, level, Wi-Fi, sensors) changed since the
    last line, else only every quiet_s, so an idle fan keeps weeks of history."""

    def __init__(self, quiet_s):
        self.quiet_s = quiet_s
        self._key = None
        self._at = None

    def __call__(self, key, now_s):
        if self._at is not None and key == self._key and now_s - self._at < self.quiet_s:
            return False
        self._key, self._at = key, now_s
        return True
