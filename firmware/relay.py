"""The ONLY module that touches relay GPIOs.

K0 = master relay (switches MAINS_B; the speed chain switches MAINS_A). Speed relays (interlock chain K3 -> K2 -> K1):
  K1 = LOW speed     (level 1)
  K2 = MEDIUM speed  (level 2)
  K3 = HIGH speed    (level 3)

Safety rules:
- Never more than one speed relay on: all off, wait 100 ms, then the new one on.
- From off: K0 on, wait 100 ms, then the speed relay. To off: speed relay off, wait 100 ms, then K0 off.
- At most one level change per 2 s.
- Never switch a relay pin to input, not even to "release" it: on the Pico 2 W (RP2350, erratum E9) a pin that
  was high stays at ~2 V with only the internal pull-down, and that keeps the relay ON (measured 2026-10-30 on
  board v3.1: K0 stayed on until driven low). A reset clears it (all pins read 0 after a watchdog reset).

set_level() blocks for 100 ms on purpose, so no other task can run in the middle of a switch.
"""

# ---------------------------------------------------------------------------------------
# Wiring (full schematic and netlist: hardware/docs/netlist.md)
#
# MAINS SIDE (230 V: unplug before touching anything!)
# The plug is reversible, so the two mains wires are MAINS_A / MAINS_B, not L / N.
#
#                                             K3 HIGH            K2 MEDIUM          K1 LOW
#                                           +---------+        +---------+        +---------+
#                                           |         |        |         |        |         |
#  J1 MAINS_A--[F1]------------------------>| COM  NC |------->| COM  NC |------->| COM  NC |--x
#                                           |      NO |--+     |      NO |--+     |      NO |--+
#                                           +---------+  |     +---------+  |     +---------+  |
#                                                        v                  v                  v
#                     K0 master                      J2 TAP3           J2 TAP2            J2 TAP1
#                   +-----------+
#  J1 MAINS_B-------| COM    NO |-------------------------------------------------> J2 MOTOR_COMMON
#                   |        NC |--x
#                   +-----------+
#
#   COM = common, NO = normally open (closed when energized), NC = normally closed.
#   All four relays are Finder 34.51 (single pole). K0 cuts MAINS_B and the speed chain cuts
#   MAINS_A, so the fan is disconnected on both wires when off. The 5 V supply PS1 is
#   connected before the relays and stays powered.
#   The chain is a hardware interlock: K3 on cuts power to K2 and K1, K2 on cuts K1,
#   so two speed windings can never be powered at the same time, even if the software fails.
#   Remove the fan's own speed switch; keep its capacitor (if any) wired as it was.
#
# LOW-VOLTAGE SIDE (U1 = TBD62003A driver, active HIGH: GPIO high = relay on)
#
#         Pico (2) W              U1
#   +---------------+       +-------------+
#   | GP15  pin 20  |-------| IN1    OUT1 |------[ K1 coil ]------+
#   | GP14  pin 19  |-------| IN2    OUT2 |------[ K2 coil ]------+
#   | GP12  pin 16  |-------| IN5    OUT5 |------[ K3 coil ]------+
#   | GP11  pin 15  |-------| IN6    OUT6 |------[ K0 coil ]------+
#   | GND   pin 18  |-------| GND     COM |-----------------------+------ VSYS (pin 39)
#   +---------------+       +-------------+
#   (IN3, IN4, IN7 to GND; OUT3, OUT4, OUT7 unused: these channels make the PCB tracks short and straight)
#
#   COM to VSYS enables U1's built-in flyback diodes. The relays run from VSYS, so they
#   also work on USB power alone (bench testing without mains). At power-up the GPIOs are
#   inputs with pull-downs, so the relays stay off until the code takes over.
# ---------------------------------------------------------------------------------------

import time

# Wiring (GPIO numbers). Must match hardware/docs/netlist.md.
K0_PIN = 11                # K0 master relay
SPEED_PINS = (15, 14, 12)  # K1 = level 1 LOW, K2 = level 2 MEDIUM, K3 = level 3 HIGH

BREAK_MS = 100
MIN_CHANGE_MS = 2000

_k0 = None
_speed = []          # K1, K2, K3
_level = 0
_last_change = None
_clock = time        # tests pass a fake clock


def init(pin_factory=None, clock=time):
    """Claim the relay pins, all off. Called first thing in main.py. Tests pass fake pins and clock."""
    global _k0, _speed, _level, _last_change, _clock
    if pin_factory is None:
        from machine import Pin
        pin_factory = lambda n, v: Pin(n, Pin.OUT, value=v)   # value set before output
    _clock = clock
    _speed = [pin_factory(n, 0) for n in SPEED_PINS]
    _k0 = pin_factory(K0_PIN, 0)
    _level = 0
    _last_change = None


def level():
    return _level


def ms_until_allowed():
    """Milliseconds until the next change is allowed (0 = now)."""
    global _last_change
    if _last_change is None:
        return 0
    d = _clock.ticks_diff(_clock.ticks_ms(), _last_change)
    if d < 0 or d >= MIN_CHANGE_MS:
        # Over: forget the change. The ms counter wraps (ticks_diff is only right for ~6.2 days on the Pico), so
        # an old timestamp kept for a week would read as "just now" and block every change for days (found
        # 2026-10-31 in a review). d < 0 is that wrap; control_task also calls this every 100 ms, so a
        # timestamp never lives longer than MIN_CHANGE_MS.
        _last_change = None
        return 0
    return MIN_CHANGE_MS - d


def energized():
    """(K0, K1, K2, K3) as True/False, read back from the pins."""
    return tuple(p.value() == 1 for p in [_k0] + _speed)


def set_level(new, force=False):
    """Switch the fan to level 0-3. Returns False if the 2 s rate limit refused it.

    force=True skips the rate limit; use it only for an emergency off: set_level(0, force=True).
    """
    global _level, _last_change
    if new not in (0, 1, 2, 3):
        raise ValueError("level must be 0-3")
    if new == _level and not force:
        return True
    if ms_until_allowed() and not force:
        return False

    try:
        for p in _speed:
            p.value(0)
        if new == 0:
            _clock.sleep_ms(BREAK_MS)
            _k0.value(0)
        else:
            _k0.value(1)
            _clock.sleep_ms(BREAK_MS)
            _speed[new - 1].value(1)
        _level = new
    except BaseException:
        # Something failed mid-switch (e.g. Ctrl-C): turn everything off.
        for p in _speed:
            p.value(0)
        try:
            _clock.sleep_ms(BREAK_MS)
        finally:
            _k0.value(0)
            _level = 0
        raise
    finally:
        _last_change = _clock.ticks_ms()
    return True
