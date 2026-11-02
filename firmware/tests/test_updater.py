import asyncio
import hashlib
import importlib
import json
import os
import sys
import tarfile

import pytest

import config
import state
import integrity
import updater
import web
from conftest import FIRMWARE
from microdot_test_client import TestClient

sys.path.insert(0, os.path.join(FIRMWARE, "..", "tools"))
import ed25519_sign  # noqa: E402

TEST_SEED = bytes(range(32))                       # a test key pair, never the release key
TEST_KEY = ed25519_sign.public_key(TEST_SEED).hex()

FILES = {"main.py": b"print('new main')\n", "web.py": b"# new web\r\n", "www/index.html": b"<p>new</p>\n",
         "updater.py": b"# new updater\n", "lib/microdot/x.py": b"x = 1\n"}


def sha(b, text=True):
    return hashlib.sha256(b.replace(b"\r", b"") if text else b).hexdigest()


def manifest(files=FILES, version="9.9.9"):
    return {"version": version, "files": {n: sha(d) for n, d in files.items()}}


def payload(files=FILES, version="9.9.9"):
    m = manifest(files, version)
    mj = json.dumps(m).encode()
    data = dict(files, **{"manifest.json": mj})
    return m, data, {n: len(d) for n, d in data.items()}


def signed(data, seed=TEST_SEED):
    """The page's /api/update/start body for a payload: manifest.json as text and its signature."""
    return {"manifest_text": data["manifest.json"].decode(), "sig": ed25519_sign.sign(seed, data["manifest.json"]).hex()}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "ROOT", str(tmp_path).replace("\\", "/") + "/")
    monkeypatch.setattr(updater, "_s", None)
    (tmp_path / "config.json").write_text('{"ftp": 250}')
    (tmp_path / "main.py").write_text("print('old main')\n")
    return tmp_path


def send(data, chunk=7):
    for n, d in data.items():
        for off in range(0, max(len(d), 1), chunk):
            updater.write(n, off, d[off:off + chunk])


def test_names():
    assert updater.name_ok("main.py") and updater.name_ok("www/index.html") and updater.name_ok("lib/a/b.py")
    for bad in ("../x.py", "/main.py", "config.json", "log.txt", "update/x.py", "a//b", "a b.py", "", "x" * 65,
                updater.MARKER, None):
        assert not updater.name_ok(bad), bad


def test_full_update_then_apply(root):
    m, data, sizes = payload()
    info = updater.start(m, sizes, free=10 ** 7)
    assert info["version"] == "9.9.9" and set(info["send"]) == set(data)
    send(data)
    assert asyncio.run(updater.finish()) == "9.9.9"
    marker = json.loads((root / updater.MARKER).read_text())
    assert marker["files"][-2:] == ["updater.py", "manifest.json"]          # the mover and the list last
    assert (root / "main.py").read_text() == "print('old main')\n"           # nothing changed yet
    assert updater.apply() == "9.9.9"
    for n, d in data.items():
        assert (root / n).read_bytes() == d
    assert (root / "config.json").read_text() == '{"ftp": 250}'             # settings stay
    assert not (root / "update").exists() and not (root / updater.MARKER).exists()
    assert updater.apply() is None                                            # nothing left to do


def test_only_changed_files_are_sent(root):
    for n in ("web.py", "lib/microdot/x.py"):                    # installed already, unchanged
        os.makedirs(os.path.dirname(str(root / n)) or str(root), exist_ok=True)
        (root / n).write_bytes(FILES[n])
    m, data, sizes = payload()
    installed = {"web.py": m["files"]["web.py"], "lib/microdot/x.py": m["files"]["lib/microdot/x.py"],
                 "main.py": "0" * 64}
    info = updater.start(m, sizes, free=10 ** 7, installed=installed)
    assert info["send"] == ["main.py", "updater.py", "www/index.html", "manifest.json"]
    with pytest.raises(updater.UpdateError, match="not in this update"):
        updater.write("web.py", 0, b"x")
    send({n: data[n] for n in info["send"]})
    assert asyncio.run(updater.finish()) == "9.9.9"
    updater.apply()
    for n, d in data.items():
        assert (root / n).read_bytes() == d


def test_a_kept_file_that_differs_stops_the_update(root):
    (root / "web.py").write_bytes(b"# edited by hand\n")
    m, data, sizes = payload()
    info = updater.start(m, sizes, free=10 ** 7, installed={"web.py": m["files"]["web.py"]})   # the list says ok
    send({n: data[n] for n in info["send"]})
    with pytest.raises(updater.UpdateError, match="differ.*web.py"):
        asyncio.run(updater.finish())
    assert updater.apply() is None and (root / "web.py").read_bytes() == b"# edited by hand\n"


def test_space_estimate():
    one = updater.need_bytes({"a.py": 1, "manifest.json": 5000})
    assert one == 3 * updater.BLOCK + 2 * updater.BLOCK            # 1 + 2 blocks, the root folder
    assert updater.need_bytes({"www/a.html": 4096, "lib/x/y.py": 4097}) == 3 * updater.BLOCK + 2 * updater.BLOCK * 4


def test_apply_resumes_after_a_power_cut(root):
    m, data, sizes = payload()
    updater.start(m, sizes, free=10 ** 7)
    send(data)
    asyncio.run(updater.finish())
    os.makedirs(root / "www", exist_ok=True)
    os.replace(root / "update" / "www" / "index.html", root / "www" / "index.html")   # moved before the cut
    assert updater.apply() == "9.9.9"
    assert (root / "www" / "index.html").read_bytes() == data["www/index.html"]
    assert (root / "main.py").read_bytes() == data["main.py"]


def test_start_checks(root):
    m, data, sizes = payload()
    with pytest.raises(updater.UpdateError, match="space"):
        updater.start(m, sizes, free=50 * 1024)
    with pytest.raises(updater.UpdateError, match="match"):
        updater.start(m, dict(sizes, extra=1), free=10 ** 7)
    bad = manifest(dict(FILES, **{"config.json": b"{}"}))
    with pytest.raises(updater.UpdateError, match="bad file name"):
        updater.start(bad, {n: 1 for n in list(bad["files"]) + ["manifest.json"]}, free=10 ** 7)
    with pytest.raises(updater.UpdateError):
        updater.start({"files": {}}, {}, free=10 ** 7)


def test_write_checks(root):
    m, data, sizes = payload()
    with pytest.raises(updater.UpdateError, match="no update"):
        updater.write("main.py", 0, b"x")
    updater.start(m, sizes, free=10 ** 7)
    with pytest.raises(updater.UpdateError, match="not in this update"):
        updater.write("other.py", 0, b"x")
    updater.write("main.py", 0, b"print(")
    with pytest.raises(updater.UpdateError, match="expected the piece"):
        updater.write("main.py", 2, b"int(")                                  # a gap / wrong place
    with pytest.raises(updater.UpdateError, match="more data"):
        updater.write("main.py", 6, b"x" * 100)


def test_a_piece_sent_twice_is_fine(root):
    m, data, sizes = payload()
    updater.start(m, sizes, free=10 ** 7)
    assert updater.write("main.py", 0, b"print(") == 6
    assert updater.write("main.py", 0, b"print(") == 6            # the answer got lost: the page sends it again
    assert updater.write("main.py", 6, data["main.py"][6:]) == len(data["main.py"])


def test_damaged_file_changes_nothing(root):
    m, data, sizes = payload()
    updater.start(m, sizes, free=10 ** 7)
    data["web.py"] = b"# NEW web\r\n"                                          # same size, other bytes
    send(data)
    with pytest.raises(updater.UpdateError, match="damaged.*web.py"):
        asyncio.run(updater.finish())
    assert not (root / "update").exists() and not (root / updater.MARKER).exists()
    assert updater.apply() is None and not updater.active()


def test_incomplete_changes_nothing(root):
    m, data, sizes = payload()
    updater.start(m, sizes, free=10 ** 7)
    updater.write("main.py", 0, data["main.py"][:3])
    with pytest.raises(updater.UpdateError, match="incomplete"):
        asyncio.run(updater.finish())
    assert updater.apply() is None


# ---- web API ----------------------------------------------------------------------------------------

@pytest.fixture
def env(root, monkeypatch):
    importlib.reload(state)
    monkeypatch.chdir(FIRMWARE)
    monkeypatch.setattr(updater, "free_bytes", lambda: 10 ** 7)
    import release_key
    monkeypatch.setattr(release_key, "KEY", TEST_KEY)
    cfg = dict(config.DEFAULTS, settings_pin="1234")
    return cfg, TestClient(web.create_app(cfg, save=lambda c: None))


def run(coro):
    return asyncio.run(coro)


def test_update_over_the_api(env, root):
    cfg, client = env
    m, data, sizes = payload()
    r = run(client.post("/api/update/start", body=dict(signed(data), sizes=sizes)))
    assert r.status_code == 403
    r = run(client.post("/api/update/start", body=dict(signed(data), sizes=sizes, pin="1234")))
    assert r.status_code == 200 and r.json["current"]
    assert run(client.get("/api/status")).json["updating"] is True              # fan off meanwhile
    for n, d in data.items():
        r = run(client.post("/api/update/file?path={}&offset=0".format(n), body=d,
                            headers={"X-Pin": "1234", "Content-Type": "application/octet-stream"}))
        assert r.status_code == 200 and r.json["got"] == len(d), (n, r.json)
    r = run(client.post("/api/update/file?path=main.py&offset=0", body=b"x", headers={"X-Pin": "nope"}))
    assert r.status_code == 403
    r = run(client.post("/api/update/finish", body={"pin": "1234"}))
    assert r.status_code == 200 and r.json["version"] == "9.9.9"
    assert state.reboot_requested and "9.9.9" in state.reboot_reason
    assert (root / updater.MARKER).exists()


def test_update_api_reports_errors(env):
    cfg, client = env
    r = run(client.post("/api/update/finish", body={"pin": "1234"}))
    assert r.status_code == 400 and "no update" in r.json["error"]
    r = run(client.post("/api/update/start", body={"manifest": {}, "sizes": {}, "pin": "1234"}))
    assert r.status_code == 400 and not state.reboot_requested


# ---- signed updates (EN 303 645 5.3-9, 5.3-10) ------------------------------------------------------

def test_signature_check():
    m, data, sizes = payload()
    body = signed(data)
    got, sha_ = updater.verified_manifest(body["manifest_text"], body["sig"], key=TEST_KEY)
    assert got == m and sha_ == sha(data["manifest.json"])
    other = ed25519_sign.sign(bytes(32), data["manifest.json"]).hex()                    # someone else's key
    tampered = body["manifest_text"].replace("9.9.9", "9.9.8")
    for text, sig, why in ((body["manifest_text"], other, "doesn't match"), (tampered, body["sig"], "doesn't match"),
                           (body["manifest_text"], None, "not signed"), (body["manifest_text"], "zz" * 64, "doesn't match")):
        with pytest.raises(updater.UpdateError) as e:
            updater.verified_manifest(text, sig, key=TEST_KEY)
        assert why in str(e.value)
    with pytest.raises(updater.UpdateError, match="no release key"):
        updater.verified_manifest(body["manifest_text"], body["sig"], key="")


def test_unsigned_or_foreign_update_refused_over_the_api(env):
    cfg, client = env
    m, data, sizes = payload()
    for body in ({"manifest": m}, dict(signed(data, seed=bytes(32)))):              # old style; another maker's key
        r = run(client.post("/api/update/start", body=dict(body, sizes=sizes, pin="1234")))
        assert r.status_code == 400 and not updater.active(), r.json


def test_staged_manifest_must_be_the_signed_one(env, root):
    cfg, client = env
    m, data, sizes = payload()
    assert run(client.post("/api/update/start", body=dict(signed(data), sizes=sizes, pin="1234"))).status_code == 200
    swapped = json.dumps({"files": m["files"], "version": m["version"]}).encode()   # same content and size, other bytes
    assert swapped != data["manifest.json"] and len(swapped) == sizes["manifest.json"]
    data = dict(data, **{"manifest.json": swapped})
    for n, d in data.items():
        run(client.post("/api/update/file?path={}&offset=0".format(n), body=d,
                        headers={"X-Pin": "1234", "Content-Type": "application/octet-stream"}))
    r = run(client.post("/api/update/finish", body={"pin": "1234"}))
    assert r.status_code == 400 and "isn't the signed one" in r.json["error"]
    assert not (root / updater.MARKER).exists()


# ---- the update file ----------------------------------------------------------------------------------

def test_make_update_packs_the_manifest_files(tmp_path):
    sys.path.insert(0, os.path.join(FIRMWARE, "..", "tools"))
    import make_update
    out = make_update.build(dist=str(tmp_path), seed=TEST_SEED, check_key=False)
    with open(os.path.join(FIRMWARE, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert sorted(names) == sorted(list(m["files"]) + ["manifest.json", "manifest.sig"])
        mj = tar.extractfile("manifest.json").read()
        sig = tar.extractfile("manifest.sig").read().decode()
        assert updater.verified_manifest(mj.decode(), sig, key=TEST_KEY)[0] == m          # the fan accepts it
        for n in m["files"]:
            assert sha(tar.extractfile(n).read(), text=n.endswith(integrity.TEXT)) == m["files"][n], n
    assert os.path.basename(out) == "wattwind-update-{}.tar".format(m["version"])


@pytest.mark.parametrize("has_detail", [False, True])
def test_installing_firmware_without_the_recording_deletes_it(root, monkeypatch, has_detail):
    """Firmware older than 0.9.71 doesn't know the detailed recording: it would never delete it (7 days, Erase)."""
    import detail
    rec = detail.Recorder(str(root / "d.txt"), str(root / "d.old.txt"), str(root / "d.json"))
    monkeypatch.setattr(detail, "_rec", rec)
    rec.start(0, "t", free=10 ** 7)
    files = dict(FILES, **({"detail.py": b"# recorder\n"} if has_detail else {}))
    m, data, sizes = payload(files)
    updater.start(m, sizes, free=10 ** 7)
    send(data)
    asyncio.run(updater.finish())
    assert rec.exists() is has_detail
