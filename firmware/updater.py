"""Firmware update from the web page (no USB): stage, check, apply at the next start.

0. verified_manifest(): the page sends manifest.json exactly as in the update file, with its Ed25519 signature
   (manifest.sig, made by tools/make_update.py with the release key). The fan checks it against the public key in
   release_key.py before anything else: an update not signed by this firmware's maker is refused (USB still works).
1. start(): with the verified manifest.json (version + SHA-256 of every file) and the file sizes. The fan
   compares it with its installed manifest and answers which files differ: only those are sent (a typical
   update is a few files). It checks the names and the free space, and empties the staging folder update/.
2. write(): each file arrives in small pieces, appended to update/<name>. The running files are not touched.
3. finish(): every staged file is checked against the new manifest (integrity.sha256_file), and so is every
   file that was kept. Only if all match, update_apply.json is written: the update is ready. Anything wrong:
   nothing changes, the page says what.
4. apply(), very early at the next start (main.py, before anything else is imported): moves each staged file
   into place, manifest.json and this file last. A power cut halfway: the marker is still there, so the next
   start finishes the job (files already moved are skipped). Then the fan restarts with the new version.

Space: a normal update sends only the changed files. Every file at once needs about 410 KB free, more than a
Pico W may have (about 400-430 KB): then the page says so and USB is the way. Only our own files change:
MicroPython itself (the UF2) still needs USB. config.json, the logbook and the
other files the fan writes can't be overwritten. Pure Python (os, json, integrity): host-tested with ROOT.
"""
import json
import os

ROOT = ""                       # tests point this at a temporary folder (with a trailing "/")
STAGE = "update/"
MARKER = "update_apply.json"
BLOCK = 4096                    # littlefs block size on the Pico: each file takes whole blocks
MARGIN = 24 * 1024              # left free after staging (logbook, config, the filesystem itself)
MAX_CHUNK = 8192
NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./"
PROTECTED = ("config.json", "config.json.bad", "log.txt", "log.old.txt", "quick_boots.txt", "reset_reason.txt",
             "update_mode.txt", MARKER)
LAST = ("updater.py", "manifest.json")    # moved last: a half-applied update is redone by the old updater

_s = None                       # the update being received: {"version", "files": {name: sha}, "sizes", "got"}


def verified_manifest(text, sig, key=None):
    """manifest.json text (as in the update file) + its signature (hex) -> (manifest dict, SHA-256 of the text as
    integrity hashes it). Raises UpdateError unless the signature matches the release key (key: hex, for tests)."""
    import binascii
    import hashlib
    import ed25519
    if key is None:
        import release_key
        key = release_key.KEY
    if not key:
        raise UpdateError("this firmware has no release key: install updates over USB")
    if not isinstance(text, str) or not text:
        raise UpdateError("not a WattWind update: no manifest.json")
    if not isinstance(sig, str) or len(sig) != 128:
        raise UpdateError("the update is not signed (no manifest.sig): install it over USB if you trust it")
    raw = text.encode()
    try:
        ok = ed25519.verify(binascii.unhexlify(key), raw, binascii.unhexlify(sig))
    except ValueError:
        ok = False
    if not ok:
        raise UpdateError("the signature doesn't match: this update wasn't made with this firmware's release key "
                          "(install it over USB if you trust it)")
    try:
        manifest = json.loads(text)
    except ValueError:
        raise UpdateError("not a WattWind update: manifest.json unreadable")
    sha = binascii.hexlify(hashlib.sha256(raw.replace(b"\r", b"")).digest()).decode()
    return manifest, sha


class UpdateError(Exception):
    pass


def name_ok(name):
    return (isinstance(name, str) and 0 < len(name) <= 64 and all(c in NAME_CHARS for c in name)
            and not name.startswith("/") and ".." not in name and "//" not in name
            and name not in PROTECTED and not name.startswith(STAGE))


def _isdir(p):
    try:
        return os.stat(p)[0] & 0x4000 != 0
    except OSError:
        return False


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _mkdirs(path):
    """Create the folders of path (a file name), one level at a time (MicroPython has no makedirs)."""
    parts = path.split("/")[:-1]
    d = ""
    for p in parts:
        d = d + p if not d else d + "/" + p
        if not _isdir(ROOT + d):
            os.mkdir(ROOT + d)


def _rmtree(path):
    if not _exists(path):
        return
    if _isdir(path):
        for n in os.listdir(path):
            _rmtree(path + "/" + n)
        os.rmdir(path)
    else:
        os.remove(path)


def free_bytes():
    st = os.statvfs(ROOT or "/")
    return st[0] * st[4]


def need_bytes(sizes):
    """Flash the staged copy takes: whole blocks per file, plus two metadata blocks per folder (littlefs)."""
    dirs = set()
    for n in sizes:
        parts = n.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))             # every folder level (lib, lib/microdot)
    blocks = sum((s + BLOCK - 1) // BLOCK for s in sizes.values())
    return (blocks + 2 * (len(dirs) + 1)) * BLOCK    # + 1: the update/ folder itself


def active():
    return _s is not None


def start(manifest, sizes, free=None, installed=None, signed_sha=None):
    """manifest: {"version", "files": {name: sha256}}; sizes: {name: bytes}, manifest.json included;
    installed: {name: sha256} of the files on the fan now (None: send everything); signed_sha: SHA-256 of the
    signed manifest.json (verified_manifest): finish() then checks that the staged manifest.json is that one.
    Returns {"version", "send": [names to send], "need", "free"}; raises UpdateError."""
    global _s
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise UpdateError("not a WattWind update: no file list (manifest.json)")
    files = manifest["files"]
    if not isinstance(sizes, dict) or set(sizes) != set(files) | {"manifest.json"}:
        raise UpdateError("the update's files don't match its manifest.json")
    for n, h in files.items():
        if not name_ok(n) or not isinstance(h, str) or len(h) != 64:
            raise UpdateError("bad file name in the update: " + str(n))
    for n, sz in sizes.items():
        if not isinstance(sz, int) or isinstance(sz, bool) or not 0 <= sz <= 256 * 1024:
            raise UpdateError("bad file size: " + str(n))
    _rmtree(ROOT + STAGE.rstrip("/"))             # an earlier, unfinished update
    _rmtree(ROOT + MARKER)
    send = sorted(n for n in files if not installed or installed.get(n) != files[n]) + ["manifest.json"]
    measured = free is None
    if measured:
        free = free_bytes()
    need = need_bytes({n: sizes[n] for n in send})
    if need + MARGIN > free and measured:
        try:                                        # the update comes first: a detailed recording gives way
            import detail
            if detail.rec().exists():
                detail.rec().delete()
                free = free_bytes()
                import logbook
                logbook.event("detailed recording deleted: the firmware update needed the space")
        except Exception:
            pass
    if need + MARGIN > free:
        raise UpdateError("not enough space on the fan: needs {} KB, {} KB free".format(
            (need + MARGIN) // 1024, free // 1024))
    os.mkdir(ROOT + STAGE.rstrip("/"))
    _s = {"version": str(manifest.get("version", "?")), "files": files, "sizes": {n: sizes[n] for n in send},
          "got": {n: 0 for n in send}, "last": {}, "signed_sha": signed_sha}
    return {"version": _s["version"], "send": send, "need": need, "free": free}


def write(name, offset, data):
    """Append data to the staged file; pieces must come in order. Returns the bytes received so far."""
    if _s is None:
        raise UpdateError("no update started")
    if name not in _s["sizes"]:
        raise UpdateError("not in this update: " + str(name))
    if (offset, offset + len(data)) == _s["last"].get(name) and len(data):
        return _s["got"][name]                # the last piece again: it arrived, only the answer got lost
    if offset != _s["got"][name]:
        raise UpdateError("{}: expected the piece at {}, got {}".format(name, _s["got"][name], offset))
    if len(data) > MAX_CHUNK or offset + len(data) > _s["sizes"][name]:
        raise UpdateError(name + ": more data than its size")
    path = STAGE + name
    _mkdirs(path)
    with open(ROOT + path, "ab" if offset else "wb") as f:
        f.write(data)
    _s["got"][name] = offset + len(data)
    _s["last"][name] = (offset, offset + len(data))
    return _s["got"][name]


def cancel():
    global _s
    _s = None
    _rmtree(ROOT + STAGE.rstrip("/"))
    _rmtree(ROOT + MARKER)


async def finish():
    """Check every staged file against the new manifest; write the marker. Returns the new version."""
    import asyncio
    import integrity
    global _s
    if _s is None:
        raise UpdateError("no update started")
    try:
        short = [n for n, sz in _s["sizes"].items() if _s["got"][n] != sz]
        if short:
            raise UpdateError("incomplete: " + ", ".join(sorted(short)))
        bad, kept = [], []
        for n, h in sorted(_s["files"].items()):
            staged = n in _s["sizes"]
            try:
                ok = integrity.sha256_file(ROOT + (STAGE if staged else "") + n) == h
            except OSError:
                ok = False
            if not ok:
                (bad if staged else kept).append(n)
            await asyncio.sleep(0)            # the watchdog and the other tasks keep running
        if bad:
            raise UpdateError("damaged in transfer: " + ", ".join(bad))
        if kept:
            raise UpdateError("installed files differ from their list: " + ", ".join(kept) +
                              " (choose the file again: it then sends every file)")
        with open(ROOT + STAGE + "manifest.json") as f:
            staged = json.load(f)
        if staged.get("files") != _s["files"]:
            raise UpdateError("the update's manifest.json doesn't match what the page sent")
        if _s["signed_sha"] and integrity.sha256_file(ROOT + STAGE + "manifest.json") != _s["signed_sha"]:
            raise UpdateError("the update's manifest.json isn't the signed one")
        order = sorted(n for n in _s["sizes"] if n not in LAST) + [n for n in LAST if n in _s["sizes"]]
        if "detail.py" not in _s["files"]:
            _drop_recording()                 # older firmware (before 0.9.71) would never delete it
        with open(ROOT + MARKER, "w") as f:
            json.dump({"version": _s["version"], "files": order}, f)
        return _s["version"]
    except Exception:
        cancel()
        raise
    finally:
        _s = None


def _drop_recording():
    """Going to firmware without the detailed recording: delete its files now (that firmware doesn't know them,
    so neither its 7-day deletion nor its Erase everything would)."""
    try:
        import detail
        if detail.rec().exists():
            detail.rec().delete()
            import logbook
            logbook.event("detailed recording deleted: the firmware being installed doesn't have it")
    except Exception as e:
        print("updater:", e)


def apply():
    """At start: move a checked, staged update into place. Returns its version, or None if there is none."""
    try:
        with open(ROOT + MARKER) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    for n in m.get("files", []):
        if not name_ok(n) and n != "manifest.json":
            continue
        src = ROOT + STAGE + n
        if not _exists(src):
            continue                          # moved already (a power cut came in between)
        _mkdirs(n)
        if _exists(ROOT + n):
            os.remove(ROOT + n)
        os.rename(src, ROOT + n)
    _rmtree(ROOT + STAGE.rstrip("/"))
    os.remove(ROOT + MARKER)
    return m.get("version", "?")
