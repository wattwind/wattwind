"""Captive-portal DNS for the access point: every name resolves to the fan, so a phone that joins
WattWind-XXXX finds its "is there internet?" check answered by the fan and opens the page by itself.

Runs only while the access point is up (started and stopped by wifi.py). reply() is pure Python and
host-tested.
"""
import asyncio
import socket

PORT = 53
TTL_S = 60


def reply(query, ip):
    """DNS answer for `query` (bytes): an A record pointing at `ip` for IPv4 lookups, an empty answer
    for anything else (so phones fall back to IPv4). None for packets that aren't plain queries."""
    if len(query) < 12 or query[2] & 0x80 or (query[2] >> 3) & 0x0F:   # a response, or not a standard query
        return None
    if query[4] != 0 or query[5] != 1:                                 # exactly one question
        return None
    i = 12
    while i < len(query) and query[i] != 0:                            # walk the name labels
        if query[i] & 0xC0:
            return None
        i += query[i] + 1
    end = i + 5                                                        # zero byte + type + class
    if end > len(query):
        return None
    qtype = (query[i + 1] << 8) | query[i + 2]
    answer = qtype in (1, 255)                                         # A or ANY
    head = query[0:2] + b"\x81\x80" + b"\x00\x01" + (b"\x00\x01" if answer else b"\x00\x00") + b"\x00\x00\x00\x00"
    out = head + query[12:end]
    if answer:
        out += b"\xc0\x0c\x00\x01\x00\x01" + TTL_S.to_bytes(4, "big") + b"\x00\x04" + bytes(int(p) for p in ip.split("."))
    return out


async def serve(ip, log=print):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", PORT))
        s.setblocking(False)
        log("captive DNS on port", PORT, "->", ip)
        while True:
            try:
                data, addr = s.recvfrom(512)
            except OSError:                      # nothing waiting
                await asyncio.sleep_ms(50)
                continue
            try:
                out = reply(data, ip)
                if out:
                    s.sendto(out, addr)
            except Exception as e:               # one bad packet must not stop the server
                log("captive DNS: bad packet", repr(e))
            await asyncio.sleep_ms(0)
    finally:
        s.close()
