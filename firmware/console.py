"""USB-serial commands for bench testing. Type a command and press Enter (not echoed):
0 1 2 3 = manual level, a = auto, s = status

Reads only characters that have already arrived, never waits for a whole line:
sys.stdin.readline() blocks the entire asyncio loop until Enter, so stray bytes from a
serial tool (Thonny / MicroPico control sequences) would freeze Wi-Fi, web and BLE.
"""

import sys
import select
import asyncio

import state
import relay

POLL_MS = 100
MAX_LINE = 16       # longer input is garbage from a tool, not a command


def _handle(cmd):
    if cmd in ("0", "1", "2", "3"):
        state.set_manual(int(cmd))
    elif cmd == "a":
        if state.auto_available:
            state.set_auto()
        else:
            print("console: auto mode is not available yet")
    elif cmd == "s":
        print("console: mode={} level={} K0-K3={}".format(
            state.mode, relay.level(), [int(k) for k in relay.energized()]))


async def run():
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    print("console: 0/1/2/3 = manual level, a = auto, s = status")
    line = ""
    while True:
        while poll.poll(0):             # a character is waiting: read(1) returns at once
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                if line:
                    _handle(line.strip())
                line = ""
            elif len(line) < MAX_LINE:
                line += ch
        await asyncio.sleep_ms(POLL_MS)
