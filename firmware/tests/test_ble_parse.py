import struct

from ble_parse import parse_hr, parse_cp, parse_bike, CrankCadence, CRANK_STOP_MS


def test_hr_uint8_and_uint16():
    assert parse_hr(bytes([0x00, 72])) == 72
    assert parse_hr(bytes([0x01]) + struct.pack("<H", 300)) == 300
    assert parse_hr(bytes([0x16, 150, 0x10, 0x03])) == 150      # contact bits + RR interval
    assert parse_hr(b"\x00") is None
    assert parse_hr(b"\x01\x50") is None


def test_cp_power_only():
    # A Pico-based BLE simulator sends flags 0 + power.
    assert parse_cp(struct.pack("<Hh", 0, 245)) == (245, None)
    assert parse_cp(struct.pack("<Hh", 0, -5)) == (0, None)
    assert parse_cp(b"\x00\x00\x10") == (None, None)


def test_cp_crank_after_optional_fields():
    # balance (1) + torque (2) + wheel (6) + crank (4)
    flags = 0x01 | 0x04 | 0x10 | 0x20
    data = struct.pack("<HhBHIHHH", flags, 310, 50, 1234, 99999, 2048, 517, 40960)
    assert parse_cp(data) == (310, (517, 40960))
    assert parse_cp(struct.pack("<HhHH", 0x20, 200, 12, 3000)) == (200, (12, 3000))


def test_bike_simulator_flags():
    # Flags 0x0A54 as sent by a Pico-based BLE simulator: speed, cadence, distance, power, HR, time.
    data = struct.pack("<HHH", 0x0A54, 3000, 180) + bytes([0x10, 0x27, 0x00]) + \
        struct.pack("<hBH", 215, 140, 600)
    assert parse_bike(data) == (215, 90.0)


def test_bike_power_without_cadence():
    data = struct.pack("<Hh", 0x0041, 150)    # bit 0 = 1: no speed field
    assert parse_bike(data) == (150, None)


def test_bike_truncated():
    assert parse_bike(b"\x44\x00\x00") == (None, None)
    assert parse_bike(struct.pack("<HHH", 0x0044, 0, 170)) == (None, 85.0)


def test_crank_cadence():
    c = CrankCadence()
    assert c.update(100, 0, 0) is None
    assert c.update(101, 683, 1000) == 90                 # 1 rev in 683/1024 s
    assert c.update(101, 683, 2000) == 90                 # repeated values: keep
    assert c.update(101, 683, 1000 + CRANK_STOP_MS) == 0  # stopped


def test_crank_cadence_wraps():
    c = CrankCadence()
    c.update(0xFFFF, 0xFF00, 0)
    assert c.update(0x0001, 0x0300, 1000) == round(2 * 60 * 1024 / 0x400)


def test_crank_cadence_after_a_long_stop():
    c = CrankCadence()
    c.update(100, 0, 0)
    assert c.update(101, 1024, 1000) == 60
    assert c.update(101, 1024, 5000) == 0              # stopped
    # 70 s later pedaling again at 90 rpm: the event time has wrapped (70 s > 64 s)
    t0 = (1024 + 70 * 1024) & 0xFFFF
    c.update(102, t0, 75000)                           # first revolution after the stop: new baseline
    assert c.update(103, (t0 + 683) & 0xFFFF, 75667) == 90


# ---- is the strap worn? (any sensor: what it reports) ---------------------------------------------

from ble_parse import parse_hr_full, HrContact  # noqa: E402


def test_hr_full_contact_and_rr():
    assert parse_hr_full(bytes([0x06, 120])) == (120, True, 0)                 # contact supported, detected
    assert parse_hr_full(bytes([0x04, 120])) == (120, False, 0)                # supported, not detected
    assert parse_hr_full(bytes([0x00, 120])) == (120, None, 0)                 # not reported
    assert parse_hr_full(bytes([0x02, 120])) == (120, None, 0)                 # bit 1 alone: "not supported" too
    assert parse_hr_full(bytes([0x16, 150, 0x10, 0x03, 0x20, 0x03])) == (150, True, 2)   # two RR intervals
    assert parse_hr_full(bytes([0x19]) + struct.pack("<HHH", 300, 55, 800)) == (300, None, 1)   # uint16 + energy + RR
    assert parse_hr_full(b"\x00") == (None, None, 0)


def test_contact_flag_strap():
    c = HrContact()
    assert c.update(0, True, 1) is None
    assert c.update(1000, False, 0) == "contact"          # off the skin: at once
    assert c.update(2000, True, 1) is None                # worn again
    assert c.caps() == "contact flag yes, beat times yes"


def test_rr_strap_without_contact_flag():
    """Keeps sending its last value, without beat times, after it comes off (the 2026-10-31 ride)."""
    c = HrContact()
    for t in range(0, 10000, 1000):
        assert c.update(t, None, 1) is None
    for t in range(10000, 14001, 1000):                    # last beat time at 9 s; 5 s of grace
        assert c.update(t, None, 0) is None
    assert c.update(15000, None, 0) == "beats"
    assert c.update(16000, None, 1) == "beats"             # one stray beat time: still not worn
    assert c.update(17000, None, 0) == "beats"
    for t in (18000, 19000):
        assert c.update(t, None, 1) == "beats"
    assert c.update(20000, None, 1) is None                # beat times in 3 messages in a row: worn again


def test_known_strap_reconnecting_while_off():
    """A strap known to send beat times connects (after a restart) while it lies off: not worn after 5 s."""
    c = HrContact(known_rr=True, now_ms=100000)
    for t in range(101000, 105001, 1000):
        assert c.update(t, None, 0) is None
    assert c.update(106000, None, 0) == "beats"


def test_sensor_reporting_neither_is_trusted():
    """Optical sensors often report neither: the old rules (5 s silence, disconnect) still apply."""
    c = HrContact()
    for t in range(0, 600000, 1000):
        assert c.update(t, None, 0) is None
    assert c.caps() == "contact flag no, beat times no"


def test_contact_flag_wins_over_missing_beats():
    c = HrContact()
    c.update(0, True, 1)
    assert c.update(20000, True, 0) is None                # says contact: trusted even without beat times


def test_zero_bpm_is_not_a_reading():
    """A strap held by its contacts sent 0 bpm with beat times (2026-10-31): not worn, beat times don't count."""
    c = HrContact()
    assert c.update(0, None, 1, 0) == "zero"
    assert c.update(1000, None, 1, 0) == "zero"
    assert c.update(2000, None, 1, 72) is None             # a real reading again
