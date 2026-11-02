"""Decoding of BLE sensor notifications. Pure Python: runs under CPython (tests/test_ble_parse.py).

Formats from the Bluetooth SIG specifications:
- Heart Rate Measurement 0x2A37 (Heart Rate Service 1.0)
- Cycling Power Measurement 0x2A63 (Cycling Power Service 1.1)
- Indoor Bike Data 0x2AD2 (Fitness Machine Service 1.0)
All multi-byte fields are little-endian.
"""

CRANK_STOP_MS = 3000   # no new crank revolution for this long = cadence 0


def _u16(b, i):
    return b[i] | (b[i + 1] << 8)


def _s16(b, i):
    v = _u16(b, i)
    return v - 0x10000 if v & 0x8000 else v


def parse_hr(data):
    """Heart Rate Measurement -> bpm, or None if malformed.

    Flags bit 0: 0 = uint8 value, 1 = uint16 value.
    """
    if len(data) < 2:
        return None
    if data[0] & 0x01:
        return _u16(data, 1) if len(data) >= 3 else None
    return data[1]


def parse_hr_full(data):
    """Heart Rate Measurement -> (bpm, contact, rr): contact True (skin contact) / False (no contact) / None (the
    sensor doesn't report it); rr = how many beat-to-beat (RR) intervals the message carries. (None, None, 0) if
    malformed. Flags: bit 0 uint16 value; bits 1-2 sensor contact (3 = detected, 2 = not detected, 0/1 = not
    supported); bit 3 energy expended (uint16) present; bit 4 RR intervals (uint16 each) follow."""
    if len(data) < 2:
        return None, None, 0
    f = data[0]
    if f & 0x01:
        if len(data) < 3:
            return None, None, 0
        bpm, i = _u16(data, 1), 3
    else:
        bpm, i = data[1], 2
    c = (f >> 1) & 0x03
    contact = True if c == 3 else (False if c == 2 else None)
    if f & 0x08:
        i += 2
    rr = max(0, (len(data) - i) // 2) if f & 0x10 else 0
    return bpm, contact, rr


class HrContact:
    """Is the heart-rate sensor on the skin? Works with any sensor, from what it reports:
    1. it reports skin contact: "no contact" = not worn, at once;
    2. it has been sending beat-to-beat times: none for RR_GAP_MS (a heart beats at least every 1.5 s) = not worn;
    3. neither: assumed worn while messages arrive (the 5 s silence / disconnect rule still applies).
    Some straps keep sending their last value for minutes after they come off (seen 2026-10-31): rules 1-2 catch
    that. update() returns None when worn, else the reason: "contact" or "beats". One instance per connection.
    After "beats", worn again only after beat times in RR_BACK messages in a row: a strap lying around can send a
    stray beat time (seen 2026-10-31: one blip 1 s after it was found off)."""
    RR_GAP_MS = 5000
    RR_BACK = 3
    MIN_BPM = 30                         # below this it isn't a heart rate: 0 bpm from a strap held by its contacts

    def __init__(self, diff=lambda a, b: a - b, known_rr=False, now_ms=0):
        """known_rr: this sensor sent beat times before (remembered across connections and restarts): then 5 s
        without any from the connection on = not worn. Without it, a strap reconnecting while it lies off and sends
        its last value without beat times would pass as a sensor that never sends them (seen 2026-10-31)."""
        self.diff = diff                 # time.ticks_diff on the Pico (ticks wrap)
        self.reports_contact = False
        self.sends_rr = known_rr
        self.last_rr = now_ms if known_rr else None
        self.off_beats = False           # judged "not worn" by missing beat times
        self.rr_run = 0                  # messages in a row with beat times

    def update(self, now_ms, contact, rr, bpm=None):
        if bpm is not None and bpm < self.MIN_BPM:
            self.rr_run = 0                  # its beat times don't count either
            return "zero"
        if contact is not None:
            self.reports_contact = True
        if rr:
            self.sends_rr = True
            self.last_rr = now_ms
            self.rr_run += 1
        else:
            self.rr_run = 0
        if contact is False:
            return "contact"
        if contact is None and self.sends_rr:
            if self.diff(now_ms, self.last_rr) > self.RR_GAP_MS:
                self.off_beats = True
            elif self.off_beats and self.rr_run >= self.RR_BACK:
                self.off_beats = False
            if self.off_beats:
                return "beats"
        return None

    def caps(self):
        """What this sensor reports, for diagnostics."""
        return "contact flag %s, beat times %s" % ("yes" if self.reports_contact else "no", "yes" if self.sends_rr else "no")


def parse_cp(data):
    """Cycling Power Measurement -> (power_w, crank) where crank is (revs, event_time) or None.

    Layout: flags uint16, instantaneous power sint16, then optional fields in flag order:
    bit 0 pedal power balance (uint8), bit 2 accumulated torque (uint16),
    bit 4 wheel revolutions (uint32 + uint16 event time), bit 5 crank revolutions
    (uint16 cumulative revs + uint16 last event time in 1/1024 s).
    """
    if len(data) < 4:
        return None, None
    flags = _u16(data, 0)
    power = max(0, _s16(data, 2))
    i = 4
    if flags & 0x01:
        i += 1
    if flags & 0x04:
        i += 2
    if flags & 0x10:
        i += 6
    crank = None
    if flags & 0x20 and len(data) >= i + 4:
        crank = (_u16(data, i), _u16(data, i + 2))
    return power, crank


def parse_bike(data):
    """Indoor Bike Data -> (power_w or None, cadence_rpm or None).

    Layout: flags uint16, then fields in flag order. Bit 0 "More Data" is inverted:
    0 = instantaneous speed (uint16) present. Bit 1 average speed (uint16), bit 2
    instantaneous cadence (uint16, 0.5 rpm), bit 3 average cadence (uint16), bit 4 total
    distance (uint24), bit 5 resistance level (sint16), bit 6 instantaneous power (sint16).
    """
    if len(data) < 2:
        return None, None
    flags = _u16(data, 0)
    i = 2
    if not flags & 0x01:
        i += 2
    if flags & 0x02:
        i += 2
    cadence = None
    if flags & 0x04:
        if len(data) < i + 2:
            return None, None
        cadence = _u16(data, i) / 2
        i += 2
    if flags & 0x08:
        i += 2
    if flags & 0x10:
        i += 3
    if flags & 0x20:
        i += 2
    power = None
    if flags & 0x40:
        if len(data) < i + 2:
            return None, cadence
        power = max(0, _s16(data, i))
    return power, cadence


class CrankCadence:
    """Cadence from cumulative crank revolutions and the last crank event time.

    Both counters wrap at 16 bits; the event time is in 1/1024 s. A sensor repeats the
    same values while the crank is still, so cadence goes to 0 after CRANK_STOP_MS
    without a new revolution. ticks_diff is time.ticks_diff on the Pico (ticks_ms wraps).
    """

    def __init__(self, ticks_diff=lambda a, b: a - b):
        self._diff = ticks_diff
        self.revs = None
        self.time = None
        self.cadence = None
        self.last_change_ms = None

    def update(self, revs, event_time, now_ms):
        if self.revs is None:
            self.revs, self.time, self.last_change_ms = revs, event_time, now_ms
            return self.cadence
        d_revs = (revs - self.revs) & 0xFFFF
        d_time = (event_time - self.time) & 0xFFFF
        if d_revs and d_time:
            self.cadence = round(d_revs * 60 * 1024 / d_time)
            self.revs, self.time, self.last_change_ms = revs, event_time, now_ms
        elif self._diff(now_ms, self.last_change_ms) >= CRANK_STOP_MS:
            self.cadence = 0
            self.revs = None    # stopped: start a fresh baseline (the 16-bit event time wraps after 64 s)
        return self.cadence
