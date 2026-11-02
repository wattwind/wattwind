"""On-device relay bench test (build stage 3). USB power only: the fan and mains NOT connected.

Part 1 (automatic) steps through every level change and reads the Pico's relay pins back. It checks the
program and the switching rules (break-before-make, rate limit), not the board: a bare Pico would pass it
too. Listen while it runs: every step should click.

Part 2 (multimeter) checks the board itself: the driver, the relays and their contacts, the fuse and the
terminals. It holds each level until you press Enter, and says which terminals must beep on the continuity
setting. The fuse must be fitted.

Run it while main.py is not on the Pico yet (first install: copy everything else, run this, then copy
main.py). If main.py is already running, its watchdog resets the board partway through: use update mode.

    Thonny: open relay_test.py on the Pico and press Run.   Or: mpremote run relay_test.py
"""

import time

import relay

SEQUENCE = [1, 2, 3, 2, 1, 0, 3, 0, 2, 0]
TAP = {1: "J2-4 (LOW)", 2: "J2-3 (MED)", 3: "J2-2 (HIGH)"}


def expect(lvl):
    want = (lvl > 0, lvl == 1, lvl == 2, lvl == 3)
    got = relay.energized()
    ok = got == want
    print("  K0..K3 =", [int(x) for x in got], "OK" if ok else "FAIL, expected {}".format(
        [int(x) for x in want]))
    return ok


def go(lvl):
    while relay.ms_until_allowed():
        time.sleep_ms(50)
    assert relay.set_level(lvl)


def part1():
    print("Part 1: the program and the Pico's pins (listen: every step should click)")
    failures = 0 if expect(0) else 1
    for lvl in SEQUENCE:
        while relay.ms_until_allowed():
            time.sleep_ms(50)
        t0 = time.ticks_ms()
        assert relay.set_level(lvl)
        print("level {} ({} ms)".format(lvl, time.ticks_diff(time.ticks_ms(), t0)))
        failures += 0 if expect(lvl) else 1
    print("rate limit: immediate change refused ->", end=" ")
    refused = relay.set_level(1) is False
    print("OK" if refused else "FAIL")
    failures += 0 if refused else 1
    relay.set_level(0, force=True)
    failures += 0 if expect(0) else 1
    print("Part 1:", "PASS" if failures == 0 else "{} FAILURE(S)".format(failures))
    return failures


def part2():
    print()
    print("Part 2: the board (multimeter on continuity / beep; fuse fitted; mains and fan NOT connected)")
    print("J1 A / B and J2 COM, HIGH, MED, LOW are printed on the board (J2-1 = COM ... J2-4 = LOW).")
    try:
        if input("Press Enter to start, or type s and Enter to skip: ").strip().lower() == "s":
            return
    except Exception:              # no keyboard (e.g. run without a terminal): skip part 2
        print("(no input: part 2 skipped)")
        return
    for lvl in (1, 2, 3, 0):
        go(lvl)
        if lvl:
            others = ", ".join(TAP[k] for k in (1, 2, 3) if k != lvl)
            print("\nLevel {}: must beep  J1 B <-> J2-1 (COM)  and  J1 A <-> {}".format(lvl, TAP[lvl]))
            print("         must stay silent  J1 A <-> {}".format(others))
        else:
            print("\nOff: must stay silent  J1 B <-> J2-1 (COM)  and  J1 A <-> each of J2-2, J2-3, J2-4")
        input("  measured? Enter for the next step ")
    print("\nPart 2 done. A wrong beep: check that relay, its driver channel on U1, and the fuse.")


try:
    relay.init()
    print("relay test: K0=GP{} K1-K3=GP{}".format(relay.K0_PIN, relay.SPEED_PINS))
    part1()
    part2()
finally:
    relay.set_level(0, force=True)
