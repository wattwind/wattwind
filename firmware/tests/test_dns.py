import dns


def query(name, qtype=1, flags=b"\x01\x00"):
    q = b"\x12\x34" + flags + b"\x00\x01\x00\x00\x00\x00\x00\x00"
    for part in name.split("."):
        q += bytes([len(part)]) + part.encode()
    return q + b"\x00" + qtype.to_bytes(2, "big") + b"\x00\x01"


def test_a_record_points_at_the_fan():
    r = dns.reply(query("connectivitycheck.gstatic.com"), "192.168.4.1")
    assert r[0:2] == b"\x12\x34"                  # same id
    assert r[2] & 0x80                            # a response
    assert r[6:8] == b"\x00\x01"                  # one answer
    assert r[-4:] == bytes([192, 168, 4, 1])


def test_ipv6_lookup_gets_no_answer():
    r = dns.reply(query("captive.apple.com", qtype=28), "192.168.4.1")
    assert r[6:8] == b"\x00\x00" and r.endswith(b"\x00\x1c\x00\x01")


def test_garbage_and_responses_are_ignored():
    assert dns.reply(b"\x00\x01", "192.168.4.1") is None
    assert dns.reply(query("a.b", flags=b"\x81\x80"), "192.168.4.1") is None
    assert dns.reply(query("a.b")[:-3], "192.168.4.1") is None
