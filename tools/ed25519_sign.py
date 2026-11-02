"""Ed25519 signing (RFC 8032) for release updates, on the PC only. Uses the fan's own point arithmetic
(firmware/ed25519.py) and Python's SHA-512, so signing and the fan's check share one curve implementation.
Pure Python, no extra packages. Signatures are deterministic: no random numbers needed when signing."""

# The point arithmetic below (here: _secret, public_key, sign; the curve in firmware/ed25519.py) follows the reference code in RFC 8032, section 6
# (Josefsson, Liusvaara, 2017), which carries this notice:
#
# Copyright (c) 2017 IETF Trust and the persons identified as authors of the code. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
# - Redistributions of source code must retain the above copyright notice, this list of conditions and the following
#   disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
#   following disclaimer in the documentation and/or other materials provided with the distribution.
# - Neither the name of Internet Society, IETF or IETF Trust, nor the names of specific contributors, may be used to
#   endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The SHA-512 is written from FIPS 180-4. The rest of the project is MIT (see LICENSE).
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware"))
import ed25519 as _e  # noqa: E402


def _encode(P):
    zi = pow(P[2], _e._P - 2, _e._P)
    x, y = P[0] * zi % _e._P, P[1] * zi % _e._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _secret(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """32-byte public key from the 32-byte private seed."""
    if len(seed) != 32:
        raise ValueError("the private key is 32 bytes")
    return _encode(_e._mul(_secret(seed)[0], _e._G))


def sign(seed, msg):
    """64-byte signature of msg."""
    a, prefix = _secret(seed)
    A = _encode(_e._mul(a, _e._G))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _e._Q
    R = _encode(_e._mul(r, _e._G))
    k = int.from_bytes(hashlib.sha512(R + A + msg).digest(), "little") % _e._Q
    return R + ((r + k * a) % _e._Q).to_bytes(32, "little")


def key_path():
    """Where the release key lives: $WATTWIND_SIGNING_KEY, or the path in tools/signing_key_path.txt (one line,
    git-ignored, so a personal folder never ends up in the repo)."""
    p = os.environ.get("WATTWIND_SIGNING_KEY")
    if not p:
        f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signing_key_path.txt")
        if os.path.exists(f):
            p = open(f, encoding="utf-8").read().strip()
    if not p:
        raise SystemExit("No signing key location: put its path in tools/signing_key_path.txt (one line, git-ignored)\n"
                         "or set WATTWIND_SIGNING_KEY. A new key: python tools/make_keys.py")
    return p


def load_seed(path=None):
    path = path or key_path()
    try:
        seed = bytes.fromhex(open(path, encoding="ascii").read().strip())
    except OSError:
        raise SystemExit("Signing key not found: {}\n(a new one: python tools/make_keys.py)".format(path))
    if len(seed) != 32:
        raise SystemExit("Signing key file damaged: {}".format(path))
    return seed
