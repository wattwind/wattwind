"""Ed25519 signature check (RFC 8032) for signed firmware updates (updater.verified_manifest). Pure Python: MicroPython
has no SHA-512, so it brings its own. About 1 s per check on a Pico 2 W (measured), once per update. Verify only:
no secret ever lives on the fan; the private key stays with whoever makes the releases (tools/make_keys.py)."""

# The point arithmetic below (_add, _mul, _x, _point, verify) follows the reference code in RFC 8032, section 6
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

_M = 0xFFFFFFFFFFFFFFFF
_H0 = (
    0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
    0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179)
_K = (
    0x428a2f98d728ae22, 0x7137449123ef65cd, 0xb5c0fbcfec4d3b2f, 0xe9b5dba58189dbbc,
    0x3956c25bf348b538, 0x59f111f1b605d019, 0x923f82a4af194f9b, 0xab1c5ed5da6d8118,
    0xd807aa98a3030242, 0x12835b0145706fbe, 0x243185be4ee4b28c, 0x550c7dc3d5ffb4e2,
    0x72be5d74f27b896f, 0x80deb1fe3b1696b1, 0x9bdc06a725c71235, 0xc19bf174cf692694,
    0xe49b69c19ef14ad2, 0xefbe4786384f25e3, 0x0fc19dc68b8cd5b5, 0x240ca1cc77ac9c65,
    0x2de92c6f592b0275, 0x4a7484aa6ea6e483, 0x5cb0a9dcbd41fbd4, 0x76f988da831153b5,
    0x983e5152ee66dfab, 0xa831c66d2db43210, 0xb00327c898fb213f, 0xbf597fc7beef0ee4,
    0xc6e00bf33da88fc2, 0xd5a79147930aa725, 0x06ca6351e003826f, 0x142929670a0e6e70,
    0x27b70a8546d22ffc, 0x2e1b21385c26c926, 0x4d2c6dfc5ac42aed, 0x53380d139d95b3df,
    0x650a73548baf63de, 0x766a0abb3c77b2a8, 0x81c2c92e47edaee6, 0x92722c851482353b,
    0xa2bfe8a14cf10364, 0xa81a664bbc423001, 0xc24b8b70d0f89791, 0xc76c51a30654be30,
    0xd192e819d6ef5218, 0xd69906245565a910, 0xf40e35855771202a, 0x106aa07032bbd1b8,
    0x19a4c116b8d2d0c8, 0x1e376c085141ab53, 0x2748774cdf8eeb99, 0x34b0bcb5e19b48a8,
    0x391c0cb3c5c95a63, 0x4ed8aa4ae3418acb, 0x5b9cca4f7763e373, 0x682e6ff3d6b2b8a3,
    0x748f82ee5defb2fc, 0x78a5636f43172f60, 0x84c87814a1f0ab72, 0x8cc702081a6439ec,
    0x90befffa23631e28, 0xa4506cebde82bde9, 0xbef9a3f7b2c67915, 0xc67178f2e372532b,
    0xca273eceea26619c, 0xd186b8c721c0c207, 0xeada7dd6cde0eb1e, 0xf57d4f7fee6ed178,
    0x06f067aa72176fba, 0x0a637dc5a2c898a6, 0x113f9804bef90dae, 0x1b710b35131c471b,
    0x28db77f523047d84, 0x32caab7b40c72493, 0x3c9ebe0a15c9bebc, 0x431d67c49c100d4c,
    0x4cc5d4becb3e42b6, 0x597f299cfc657e2a, 0x5fcb6fab3ad6faec, 0x6c44198c4a475817)


def _r(x, n):
    return ((x >> n) | (x << (64 - n))) & _M


def sha512(msg):
    h = list(_H0)
    ml = len(msg)
    msg = bytes(msg) + b"\x80" + b"\x00" * ((111 - ml) % 128) + (ml * 8).to_bytes(16, "big")
    for off in range(0, len(msg), 128):
        w = [int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "big") for i in range(16)]
        for i in range(16, 80):
            a, b = w[i - 15], w[i - 2]
            s0 = _r(a, 1) ^ _r(a, 8) ^ (a >> 7)
            s1 = _r(b, 19) ^ _r(b, 61) ^ (b >> 6)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & _M)
        a, b, c, d, e, f, g, hh = h
        for i in range(80):
            t1 = (hh + (_r(e, 14) ^ _r(e, 18) ^ _r(e, 41)) + ((e & f) ^ (~e & g)) + _K[i] + w[i]) & _M
            t2 = ((_r(a, 28) ^ _r(a, 34) ^ _r(a, 39)) + ((a & b) ^ (a & c) ^ (b & c))) & _M
            hh, g, f, e, d, c, b, a = g, f, e, (d + t1) & _M, c, b, a, (t1 + t2) & _M
        h = [(x + y) & _M for x, y in zip(h, (a, b, c, d, e, f, g, hh))]
    return b"".join(x.to_bytes(8, "big") for x in h)


_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _P
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C = 2 * P[3] * Q[3] * _D % _P
    D = 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 % _P == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _point(b):
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def verify(public, msg, sig):
    """True if sig (64 bytes) is a valid Ed25519 signature of msg by public (32 bytes)."""
    if len(public) != 32 or len(sig) != 64:
        return False
    A, R = _point(public), _point(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _Q:
        return False
    h = int.from_bytes(sha512(sig[:32] + public + msg), "little") % _Q
    P1, P2 = _mul(s, _G), _add(R, _mul(h, A))
    return (P1[0] * P2[2] - P2[0] * P1[2]) % _P == 0 and (P1[1] * P2[2] - P2[1] * P1[2]) % _P == 0
