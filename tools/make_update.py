"""Write dist/wattwind-update-<version>.tar: the firmware update for the fan's page (Settings > Firmware update).

    python tools/make_manifest.py      (first: bump firmware/version.py, then the manifest)
    python tools/make_update.py

The archive holds every file listed in firmware/manifest.json, plus manifest.json itself, with the same names as
on the Pico, and manifest.sig: the Ed25519 signature of manifest.json (as packed) with the release key
(tools/make_keys.py; its location in tools/signing_key_path.txt). Fans install only updates whose signature
matches firmware/release_key.py. Text files go in without \\r (smaller; their SHA-256 is computed without \\r anyway). A plain tar,
no compression: the page reads it in the browser without any library. The fan checks every file against the
manifest before it changes anything (firmware/updater.py). Attach the .tar to the GitHub release.
"""
import io
import json
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))
import make_manifest  # noqa: E402
import ed25519_sign  # noqa: E402
from integrity import TEXT  # noqa: E402

DIST = os.path.join(HERE, "..", "dist")


def build(root=make_manifest.ROOT, dist=DIST, seed=None, check_key=True):
    with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    now = make_manifest.files(root)
    if now != manifest["files"] or make_manifest.version(root) != manifest["version"]:
        raise SystemExit("make_update: manifest.json is out of date: run tools/make_manifest.py first")
    if seed is None:
        seed = ed25519_sign.load_seed()
    ns = {}
    exec(open(os.path.join(root, "release_key.py"), encoding="utf-8").read(), ns)
    if check_key and ed25519_sign.public_key(seed).hex() != ns.get("KEY"):
        raise SystemExit("make_update: the signing key doesn't match firmware/release_key.py (wrong key file?)")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "wattwind-update-{}.tar".format(manifest["version"]))
    with tarfile.open(out, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(manifest["files"]) + ["manifest.json"]:
            with open(os.path.join(root, name), "rb") as f:
                data = f.read()
            if name.endswith(TEXT):
                data = data.replace(b"\r", b"")
            if name == "manifest.json":
                sig = ed25519_sign.sign(seed, data).hex().encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo("manifest.sig")
        info.size = len(sig)
        info.mtime = 0
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(sig))
    try:
        shown = os.path.relpath(out)
    except ValueError:                  # Windows: the file is on another drive than the current folder
        shown = out
    print("{}: {} files + signature, {} KB".format(shown, len(manifest["files"]) + 1,
                                                    os.path.getsize(out) // 1024))
    return out


if __name__ == "__main__":
    build()
