"""Host stand-in for MicroPython's cryptolib (AES-128, ECB and CBC), so link.py runs under CPython in the tests.
Plain FIPS-197 AES, slow and only for tests; checked against the NIST SP 800-38A vector in test_link.py, the same
vector the Pico's cryptolib passed (checked on a Pico 2 W, 2026-10-31)."""


def _xt(a):
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _make_sbox():
    sbox = [0] * 256
    for x in range(256):
        inv = 0
        if x:
            for y in range(1, 256):
                if _mul(x, y) == 1:
                    inv = y
                    break
        s = inv
        for i in range(1, 5):
            s ^= ((inv << i) | (inv >> (8 - i))) & 0xFF
        sbox[x] = s ^ 0x63
    return sbox


SBOX = _make_sbox()
INV = [0] * 256
for _i, _v in enumerate(SBOX):
    INV[_v] = _i


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _add(s, k):
    return [a ^ b for a, b in zip(s, k)]


def _shift(s, inv=False):
    out = [0] * 16
    for c in range(4):
        for r in range(4):
            src = (c + r) % 4 if not inv else (c - r) % 4
            out[c * 4 + r] = s[src * 4 + r]
    return out


def _mix(s, inv=False):
    m = (14, 11, 13, 9) if inv else (2, 3, 1, 1)
    out = []
    for c in range(4):
        col = s[c * 4:c * 4 + 4]
        for r in range(4):
            out.append(_mul(col[0], m[(0 - r) % 4]) ^ _mul(col[1], m[(1 - r) % 4])
                       ^ _mul(col[2], m[(2 - r) % 4]) ^ _mul(col[3], m[(3 - r) % 4]))
    return out


def _enc_block(rk, b):
    s = _add(list(b), rk[0])
    for r in range(1, 10):
        s = _add(_mix(_shift([SBOX[x] for x in s])), rk[r])
    return bytes(_add(_shift([SBOX[x] for x in s]), rk[10]))


def _dec_block(rk, b):
    s = _add(list(b), rk[10])
    for r in range(9, 0, -1):
        s = _mix(_add([INV[x] for x in _shift(s, True)], rk[r]), True)
    return bytes(_add([INV[x] for x in _shift(s, True)], rk[0]))


class aes:
    """cryptolib.aes(key, mode, iv): mode 1 = ECB, 2 = CBC. Like the Pico's: one object per message direction,
    data a multiple of 16 bytes."""

    def __init__(self, key, mode, iv=None):
        if len(key) != 16 or mode not in (1, 2):
            raise ValueError("mode")
        self.rk = _expand(bytes(key))
        self.mode = mode
        self.prev = bytes(iv) if iv is not None else bytes(16)

    def encrypt(self, data):
        if len(data) % 16:
            raise ValueError("blksize")
        out = b""
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            if self.mode == 2:
                blk = bytes(a ^ b for a, b in zip(blk, self.prev))
            c = _enc_block(self.rk, blk)
            self.prev = c
            out += c
        return out

    def decrypt(self, data):
        if len(data) % 16:
            raise ValueError("blksize")
        out = b""
        for i in range(0, len(data), 16):
            c = data[i:i + 16]
            p = _dec_block(self.rk, c)
            if self.mode == 2:
                p = bytes(a ^ b for a, b in zip(p, self.prev))
            self.prev = c
            out += p
        return out
