"""The detailed recording (detail.py): lines, batches, rotation, 24 h, kept 7 days, survives a restart."""
import os
import types

import detail


def rec(tmp_path):
    return detail.Recorder(str(tmp_path / "d.txt"), str(tmp_path / "d.old.txt"), str(tmp_path / "d.json"))


def st(**kw):
    s = dict(power=None, cadence=None, hr=None, level=0, target_level=0, mode="auto", hr_off=None)
    s.update(kw)
    return types.SimpleNamespace(**s)


CFG = {"ftp": 200, "hr_max": 190, "hr_rest": 60, "use": "both", "response": "normal", "up_thresholds": [0.45, 0.7, 0.88],
       "down_thresholds": [0.38, 0.63, 0.81], "dwell_up_s": 15, "dwell_down_s": 60, "idle_off_min": 15, "max_level": 3}


def text(r):
    r.flush()
    return "".join(r.chunks())


def test_off_by_default_and_writes_nothing(tmp_path):
    r = rec(tmp_path)
    assert r.status() is None
    r.line(5, "E", "x")
    r.second(1, st(power=200), CFG)
    assert not r.exists() and not os.path.exists(str(tmp_path / "d.json"))


def test_ride_lines_settings_and_minute_line(tmp_path):
    r = rec(tmp_path)
    r.start(100, "2026-10-31 18:00Z", free=2_000_000)
    r.second(101, st(power=205.4, cadence=91, hr=146, level=2, target_level=2), CFG, lambda: "now free=1")
    r.second(102, st(), CFG)                                   # nothing to record: no R line
    r.second(103, st(hr=150, hr_off="beats", mode="manual", level=1, target_level=1), CFG)
    t = text(r)
    assert "101 R 205 91 146 2 2 a\n" in t
    assert "102 R" not in t
    assert "103 R - - 150 1 1 mx\n" in t
    assert '"ftp": 200' in t and " S " in t                   # settings for a replay
    assert "101 H now free=1 lag=0 leader=0" in t
    assert r.status()["on"] and r.status()["left_s"] == detail.ON_S - 3


def test_lines_are_batched_not_written_each_second(tmp_path):
    r = rec(tmp_path)
    r.start(0, "t", free=2_000_000)
    size0 = os.path.getsize(str(tmp_path / "d.txt"))
    r.second(1, st(power=100), CFG)                           # first second flushes (flush timer starts at 0)
    size1 = os.path.getsize(str(tmp_path / "d.txt"))
    for s in range(2, 2 + detail.FLUSH_S - 1):
        r.second(s, st(power=100), CFG)
    assert os.path.getsize(str(tmp_path / "d.txt")) == size1 > size0
    r.second(1 + detail.FLUSH_S, st(power=100), CFG)
    assert os.path.getsize(str(tmp_path / "d.txt")) > size1


def test_rotation_keeps_the_latest_two_files(tmp_path):
    r = rec(tmp_path)
    r.start(0, "t", free=0)                                    # tiny flash: the smallest files
    assert r.max_bytes == detail.MIN_BYTES
    for s in range(1, 3000):
        r.second(s, st(power=s % 400, cadence=90, hr=140, level=1, target_level=1), CFG)
    r.flush()
    assert os.path.getsize(str(tmp_path / "d.txt")) <= detail.MIN_BYTES
    assert os.path.getsize(str(tmp_path / "d.old.txt")) <= detail.MIN_BYTES
    assert "2999 R" in text(r)                                 # the newest second is there
    assert "recording started" not in text(r)                  # the oldest part went


def test_ends_after_24_hours_and_is_deleted_7_days_later(tmp_path):
    r = rec(tmp_path)
    r.start(0, "t", free=2_000_000)
    assert r.second(detail.ON_S - 1, st(), CFG) is None
    assert r.second(detail.ON_S, st(), CFG) == "ended"
    assert not r.status()["on"] and r.exists() and "24 h are over" in text(r)
    assert r.second(detail.ON_S + detail.KEEP_S - 1, st(), CFG) is None
    assert r.second(detail.ON_S + detail.KEEP_S, st(), CFG) == "deleted"
    assert not r.exists() and r.status() is None


def test_continues_after_a_restart(tmp_path):
    r = rec(tmp_path)
    r.start(0, "2026-10-31 18:00Z", free=2_000_000)
    for s in range(1, 400):
        r.second(s, st(power=100), CFG)                        # meta saved every SAVE_S
    again = rec(tmp_path)                                      # a restart: uptime starts at 0 again
    assert again.on and again.started == "2026-10-31 18:00Z"
    assert detail.ON_S - 400 <= again.left_s <= detail.ON_S - 300
    again.second(1, st(power=120, reset_reason="power on"), CFG)
    t = text(again)
    assert "1 E fan restarted (power on): recording continues" in t and "1 R 120" in t
    assert "391 R 100" in t                                    # written; the last <= 10 s before a power cut can be lost


def test_stop_keeps_the_file_start_replaces_it_delete_removes_all(tmp_path):
    r = rec(tmp_path)
    r.start(0, "first", free=2_000_000)
    r.second(1, st(power=100), CFG)
    r.stop(2)
    assert not r.status()["on"] and "first" in text(r) and "stopped from the page" in text(r)
    r.start(3, "second", free=2_000_000)
    assert "first" not in text(r) and "second" in text(r)
    r.delete()
    assert not r.exists() and not os.listdir(str(tmp_path))


def test_gaps_and_lag_and_leader_packets(tmp_path):
    r = rec(tmp_path)
    r.start(0, "t", free=2_000_000)
    r.gap(5, "hr", 1500)                                       # normal: not noted
    r.gap(6, "power", 3400)
    r.note_lag(40); r.note_lag(900); r.note_lag(10)
    r.count_leader(); r.count_leader()
    r.second(60, st(), CFG, lambda: "h")
    t = text(r)
    assert "5 E hr" not in t and "6 E power data gap 3.4 s" in t
    assert "60 H h lag=900 leader=2" in t


def test_download_is_oldest_first_and_flushes(tmp_path):
    r = rec(tmp_path)
    r.start(0, "t", free=0)
    for s in range(1, 1500):
        r.second(s, st(power=200, level=1, target_level=1), CFG)
    r.line(1500, "E", "last line, still in the buffer")
    t = "".join(r.chunks())
    lines = [int(l.split()[0]) for l in t.splitlines() if l]
    assert lines == sorted(lines) and t.rstrip().endswith("still in the buffer")
