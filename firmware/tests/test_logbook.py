import logbook


def test_lines_are_appended(tmp_path):
    p, o = str(tmp_path / "log.txt"), str(tmp_path / "log.old.txt")
    logbook.write("a", p, o)
    logbook.write("b", p, o)
    assert open(p).read() == "a\nb\n"


def test_full_file_rotates_and_keeps_one_old(tmp_path):
    import os
    p, o = str(tmp_path / "log.txt"), str(tmp_path / "log.old.txt")
    for i in range(30):
        logbook.write("line %02d" % i, p, o, max_bytes=40)
    cur, old = open(p).read().split(), open(o).read().split()
    cur = [w for w in cur if w != "line"]; old = [w for w in old if w != "line"]
    assert cur[-1] == "29"                                       # newest line kept
    assert int(old[-1]) + 1 == int(cur[0])                       # old file continues into the current one
    assert os.stat(p).st_size <= 40 and os.stat(o).st_size <= 40 # size limit respected (any line ending)


def test_never_raises(tmp_path):
    logbook.write("x", str(tmp_path / "no" / "such" / "dir" / "log.txt"), str(tmp_path / "o.txt"))


def test_status_line_only_on_change_or_every_half_hour():
    due = logbook.StatusDue(quiet_s=1800)
    key = ("auto", 0, "sta", True, False)
    assert due(key, 300)                         # the first one always
    assert not due(key, 600) and not due(key, 1800)
    assert due(key, 2100)                        # 30 min without change
    assert due(("auto", 1, "sta", True, False), 2400)   # level changed
    assert not due(("auto", 1, "sta", True, False), 2700)
