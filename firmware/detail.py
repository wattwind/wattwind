"""Detailed recording: extra lines for finding a problem, switched on from the page (Settings -> Maintenance).

Its own files (detail.txt, and detail.old.txt when that is full: the latest few hours are kept), so the normal
logbook keeps its history. On for ON_S (24 h, also across restarts: a restart is often the problem), then off by
itself. The files stay for download until Delete, the next Start, Erase everything, or KEEP_S of the fan running
after the end (they hold heart rate: nobody needs them for longer).

Lines start with the uptime, like the logbook, so the two line up:
  up R power cadence hr level target mode[x]   every second while riding (sensor data or fan on); mode a/m/f,
                                               x = the strap is connected but not worn; "-" = no value
  up H <time> free= lag= rssi= chip= leader=   every minute: memory, the longest delay of the 1 s tick (ms), Wi-Fi,
                                               chip temperature, linked-fans packets heard
  up E <text>                                  events: sensor data gaps over 2 s, fan level changes with the
                                               reason, start / end
  up S {settings}                              what fan_logic needs to replay the ride (at start and on change)
Written in batches (every FLUSH_S or BUF_BYTES), so the flash isn't written every second. Pure Python apart from
file access: host-tested (tests/test_detail.py).
"""
import json
import os

PATH = "detail.txt"
OLD = "detail.old.txt"
META = "detail.json"
FILES = (PATH, OLD, META)
ON_S = 24 * 3600
KEEP_S = 7 * 24 * 3600
MAX_BYTES = 256 * 1024          # per file, two files: 5-6 hours of riding on a Pico 2 W
MIN_BYTES = 16 * 1024
SPACE_SHARE = 6                 # each file at most 1/6 of the free flash (a Pico W has little)
FLUSH_S = 10
BUF_BYTES = 4096
SAVE_S = 300                    # time left / keep time saved this often (survives a restart)
GAP_MS = 2000                   # sensor data gaps longer than this are noted
REPLAY_KEYS = ("ftp", "hr_max", "hr_rest", "use", "response", "up_thresholds", "down_thresholds", "dwell_up_s",
               "dwell_down_s", "idle_off_min", "max_level")


def _size(p):
    try:
        return os.stat(p)[6]
    except OSError:
        return 0


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _v(x):
    return "-" if x is None else str(int(round(x)))


class Recorder:
    def __init__(self, path=PATH, old=OLD, meta=META):
        self.path, self.old, self.meta = path, old, meta
        self.on = False
        self.left_s = 0                 # recording time left
        self.keep_s = 0                 # after the end: fan running time until the files are deleted
        self.max_bytes = MAX_BYTES
        self.started = ""
        self._buf = []
        self._n = 0
        self._last = None               # uptime of the last second()
        self._flush_at = 0
        self._save_at = 0
        self._minute_at = 0
        self._settings = None
        self.lag_ms = 0
        self.leader = 0
        self.load()
        self._resumed = self.on         # recording when the fan started: say so in the first line

    # ---- state across restarts
    def load(self):
        try:
            with open(self.meta) as f:
                m = json.load(f)
            self.on = bool(m.get("on"))
            self.left_s = int(m.get("left_s", 0))
            self.keep_s = int(m.get("keep_s", KEEP_S))
            self.max_bytes = int(m.get("max_bytes", MAX_BYTES))
            self.started = str(m.get("started", ""))
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save_meta(self):
        try:
            if not self.on and not self.exists():
                _remove(self.meta)
                return
            with open(self.meta, "w") as f:
                json.dump({"on": self.on, "left_s": self.left_s, "keep_s": self.keep_s, "max_bytes": self.max_bytes,
                           "started": self.started}, f)
        except Exception as e:
            print("detail:", e)

    # ---- what the page shows
    def exists(self):
        return bool(self._buf) or _size(self.path) + _size(self.old) > 0

    def size(self):
        return _size(self.path) + _size(self.old) + self._n

    def status(self):
        if self.on:
            return {"on": True, "left_s": self.left_s, "kb": self.size() // 1024, "started": self.started}
        if self.exists():
            return {"on": False, "kb": self.size() // 1024, "keep_s": self.keep_s, "started": self.started}
        return None

    # ---- actions from the page
    def start(self, now_s, stamp, free):
        self.delete()
        self.max_bytes = max(MIN_BYTES, min(MAX_BYTES, free // SPACE_SHARE))
        self.on, self.left_s, self.keep_s, self.started = True, ON_S, KEEP_S, stamp
        self._last, self._settings = now_s, None
        self._minute_at = now_s
        self.line(now_s, "E", "recording started {} (24 h; {} KB per file, two files)".format(stamp, self.max_bytes // 1024))
        self.line(now_s, "E", "columns: up R power cadence hr level target mode(a/m/f, x = strap not worn) | "
                              "up H time free lag(ms) rssi chip leader-packets | up E event | up S settings")
        self.flush()
        self._save_meta()

    def stop(self, now_s, why="stopped from the page"):
        if not self.on:
            return
        self.line(now_s, "E", "recording ended: " + why)
        self.on = False
        self.keep_s = KEEP_S
        self.flush()
        self._save_meta()

    def delete(self):
        self._buf, self._n = [], 0
        self.on, self.left_s, self.started = False, 0, ""
        for p in (self.path, self.old, self.meta):
            _remove(p)

    # ---- lines
    def line(self, now_s, tag, text):
        if not self.on:
            return
        s = "{} {} {}".format(now_s, tag, text)
        self._buf.append(s)
        self._n += len(s) + 1
        if self._n >= BUF_BYTES:
            self.flush()

    def flush(self):
        """Write the buffered lines; rotate first when the file would pass max_bytes. Never raises."""
        if not self._buf:
            return
        data = "\n".join(self._buf) + "\n"
        self._buf, self._n = [], 0
        try:
            if _size(self.path) + len(data) > self.max_bytes:
                _remove(self.old)
                os.rename(self.path, self.old)
            with open(self.path, "a") as f:
                f.write(data)
        except Exception as e:
            print("detail:", e)

    def gap(self, now_s, role, ms):
        if self.on and ms > GAP_MS:
            self.line(now_s, "E", "{} data gap {:.1f} s".format(role, ms / 1000))

    def note_lag(self, ms):
        if ms > self.lag_ms:
            self.lag_ms = ms

    def count_leader(self):
        self.leader += 1

    def second(self, now_s, st, cfg, health=None):
        """Once per second from main.py. st: the state module (or a stand-in); health: a function returning the
        minute line's text. Returns "ended" / "deleted" when that just happened (for the logbook), else None."""
        dt = 1 if self._last is None else max(0, now_s - self._last)
        self._last = now_s
        if self._resumed and self.on:
            self._resumed = False
            self.line(now_s, "E", "fan restarted ({}): recording continues".format(getattr(st, "reset_reason", "?")))
        if self.on:
            s = {k: cfg.get(k) for k in REPLAY_KEYS}
            if s != self._settings:
                self._settings = s
                self.line(now_s, "S", json.dumps(s))
            if st.power is not None or st.hr is not None or st.level:
                self.line(now_s, "R", "{} {} {} {} {} {}{}".format(
                    _v(st.power), _v(st.cadence), _v(st.hr), st.level, st.target_level,
                    {"auto": "a", "manual": "m", "follow": "f"}.get(st.mode, "?"), "x" if st.hr_off else ""))
            if now_s >= self._minute_at:
                self._minute_at = now_s + 60
                try:
                    text = health() if health else ""
                except Exception as e:
                    text = repr(e)
                self.line(now_s, "H", "{} lag={} leader={}".format(text, self.lag_ms, self.leader))
                self.lag_ms, self.leader = 0, 0
            self.left_s -= dt
            if self.left_s <= 0:
                self.stop(now_s, "24 h are over")
                return "ended"
            if now_s >= self._flush_at:
                self._flush_at = now_s + FLUSH_S
                self.flush()
            if now_s >= self._save_at:
                self._save_at = now_s + SAVE_S
                self._save_meta()
        elif self.started and self.exists():
            self.keep_s -= dt
            if self.keep_s <= 0:
                self.delete()
                return "deleted"
            if now_s >= self._save_at:
                self._save_at = now_s + SAVE_S
                self._save_meta()
        return None

    def chunks(self, size=1024):
        """Both files, oldest first, for the download (streamed: never the whole file in RAM)."""
        self.flush()
        for p in (self.old, self.path):
            try:
                with open(p) as f:
                    while True:
                        b = f.read(size)
                        if not b:
                            break
                        yield b
            except OSError:
                pass


_rec = None


def rec():
    """The one recorder (created on first use, reading detail.json)."""
    global _rec
    if _rec is None:
        _rec = Recorder()
    return _rec
