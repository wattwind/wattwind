"""Make the release signing key pair (once). Writes:

- the PRIVATE key (32 random bytes, hex) to the path in tools/signing_key_path.txt or $WATTWIND_SIGNING_KEY:
  keep it outside the project, back it up once, never share it;
- the PUBLIC key into firmware/release_key.py: it ships with the firmware, and fans then install only Wi-Fi
  updates signed with the private key (tools/make_update.py signs).

Refuses to overwrite an existing key. A new key pair means: the next update goes to the fans over USB once (or is
signed with the old key and carries the new public key). Builders who change the firmware run this for their own
key: their fans then take their updates, and switching between makers is one USB install.

    python tools/make_keys.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ed25519_sign  # noqa: E402

RELEASE_KEY = os.path.join(HERE, "..", "firmware", "release_key.py")


def write_release_key(public, path=RELEASE_KEY):
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write('"""The public key of whoever makes this firmware\'s releases (tools/make_keys.py). Wi-Fi updates must be\n'
                'signed with the matching private key (updater.verified_manifest). Public: safe to publish."""\n'
                'KEY = "{}"\n'.format(public.hex()))


def main():
    path = ed25519_sign.key_path()
    if os.path.exists(path):
        raise SystemExit("A key already exists: {}\nNot overwritten. Delete it yourself if you really want a new one.".format(path))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    seed = os.urandom(32)
    with open(path, "w", encoding="ascii") as f:
        f.write(seed.hex() + "\n")
    public = ed25519_sign.public_key(seed)
    write_release_key(public)
    print("Private key: {}  (back it up once; never share it)".format(path))
    print("Public key:  firmware/release_key.py  ({}...)".format(public.hex()[:16]))
    print("Next: bump firmware/version.py, then tools/make_manifest.py and tools/make_update.py")


if __name__ == "__main__":
    main()
