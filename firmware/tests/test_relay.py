"""Relay sequencing tests with fake pins and a fake clock.

Every pin write is logged with a timestamp and the safety invariants are checked
after each one, so a single bad intermediate state fails the test.
"""

import itertools

import pytest

import relay

K0, K1, K2, K3 = relay.K0_PIN, *relay.SPEED_PINS


class FakeClock:
    def __init__(self):
        self.t = 1000

    def ticks_ms(self):
        return self.t

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, ms):
        self.t += ms


class Rig:
    """Fake hardware: records each write and checks invariants as it happens."""

    def __init__(self):
        self.clock = FakeClock()
        self.values = {}
        self.log = []                  # (t, pin, energized)
        self.k0_on_since = None
        self.speed_all_off_since = None
        self.created = []

    def pin_factory(self, num, value):
        rig = self
        # A relay must never be energized at the moment its pin is created.
        assert value == 0
        self.values[num] = value
        self.created.append(num)

        class Pin:
            def value(self, v=None):
                if v is None:
                    return rig.values[num]
                rig.write(num, v)

        return Pin()

    def energized(self, num):
        return self.values.get(num) == 1

    def write(self, num, v):
        was = self.energized(num)
        self.values[num] = v
        now = self.energized(num)
        t = self.clock.t
        self.log.append((t, num, now))
        speeds_on = [p for p in (K1, K2, K3) if self.energized(p)]

        # Rule 3: never more than one speed relay energized.
        assert len(speeds_on) <= 1, "two speed relays on at t={}".format(t)

        if num == K0:
            if now and not was:
                self.k0_on_since = t
            if was and not now:
                # K0 goes off only after the speed relay has been off >= 100 ms.
                assert not speeds_on
                assert self.speed_all_off_since is not None
                assert t - self.speed_all_off_since >= 100
                self.k0_on_since = None
        else:
            if now and not was:
                # Speed relay on: K0 on for >= 100 ms, and all speeds off for >= 100 ms.
                assert self.energized(K0), "speed relay on without K0"
                assert t - self.k0_on_since >= 100
                assert self.speed_all_off_since is not None
                assert t - self.speed_all_off_since >= 100
                self.speed_all_off_since = None
            if not speeds_on and self.speed_all_off_since is None:
                self.speed_all_off_since = t

    def state(self):
        return tuple(self.energized(p) for p in (K0, K1, K2, K3))


def make_rig():
    rig = Rig()
    relay.init(pin_factory=rig.pin_factory, clock=rig.clock)
    # Speed relays have been "off" since boot.
    rig.speed_all_off_since = rig.clock.t - 10000
    return rig


def expected(level):
    return (level > 0, level == 1, level == 2, level == 3)


def test_init_all_off():
    rig = make_rig()
    assert sorted(rig.created) == sorted([K0, K1, K2, K3])
    assert rig.state() == (False, False, False, False)
    assert relay.level() == 0
    assert relay.energized() == (False, False, False, False)


@pytest.mark.parametrize("a,b", [p for p in itertools.product(range(4), repeat=2) if p[0] != p[1]])
def test_every_transition(a, b):
    rig = make_rig()
    if a:
        assert relay.set_level(a)
        rig.clock.t += 2000
    assert rig.state() == expected(a)
    assert relay.set_level(b)
    assert rig.state() == expected(b)
    assert relay.level() == b
    assert relay.energized() == expected(b)


def test_long_random_sequence_keeps_invariants():
    import random
    rng = random.Random(1)
    rig = make_rig()
    for _ in range(500):
        lvl = rng.randrange(4)
        rig.clock.t += 2000
        assert relay.set_level(lvl)
        assert rig.state() == expected(lvl)


def test_off_to_level_sequence_timing():
    rig = make_rig()
    relay.set_level(2)
    # K0 on first, speed relay 100 ms later.
    ons = [(t, p) for t, p, on in rig.log if on]
    assert ons[0][1] == K0 and ons[1][1] == K2
    assert ons[1][0] - ons[0][0] == 100


def test_level_to_off_sequence_timing():
    rig = make_rig()
    relay.set_level(3)
    rig.clock.t += 5000
    rig.log.clear()
    relay.set_level(0)
    offs = [(t, p) for t, p, on in rig.log if not on and p in (K0, K3)]
    assert offs[0][1] == K3 and offs[-1][1] == K0
    assert offs[-1][0] - offs[0][0] == 100


def test_rate_limit():
    rig = make_rig()
    assert relay.set_level(1)                   # first change is allowed immediately
    rig.clock.t += 1500
    assert relay.set_level(2) is False          # too soon: refused, nothing switched
    assert rig.state() == expected(1)
    assert relay.ms_until_allowed() == 500      # measured from the end of the last change
    rig.clock.t += 500
    assert relay.set_level(2)
    assert rig.state() == expected(2)


def test_same_level_is_not_a_change():
    rig = make_rig()
    relay.set_level(1)
    n = len(rig.log)
    assert relay.set_level(1)
    assert len(rig.log) == n


def test_force_off_bypasses_rate_limit():
    rig = make_rig()
    relay.set_level(3)
    assert relay.set_level(0, force=True)
    assert rig.state() == expected(0)


@pytest.mark.parametrize("bad", [-1, 4, 1.5, "1", None])
def test_invalid_level(bad):
    rig = make_rig()
    with pytest.raises(ValueError):
        relay.set_level(bad)
    assert rig.state() == expected(0)


def test_exception_mid_sequence_turns_everything_off():
    rig = make_rig()
    relay.set_level(1)
    rig.clock.t += 2000

    real_sleep = rig.clock.sleep_ms
    calls = []

    def boom(ms):
        # Ctrl-C lands during the break-before-make wait; later sleeps work.
        calls.append(ms)
        if len(calls) == 1:
            raise KeyboardInterrupt
        real_sleep(ms)

    rig.clock.sleep_ms = boom
    with pytest.raises(KeyboardInterrupt):
        relay.set_level(2)
    assert rig.state() == expected(0)
    assert relay.level() == 0


class WrapClock(FakeClock):
    """MicroPython's ticks: ticks_ms wraps at 2**30 ms (~12.4 days), ticks_diff is only right within half of that."""
    PERIOD = 1 << 30

    def ticks_ms(self):
        return self.t % self.PERIOD

    def ticks_diff(self, a, b):
        return ((a - b + self.PERIOD // 2) % self.PERIOD) - self.PERIOD // 2


DAY_MS = 24 * 3600 * 1000


@pytest.mark.parametrize("days", [6.3, 7, 9, 12.4, 12.43, 20, 40])
def test_rate_limit_after_days_without_a_change(days):
    """Found 2026-10-31: after ~6.2 days without a level change the old timestamp read as "just now" and every
    change was refused for days (the fan wouldn't come on, or wouldn't go off). Fixed in relay.ms_until_allowed."""
    rig = Rig()
    rig.clock = WrapClock()
    relay.init(pin_factory=rig.pin_factory, clock=rig.clock)
    rig.speed_all_off_since = rig.clock.t - 10000
    assert relay.set_level(1)
    rig.clock.t += 2000
    relay.ms_until_allowed()                     # control_task asks every 100 ms: the change is forgotten
    rig.clock.t += int(days * DAY_MS)
    assert relay.set_level(0)                    # off at once
    rig.clock.t += 2000
    assert relay.set_level(2)


def test_rate_limit_wrap_even_without_the_regular_check():
    """Also safe if nothing asked in between (d < 0 = the counter wrapped)."""
    rig = Rig()
    rig.clock = WrapClock()
    relay.init(pin_factory=rig.pin_factory, clock=rig.clock)
    rig.speed_all_off_since = rig.clock.t - 10000
    assert relay.set_level(3)
    rig.clock.t += 7 * DAY_MS
    assert relay.set_level(0)
