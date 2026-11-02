import asyncio
import hashlib
import hmac
import importlib
import json

import pytest

import config
import link
import state
import web
from conftest import FIRMWARE
from microdot_test_client import TestClient

KEY = "0123456789abcdef0123456789abcdef"


def info(seq=1, boot="b1", lvl=2, fid="WattWind-AAAA"):
    return {"id": fid, "name": "wattwind", "boot": boot, "seq": seq, "lvl": lvl, "hr": 140, "pw": 210, "cad": 88,
            "hrc": True, "pwc": True}


# ---- signing and parsing ------------------------------------------------------------------------

def test_hmac_matches_python():
    for key, msg in ((b"k", b"hello"), (b"x" * 100, b"long key"), (KEY.encode(), b"")):
        assert link.hmac_sha256(key, msg) == hmac.new(key, msg, hashlib.sha256).digest()


NIST_KEY = "2b7e151628aed2a6abf7158809cf4f3c"      # NIST SP 800-38A F.2.1, AES-128-CBC
NIST_IV = "000102030405060708090a0b0c0d0e0f"
NIST_PT = ("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51"
           "30c81c46a35ce411e5fbc1191a0a52ef" "f69f2445df4f9b17ad2b417be66c3710")
NIST_CT = ("7649abac8119b246cee98e9b12e9197d" "5086cb9b507219ee95db113a917678b2"
           "73bed6b8e3c1743b7116e69e22229516" "3ff1caa1681fac09120eca307586e1a7")


def test_aes_standin_matches_nist():
    """The host stand-in computes the same AES as the Pico's cryptolib (which passed this vector on the fan)."""
    import binascii
    import cryptolib
    h = binascii.unhexlify
    assert cryptolib.aes(h(NIST_KEY), 2, h(NIST_IV)).encrypt(h(NIST_PT)) == h(NIST_CT)
    assert cryptolib.aes(h(NIST_KEY), 2, h(NIST_IV)).decrypt(h(NIST_CT)) == h(NIST_PT)


def test_pack_and_open():
    u = link.unpack(link.pack(KEY, info()))
    assert u[2] == {"id": "WattWind-AAAA", "name": "wattwind"}           # readable: only id and name
    got = link.open_packet(KEY, u)
    assert got["lvl"] == 2 and got["hr"] == 140 and got["seq"] == 1 and got["id"] == "WattWind-AAAA"
    assert link.open_packet("other-key", u) is None and link.open_packet("", u) is None


def test_values_are_not_readable_on_the_network():
    a, b = link.pack(KEY, info()), link.pack(KEY, info())
    for word in (b'"lvl"', b'"hr": 140', b'"pw": 210', b'"boot"', b'"seq"'):   # the JSON fields, not bare digits:
        assert word not in a                                                  # hex ciphertext can hold "210" by chance
    assert a != b                                       # a fresh IV every packet: the same values look different


def test_unpack_rejects_foreign_packets():
    assert link.unpack(b"hello") is None
    assert link.unpack(b"WW1 abc notjson") is None
    assert link.unpack(b"WW1 abc " + json.dumps({"no": "id"}).encode()) is None
    assert link.unpack(b"WW2 abc zz 00 {}") is None
    assert link.unpack(b"WW2 abc 00 00") is None


def test_tampered_packet_fails():
    pkt = link.pack(KEY, info(lvl=1))
    head, mac, iv, ct, pub = pkt.split(b" ", 4)
    flip = lambda hx: (b"0" if hx[:1] != b"0" else b"1") + hx[1:]
    for bad in (b" ".join((head, mac, flip(iv), ct, pub)), b" ".join((head, mac, iv, flip(ct), pub)),
                b" ".join((head, mac, iv, ct, pub.replace(b"wattwind", b"evilfan1")))):
        assert link.open_packet(KEY, link.unpack(bad)) is None


def test_old_leader_is_listed_but_not_followed():
    old = b"WW1 0123 " + json.dumps(info()).encode()                      # a leader on 0.9.49 or older
    lst = link.Listener("WattWind-ME00")
    assert lst.receive(old, "ip", 1, "WattWind-AAAA", KEY) is None
    assert [h["id"] for h in lst.heard(1)] == ["WattWind-AAAA"] and not lst.unpaired(1)


def test_packet_fits_the_receive_buffer():
    big = info(seq=10 ** 9, boot="ffffffff")
    big.update(hr=255, pw=2000, cad=200, name="x" * 32)
    assert len(link.pack(KEY, big)) < 700


# ---- listener -------------------------------------------------------------------------------------

def test_listener_lists_leaders_and_forgets_them():
    lst = link.Listener("WattWind-ME00")
    lst.receive(link.pack("anykey", info()), "192.168.1.20", 100)
    lst.receive(link.pack("k", info(fid="WattWind-ME00")), "192.168.1.21", 100)   # its own broadcast
    heard = lst.heard(101)
    assert [h["id"] for h in heard] == ["WattWind-AAAA"] and heard[0]["ip"] == "192.168.1.20"
    assert lst.heard(100 + link.FORGET_S + 1) == []


def test_listener_accepts_only_the_followed_leader_with_its_key():
    lst = link.Listener("WattWind-ME00")
    assert lst.receive(link.pack(KEY, info()), "ip", 1) is None                         # not following
    assert lst.receive(link.pack(KEY, info()), "ip", 1, "WattWind-BBBB", KEY) is None   # another leader
    assert lst.receive(link.pack("wrong", info()), "ip", 1, "WattWind-AAAA", KEY) is None
    assert lst.receive(link.pack(KEY, info()), "ip", 1, "WattWind-AAAA", KEY)["lvl"] == 2


def test_listener_rejects_replays_but_takes_a_restarted_leader():
    lst = link.Listener("WattWind-ME00")
    rx = lambda seq, boot="b1": lst.receive(link.pack(KEY, info(seq, boot)), "ip", 1, "WattWind-AAAA", KEY)
    assert rx(5) is not None
    assert rx(5) is None and rx(4) is None         # same or older packet again
    assert rx(6) is not None
    assert rx(1, boot="b2") is not None            # leader restarted: new boot id, counting from 1


def test_new_key_is_random_hex():
    k1, k2 = link.new_key(), link.new_key()
    assert len(k1) == 32 and int(k1, 16) >= 0 and k1 != k2


def test_listener_notices_a_leader_with_a_new_key():
    lst = link.Listener("WattWind-ME00")
    rx = lambda key, seq, now: lst.receive(link.pack(key, info(seq)), "ip", now, "WattWind-AAAA", KEY)
    assert rx(KEY, 1, 10) is not None and not lst.unpaired(10)
    assert rx("newkey", 2, 11) is None and lst.unpaired(11)          # leader pressed Unpair all followers
    assert not lst.unpaired(11 + link.STALE_S + 1)                    # leader gone altogether
    lst.receive(link.pack("anykey", info(fid="WattWind-BBBB")), "ip", 12, "WattWind-AAAA", KEY)
    assert lst.unpaired(12)                                           # another leader doesn't change it
    assert rx(KEY, 3, 13) is not None and not lst.unpaired(13)        # paired again


# ---- same-level following ------------------------------------------------------------------------

def test_follow_level_offset_and_clamp():
    f = link.FollowLevel()
    assert f.update(0, 3) == 3
    assert f.update(1, 3, -1) == 2
    assert f.update(2, 1, -2) == 0
    assert f.update(3, 0) == 0
    assert f.update(4, 1, 1) == 2 and f.update(5, 3, 1) == 3       # one higher, clamped at 3
    assert f.update(6, 0, 1) == 0                                  # leader off: off, also one higher


def test_follow_level_holds_then_steps_down_and_recovers():
    f = link.FollowLevel()
    f.update(0, 3)
    assert f.update(10, None) == 3                              # leader silent: hold
    assert f.update(10 + link.HOLD_S - 1, None) == 3
    assert f.update(10 + link.HOLD_S, None) == 2                # then one level down per STEP_S
    assert f.update(10 + link.HOLD_S + link.STEP_S - 1, None) == 2
    assert f.update(10 + link.HOLD_S + link.STEP_S, None) == 1
    assert f.update(10 + link.HOLD_S + 2 * link.STEP_S, None) == 0
    assert f.update(10 + link.HOLD_S + 9 * link.STEP_S, None) == 0
    assert f.update(1000, 2) == 2                               # heard again: follows at once


# ---- web API ----------------------------------------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    importlib.reload(state)
    monkeypatch.chdir(FIRMWARE)
    cfg = dict(config.DEFAULTS, link_key=KEY, hostname="wattwind2")
    saved = []
    client = TestClient(web.create_app(cfg, save=lambda c: saved.append(dict(c))), host="wattwind2.local")
    state.link_id = "WattWind-ME00"
    state.auto_available = True
    return cfg, saved, client


def run(coro):
    return asyncio.run(coro)


def post(client, path, body):
    return run(client.post(path, body=body))


def test_key_only_while_pairing_is_open(env):
    cfg, _, client = env
    assert run(client.get("/api/link/key")).status_code == 403
    assert post(client, "/api/link/pair", {}).json["pair_left_s"] == link.PAIR_S
    r = run(client.get("/api/link/key"))
    assert r.status_code == 200 and r.json == {"id": "WattWind-ME00", "name": "wattwind2", "key": KEY}
    state.uptime_s += link.PAIR_S
    assert run(client.get("/api/link/key")).status_code == 403


def test_pairing_needs_the_pin_and_a_leader(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/link/pair", {}).status_code == 403
    assert post(client, "/api/link/pair", {"pin": "1234"}).status_code == 200
    cfg["follow_id"] = "WattWind-AAAA"
    assert post(client, "/api/link/pair", {"pin": "1234"}).status_code == 409


def test_keys_never_in_config_or_status(env):
    cfg, _, client = env
    cfg["follow_key"] = "secret"
    c = run(client.get("/api/config")).json
    assert "link_key" not in c and "follow_key" not in c
    assert KEY not in run(client.get("/api/status")).text


def test_follow_fetches_the_key_and_restarts(env, monkeypatch):
    cfg, saved, client = env
    state.leaders_heard = [{"id": "WattWind-AAAA", "name": "wattwind", "ip": "192.168.1.20", "age_s": 0}]
    asked = []

    async def fake_fetch(ip):
        asked.append(ip)
        return 200, {"id": "WattWind-AAAA", "name": "wattwind", "key": KEY}
    monkeypatch.setattr(link, "fetch_key", fake_fetch)
    r = post(client, "/api/follow", {"id": "WattWind-AAAA", "mode": "same", "offset": -1})
    assert r.status_code == 200 and r.json["reboot"] and asked == ["192.168.1.20"]
    assert cfg["follow_id"] == "WattWind-AAAA" and cfg["follow_key"] == KEY and cfg["follow_offset"] == -1
    assert state.reboot_requested and state.mode == "follow" and saved


def test_follow_refused_when_pairing_closed_or_not_heard(env, monkeypatch):
    cfg, _, client = env
    assert post(client, "/api/follow", {"id": "WattWind-AAAA"}).status_code == 404
    state.leaders_heard = [{"id": "WattWind-AAAA", "name": "wattwind", "ip": "192.168.1.20", "age_s": 0}]

    async def closed(ip):
        return 403, {"error": "pairing is not open"}
    monkeypatch.setattr(link, "fetch_key", closed)
    r = post(client, "/api/follow", {"id": "WattWind-AAAA"})
    assert r.status_code == 409 and "Pair a new fan" in r.json["error"] and cfg["follow_id"] == ""
    assert post(client, "/api/follow", {"id": "WattWind-ME00"}).status_code == 400          # itself
    assert post(client, "/api/follow", {"id": "WattWind-AAAA", "mode": "x"}).status_code == 400
    assert post(client, "/api/follow", {"id": "WattWind-AAAA", "offset": 2}).status_code == 400


def test_change_mode_live_and_stop_following(env):
    cfg, _, client = env
    web.set_follow(cfg, "WattWind-AAAA", "wattwind", KEY, "same", 0)
    assert state.mode == "follow"
    r = post(client, "/api/follow", {"id": "WattWind-AAAA", "mode": "own", "offset": 0})
    assert r.status_code == 200 and state.mode == "auto" and not state.reboot_requested   # live, no restart
    post(client, "/api/follow", {"id": "WattWind-AAAA", "mode": "same", "offset": -1})
    assert state.mode == "follow" and r.status_code == 200
    r = post(client, "/api/follow", {"id": ""})
    assert r.json["reboot"] and cfg["follow_id"] == "" and state.follow is None and state.mode == "auto"


def test_follow_button_and_manual_override(env):
    cfg, _, client = env
    web.set_follow(cfg, "WattWind-AAAA", "wattwind", KEY, "same", 0)
    post(client, "/api/mode", {"mode": "manual", "level": 2})
    assert state.mode == "manual"
    post(client, "/api/mode", {"mode": "auto"})                 # the page's Follow button
    assert state.mode == "follow"
    post(client, "/api/mode", {"mode": "manual", "level": 1})
    assert post(client, "/api/mode", {"mode": "follow"}).json["mode"] == "follow"
    web.set_follow(cfg)
    assert post(client, "/api/mode", {"mode": "follow"}).status_code == 400   # not a follower


def test_status_shows_the_followed_leader(env):
    cfg, _, client = env
    web.set_follow(cfg, "WattWind-AAAA", "wattwind", KEY, "same", -1)
    state.follow_fresh, state.leader_level = True, 3
    s = run(client.get("/api/status")).json
    assert s["follow"] == {"id": "WattWind-AAAA", "name": "wattwind", "mode": "same", "offset": -1,
                           "fresh": True, "leader_level": 3, "unpaired": False}
    assert s["link_id"] == "WattWind-ME00"


def test_unpair_all_gives_the_leader_a_new_key(env):
    cfg, saved, client = env
    cfg["settings_pin"] = "1234"
    post(client, "/api/link/pair", {"pin": "1234"})
    assert post(client, "/api/link/unpair", {}).status_code == 403
    r = post(client, "/api/link/unpair", {"pin": "1234"})
    assert r.status_code == 200 and cfg["link_key"] != KEY and len(cfg["link_key"]) == 32 and saved
    assert run(client.get("/api/link/key")).status_code == 403     # the pairing window closed too
    assert cfg["link_key"] not in run(client.get("/api/status")).text
    cfg["follow_id"] = "WattWind-AAAA"
    assert post(client, "/api/link/unpair", {"pin": "1234"}).status_code == 409


def test_pair_again_fetches_the_new_key_without_a_restart(env, monkeypatch):
    cfg, _, client = env
    web.set_follow(cfg, "WattWind-AAAA", "wattwind", "oldkey", "same", -1)
    state.leaders_heard = [{"id": "WattWind-AAAA", "name": "wattwind", "ip": "192.168.1.20", "age_s": 0}]

    async def fake_fetch(ip):
        return 200, {"id": "WattWind-AAAA", "name": "wattwind", "key": KEY}
    monkeypatch.setattr(link, "fetch_key", fake_fetch)
    r = post(client, "/api/follow", {"id": "WattWind-AAAA", "pair": True, "mode": "same", "offset": -1})
    assert r.status_code == 200 and not state.reboot_requested
    assert cfg["follow_key"] == KEY and cfg["follow_offset"] == -1 and state.mode == "follow"

    async def closed(ip):
        return 403, {"error": "pairing is not open"}
    monkeypatch.setattr(link, "fetch_key", closed)
    r = post(client, "/api/follow", {"id": "WattWind-AAAA", "pair": True})
    assert r.status_code == 409 and cfg["follow_key"] == KEY
