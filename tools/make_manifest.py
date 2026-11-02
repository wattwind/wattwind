"""Write firmware/manifest.json: the SHA-256 of every file that goes onto the Pico.

Run it after changing anything in firmware/ and before uploading (also in a fork):

    python tools/make_manifest.py

The fan checks its files against this list when it starts (firmware/integrity.py) and shows the result
under Settings ("Files: ok", or which files are changed or missing) and in the logbook. It only reports;
the fan runs either way. No manifest.json on the Pico: "not checked".

The files left out are the ones that never go onto the Pico (keep in step with micropico.pyIgnore in
.vscode/settings.json) and the ones the fan writes itself.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware"))
from integrity import sha256_file  # noqa: E402  same hashing as on the fan (text files without \r)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")
SKIP_DIRS = {"tests", "__pycache__", ".pytest_cache"}
SKIP_FILES = {"manifest.json", "README.md", "config.json", "config.json.bad", "pytest.ini", "relay_test.py", "blink.py",
              "log.txt", "log.old.txt", "quick_boots.txt", "reset_reason.txt", "erased.txt",
              "detail.txt", "detail.old.txt", "detail.json", "crash_boots.txt", "config.json.tmp"}


def wanted(rel):
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1] in SKIP_FILES:
        return False
    if parts[0] == "lib" and parts[-1].endswith(".txt"):       # library LICENSE / README stay on the PC
        return False
    return True


def files(root=ROOT):
    out = {}
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for n in sorted(names):
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if wanted(rel):
                out[rel] = sha256_file(p)
    return out


def version(root=ROOT):
    ns = {}
    with open(os.path.join(root, "version.py"), encoding="utf-8") as f:
        exec(f.read(), ns)
    return ns.get("VERSION", "?")


def main(root=ROOT):
    data = {"version": version(root), "files": files(root)}
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    print("manifest.json: {} files, version {}".format(len(data["files"]), data["version"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT)
