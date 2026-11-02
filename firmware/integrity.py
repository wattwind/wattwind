"""Firmware file check: each file is compared with its SHA-256 in manifest.json, which
tools/make_manifest.py writes on the PC before an upload. Catches a partial or mixed upload (a file
missed or left from another version) and a damaged file. It only reports (page diagnostics, logbook);
it never stops the fan. Changed the firmware yourself? Run tools/make_manifest.py again.
Pure Python (hashlib, binascii, json): host-tested.
"""
import binascii
import hashlib
import json

MANIFEST = "manifest.json"
CHUNK = 512
TEXT = (".py", ".html", ".json", ".txt", ".css", ".js")   # hashed without \r: Windows / Unix line endings match


def sha256_file(path):
    """SHA-256 as hex; text files without their \r bytes (same rule in tools/make_manifest.py)."""
    text = path.endswith(TEXT)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b.replace(b"\r", b"") if text else b)
    return binascii.hexlify(h.digest()).decode()


async def check(manifest=MANIFEST, root=""):
    """-> "ok", "not checked (no manifest.json)" or e.g. "changed: web.py; missing: dns.py".
    Yields to the other tasks after every file (the watchdog keeps being fed)."""
    import asyncio
    try:
        with open(root + manifest) as f:
            files = json.load(f)["files"]
    except OSError:
        return "not checked (no manifest.json)"
    except (ValueError, KeyError):
        return "not checked (manifest.json damaged)"
    changed, missing = [], []
    for name in sorted(files):
        try:
            if sha256_file(root + name) != files[name]:
                changed.append(name)
        except OSError:
            missing.append(name)
        await asyncio.sleep(0)
    if not changed and not missing:
        return "ok"
    out = []
    if changed:
        out.append("changed: " + ", ".join(changed))
    if missing:
        out.append("missing: " + ", ".join(missing))
    return "; ".join(out)
