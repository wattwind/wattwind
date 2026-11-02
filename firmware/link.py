"""Linked fans: one leader with the sensors, any number of followers on the same home network.

Leader (a fan with its own sensors): once per second one UDP broadcast with its id, name, heart rate, power,
cadence and running fan level: id and name readable, the rest encrypted (AES-128-CBC), all signed (HMAC-SHA256),
both keys from its link key. Every fan listens and keeps a list of
the leaders it hears (shown on the page). A follower (config follow_id set) uses no Bluetooth and doesn't
broadcast:
- "same": its level follows the leader's running level (+ follow_offset), whatever mode the leader is in;
- "own":  the leader's heart rate / power / cadence feed its own Auto logic (its own settings).
No packet for STALE_S = sensor loss: FollowLevel holds the level, then steps down to off; "own" sees no data.
The key reaches a follower once, by pairing: "Pair a new fan" on the leader opens PAIR_S seconds in which
GET /api/link/key answers. "Unpair all followers" gives the leader a new key: its followers then hear packets
they can't verify (Listener.unpaired), hold, step down to off, and offer "Pair again". Followers never send
anything, so a leader doesn't know its followers (by design: they are in the same room; their own page shows
whether they hear the leader). The network only delivers numbers; relays stay with the control task in main.py.
The pure parts (signing, parsing, Listener, FollowLevel) are host-tested (tests/test_link.py).
"""
import binascii
import hashlib
import json

PORT = 47800             # UDP, broadcast on the home network
MAGIC = b"WW2"           # WW1 (0.9.49 and older): signed, readable; WW2: signed and encrypted
OLD_MAGIC = b"WW1"
MAC_LEN = 32             # hex characters of the HMAC kept in a packet (128 bits)
STALE_S = 5              # follower: leader data older than this counts as missing
FORGET_S = 15            # leaders not heard for this long leave the list
HOLD_S = 60              # same level, leader silent: hold the level this long, ...
STEP_S = 60              # ... then one level down per STEP_S until off
PAIR_S = 60              # leader: pairing window after "Pair a new fan"
OFFSETS = (1, 0, -1, -2) # same level: follow the leader's level, 1 higher, or 1 / 2 lower (leader off = off)
MODES = ("same", "own")


def hmac_sha256(key, msg):
    """HMAC-SHA256 (RFC 2104); MicroPython has hashlib but no hmac module."""
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (64 - len(key))
    inner = hashlib.sha256(bytes(b ^ 0x36 for b in key))
    inner.update(msg)
    outer = hashlib.sha256(bytes(b ^ 0x5C for b in key))
    outer.update(inner.digest())
    return outer.digest()


def mac(key, body):
    return binascii.hexlify(hmac_sha256(key.encode(), body)).decode()[:MAC_LEN]


def _aes_key(key):
    """The AES key, derived from the link key, so signing and encrypting never use the same key."""
    return hmac_sha256(key.encode(), b"WattWind link AES-128")[:16]


def _encrypt(key, data):
    """AES-128-CBC with a fresh random IV (cryptolib: mbedTLS in MicroPython; a stand-in in the host tests)."""
    import os
    import cryptolib
    n = 16 - len(data) % 16
    iv = os.urandom(16)
    return iv, cryptolib.aes(_aes_key(key), 2, iv).encrypt(data + bytes([n]) * n)    # PKCS#7 padding


def _decrypt(key, iv, ct):
    import cryptolib
    if len(iv) != 16 or not ct or len(ct) % 16:
        return None
    data = cryptolib.aes(_aes_key(key), 2, iv).decrypt(ct)
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        return None
    return data[:-n]


def pack(key, info):
    """info dict -> packet b"WW2 <mac> <iv> <secret> <public json>". Public: id and name only (every fan lists
    the leaders it hears, also before pairing). Secret, AES-128-CBC: everything else (level, heart rate, power,
    cadence, boot and sequence). The mac (HMAC-SHA256, encrypt-then-MAC) covers iv, secret and public part."""
    public = json.dumps({"id": info["id"], "name": info.get("name", "")}).encode()
    secret = json.dumps({k: v for k, v in info.items() if k not in ("id", "name")}).encode()
    iv, ct = _encrypt(key, secret)
    signed = binascii.hexlify(iv) + b" " + binascii.hexlify(ct) + b" " + public
    return MAGIC + b" " + mac(key, signed).encode() + b" " + signed


def unpack(packet):
    """packet -> (mac str, signed bytes, public dict, iv, ct), or None if it isn't one of ours. A WW1 packet
    (a leader on old firmware) gives iv = ct = None: it is listed, but can't be followed."""
    if packet.startswith(OLD_MAGIC + b" "):
        parts = packet.split(b" ", 2)
        if len(parts) != 3:
            return None
        pub, iv, ct = parts[2], None, None
    elif packet.startswith(MAGIC + b" "):
        parts = packet.split(b" ", 4)
        if len(parts) != 5:
            return None
        pub = parts[4]
        try:
            iv, ct = binascii.unhexlify(parts[2]), binascii.unhexlify(parts[3])
        except ValueError:
            return None
    else:
        return None
    try:
        info = json.loads(pub)
        m = parts[1].decode()
    except (ValueError, UnicodeError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("id"), str):
        return None
    signed = None if iv is None else packet.split(b" ", 2)[2]
    return m, signed, info, iv, ct


def open_packet(key, u):
    """The unpacked packet's data (public + decrypted part) if it is WW2 and signed with this key, else None.
    The signature is checked before anything is decrypted."""
    m, signed, info, iv, ct = u
    if iv is None or not key or mac(key, signed) != m:
        return None
    data = _decrypt(key, iv, ct)
    if data is None:
        return None
    try:
        secret = json.loads(data)
    except ValueError:
        return None
    if not isinstance(secret, dict):
        return None
    secret.update(info)
    return secret


def new_key():
    """A fresh random link key (32 hex characters)."""
    import os
    return binascii.hexlify(os.urandom(16)).decode()


class Listener:
    """Every packet heard: keeps the list of leaders; returns the data of the followed leader if it is
    signed with the follower's key and newer than the last one (no replays)."""

    def __init__(self, my_id):
        self.my_id = my_id
        self.leaders = {}          # id -> {"name", "ip", "seen_s"}
        self.last = (None, -1)     # (boot, seq) of the last accepted packet
        self.bad_s = None          # followed leader heard with a signature the key doesn't match (unpaired)

    def receive(self, packet, ip, now_s, follow_id="", follow_key=""):
        u = unpack(packet)
        if u is None:
            return None
        info = u[2]
        fid = info["id"]
        if fid == self.my_id:
            return None
        self.leaders[fid] = {"name": str(info.get("name", ""))[:32], "ip": ip, "seen_s": now_s}
        if not follow_id or fid != follow_id:
            return None
        if u[3] is None:
            return None            # WW1: the leader runs old firmware (0.9.49 or older): update both fans
        info = open_packet(follow_key, u)
        if info is None:
            self.bad_s = now_s     # the leader is there, but with another key: it unpaired its followers
            return None
        boot, seq = info.get("boot"), info.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            return None
        if boot == self.last[0] and seq <= self.last[1]:
            return None            # replayed or out of order
        self.last = (boot, seq)
        self.bad_s = None
        return info

    def unpaired(self, now_s):
        """The followed leader is heard, but its packets don't match this fan's key (recently)."""
        return self.bad_s is not None and now_s - self.bad_s <= STALE_S

    def heard(self, now_s):
        for fid in [k for k, v in self.leaders.items() if now_s - v["seen_s"] > FORGET_S]:
            del self.leaders[fid]
        return [{"id": k, "name": v["name"], "ip": v["ip"], "age_s": now_s - v["seen_s"]}
                for k, v in sorted(self.leaders.items())]


class FollowLevel:
    """Same-level following: the leader's level + offset (0..3); the leader off is off for every offset, so
    "one higher" never runs a fan the leader has stopped. Leader silent (None): hold HOLD_S, then
    one level down every STEP_S until off; the next packet takes over again at once."""

    def __init__(self):
        self.level = 0
        self.lost_s = None
        self.next_step_s = None

    def update(self, now_s, leader_level, offset=0):
        if leader_level is not None:
            self.lost_s = None
            self.level = 0 if leader_level <= 0 else max(0, min(3, leader_level + offset))
            return self.level
        if self.lost_s is None:
            self.lost_s = now_s
            self.next_step_s = now_s + HOLD_S
        if self.level > 0 and now_s >= self.next_step_s:
            self.level -= 1
            self.next_step_s = now_s + STEP_S
        return self.level


# ------------------------------------------------------------------ on the Pico (not host-tested)

def my_id():
    """WattWind-XXXX, the same name as the fan's access point (last 4 hex digits of the MAC)."""
    import network
    mac_b = network.WLAN(network.STA_IF).config("mac")
    return "WattWind-" + binascii.hexlify(mac_b[-2:]).decode().upper()


async def fetch_key(ip, timeout_s=5):
    """GET http://<ip>/api/link/key from a leader. -> (status, dict)."""
    import asyncio
    reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 80), timeout_s)
    try:
        writer.write(("GET /api/link/key HTTP/1.0\r\nHost: %s\r\n\r\n" % ip).encode())
        await writer.drain()
        data = b""
        while len(data) < 4096:
            chunk = await asyncio.wait_for(reader.read(512), timeout_s)
            if not chunk:
                break
            data += chunk
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    code = int(head.split(b" ")[1])
    return code, json.loads(body)


def _broadcast_addr():
    """Directed broadcast of the home network (e.g. 192.168.1.255), from the station's address."""
    import network
    ip, mask = network.WLAN(network.STA_IF).ifconfig()[:2]
    a = [int(x) for x in ip.split(".")]
    m = [int(x) for x in mask.split(".")]
    return ".".join(str(a[i] | (255 - m[i])) for i in range(4))


def _open_socket():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    if hasattr(socket, "SO_BROADCAST"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass
    s.bind(("0.0.0.0", PORT))
    s.setblocking(False)
    return s


def _apply(info, cfg, state, name):
    """Data from the followed leader -> state. The sensor values are taken in both modes: "own" decides with
    them, "same" shows them on its screen (its level comes from the leader's level only)."""
    state.leader_seen_s = state.uptime_s
    try:
        import detail
        detail.rec().count_leader()       # packets per minute in the detailed recording
    except Exception:
        pass
    lvl = info.get("lvl")
    state.leader_level = lvl if isinstance(lvl, int) and 0 <= lvl <= 3 else None
    state.hr = info.get("hr")
    state.power = info.get("pw")
    state.cadence = info.get("cad")
    state.hr_connected = bool(info.get("hrc"))
    state.power_connected = bool(info.get("pwc"))
    state.hr_name = state.power_name = "via " + name


def _expire(cfg, state):
    """Followed leader silent for STALE_S: its data counts as missing."""
    fresh = state.leader_seen_s is not None and state.uptime_s - state.leader_seen_s <= STALE_S
    if not fresh:
        state.leader_level = None
        state.hr = state.power = state.cadence = None
        state.hr_connected = state.power_connected = False
    return fresh


async def run(cfg):
    """Leader: broadcast once per second. Everyone: listen (list of leaders; a follower takes its leader's
    data). Only while on the home network (state.wifi_mode == "sta")."""
    import asyncio
    import os
    import config
    import state
    if not cfg.get("link_key"):
        cfg["link_key"] = new_key()
        config.save(cfg)
    state.link_id = my_id()
    lst = Listener(state.link_id)
    boot = binascii.hexlify(os.urandom(4)).decode()
    seq = 0
    sock = None
    bcast = "255.255.255.255"
    next_send = 0
    was_fresh = None
    following = bool(cfg.get("follow_id"))
    name = cfg.get("follow_name") or cfg.get("follow_id", "")
    while True:
        if state.wifi_mode != "sta":
            if sock:
                sock.close()
                sock = None
        else:
            if sock is None:
                sock = _open_socket()
            for _ in range(10):                       # drain what arrived
                try:
                    data, addr = sock.recvfrom(700)
                except OSError:
                    break
                info = lst.receive(data, addr[0], state.uptime_s, cfg.get("follow_id", ""), cfg.get("follow_key", ""))
                if info is not None:
                    _apply(info, cfg, state, name)
            if not following and state.uptime_s >= next_send:
                next_send = state.uptime_s + 1
                seq += 1
                pkt = pack(cfg["link_key"], {
                    "id": state.link_id, "name": cfg.get("hostname", ""), "boot": boot, "seq": seq,
                    "lvl": state.level, "hr": state.hr, "pw": state.power, "cad": state.cadence,
                    "hrc": state.hr_connected, "pwc": state.power_connected})
                try:
                    sock.sendto(pkt, (bcast, PORT))
                except OSError:
                    bcast = _broadcast_addr()       # some stacks refuse 255.255.255.255
        state.leaders_heard = lst.heard(state.uptime_s)
        if following:
            fresh = _expire(cfg, state)
            state.follow_fresh = fresh
            state.follow_unpaired = not fresh and lst.unpaired(state.uptime_s)
            if fresh != was_fresh:
                if was_fresh is not None:
                    try:
                        import logbook
                        logbook.write("up={} leader {} {}".format(state.uptime_s, name, "heard" if fresh else "silent"))
                    except Exception:
                        pass
                was_fresh = fresh
        await asyncio.sleep_ms(100)
