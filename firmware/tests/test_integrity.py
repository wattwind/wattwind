import asyncio
import os
import sys

import integrity

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import make_manifest  # noqa: E402


def tree(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "lib" / "microdot").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    for p, body in {"main.py": "print(1)\n", "version.py": 'VERSION = "9.9.9"\n', "www/index.html": "<p>",
                    "lib/microdot/microdot.py": "x = 1\n", "lib/microdot/LICENSE.txt": "MIT",
                    "tests/test_x.py": "", "config.json": "{}", "log.txt": "up=0"}.items():
        (tmp_path / p).write_bytes(body.encode())
    return tmp_path


def check(root):
    return asyncio.run(integrity.check(root=str(root) + "/"))


def test_manifest_lists_only_pico_files(tmp_path):
    root = tree(tmp_path)
    assert sorted(make_manifest.files(str(root))) == ["lib/microdot/microdot.py", "main.py", "version.py",
                                                      "www/index.html"]


def test_ok_changed_missing_and_no_manifest(tmp_path):
    root = tree(tmp_path)
    assert check(root) == "not checked (no manifest.json)"
    make_manifest.main(str(root))
    assert check(root) == "ok"
    (root / "config.json").write_text('{"ftp": 300}')         # the fan's own files don't count
    assert check(root) == "ok"
    (root / "main.py").write_text("print(2)\n")
    os.remove(root / "www" / "index.html")
    assert check(root) == "changed: main.py; missing: www/index.html"


def test_damaged_manifest(tmp_path):
    root = tree(tmp_path)
    (root / "manifest.json").write_text("{nope")
    assert check(root) == "not checked (manifest.json damaged)"


def test_hash_matches_hashlib(tmp_path):
    import hashlib
    p = tmp_path / "big.bin"
    data = bytes(range(256)) * 20                              # several chunks (binary: hashed as is)
    p.write_bytes(data)
    assert integrity.sha256_file(str(p)) == hashlib.sha256(data).hexdigest()


def test_line_endings_do_not_count_in_text_files(tmp_path):
    root = tree(tmp_path)
    make_manifest.main(str(root))
    (root / "main.py").write_bytes(b"print(1)\r\n")              # copied from a Windows checkout
    assert check(root) == "ok"
    (root / "www" / "icon.png").write_bytes(b"\x89PNG\r\n")       # binary files: every byte counts
    make_manifest.main(str(root))
    (root / "www" / "icon.png").write_bytes(b"\x89PNG\n")
    assert check(root) == "changed: www/icon.png"
