"""Stand-ins for the Pico, for host tests of main.py and wifi.py: a virtual clock (sleeps return at once and move
it forward, so minutes run in milliseconds), machine (pins, reset, watchdog), and a network with a scripted router.

    clock = Clock(monkeypatch)        time.ticks_ms / ticks_diff / ticks_add / sleep_ms, asyncio.sleep / sleep_ms
    m = FakeMachine(); monkeypatch.setitem(sys.modules, "machine", m)
    net = FakeNetwork(clock); monkeypatch.setitem(sys.modules, "network", net)
    run_until(coro, clock, until_s=..., stop=lambda: ...)

MicroPython's ticks wrap at 2**30 ms like the Pico's (so long runs see the real wrap-around).
"""
import asyncio
import types

PERIOD = 1 << 30
_real_sleep = asyncio.sleep
_real_run = asyncio.run           # tests may replace asyncio.run (main.py's last line)


class Clock:
    def __init__(self, monkeypatch, state=None):
        import time
        self.ms = 0
        self.state = state                  # if given: state.uptime_s follows the clock (main.py's job on the Pico)
        monkeypatch.setattr(time, "ticks_ms", lambda: self.ms % PERIOD, raising=False)
        monkeypatch.setattr(time, "ticks_diff", lambda a, b: ((a - b + PERIOD // 2) % PERIOD) - PERIOD // 2,
                            raising=False)
        monkeypatch.setattr(time, "ticks_add", lambda a, b: (a + b) % PERIOD, raising=False)
        monkeypatch.setattr(time, "sleep_ms", self.advance, raising=False)
        monkeypatch.setattr(asyncio, "sleep_ms", self._sleep_ms, raising=False)
        monkeypatch.setattr(asyncio, "sleep", self._sleep)

    def advance(self, ms):
        self.ms += int(ms)
        if self.state is not None:
            self.state.uptime_s = self.ms // 1000

    @property
    def s(self):
        return self.ms / 1000

    async def _sleep_ms(self, ms):
        self.advance(ms)
        await _real_sleep(0)

    async def _sleep(self, s, *a):
        self.advance(s * 1000)
        await _real_sleep(0)


class Reset(BaseException):
    """machine.reset() was called. Not an Exception: on the Pico reset() never returns, so no `except Exception`
    in the firmware may catch it."""


class FakeMachine(types.ModuleType):
    PWRON_RESET, WDT_RESET, SOFT_RESET = 1, 3, 5

    def __init__(self, cause=1):
        super().__init__("machine")
        self.cause = cause
        self.pins = {}                       # pin number -> 0/1
        self.resets = 0
        self.fed = 0
        m = self

        class Pin:
            OUT, IN = 1, 0

            def __init__(self, n, mode=None, value=None):
                self.n = n
                if value is not None:
                    m.pins[n] = value

            def value(self, v=None):
                if v is None:
                    return m.pins.get(self.n, 0)
                m.pins[self.n] = v

        class WDT:
            def __init__(self, timeout=0):
                pass

            def feed(self):
                m.fed += 1

        class ADC:
            def __init__(self, ch):
                pass

            def read_u16(self):
                return 14000                 # ~27 C

        self.Pin, self.WDT, self.ADC = Pin, WDT, ADC

    def reset_cause(self):
        return self.cause

    def reset(self):
        self.resets += 1
        raise Reset()


class FakeNetwork(types.ModuleType):
    """One router: up/down by time (router_up(t_s)), a password, and how long a join takes."""
    STA_IF, AP_IF = 0, 1
    STAT_IDLE, STAT_CONNECTING, STAT_WRONG_PASSWORD, STAT_NO_AP_FOUND, STAT_CONNECT_FAIL, STAT_GOT_IP = 0, 1, -3, -2, -1, 3

    def __init__(self, clock, ssid="HomeWiFi", password="secretpass", router_up=lambda t: True, join_s=2):
        super().__init__("network")
        self.clock, self.ssid, self.password, self.router_up, self.join_s = clock, ssid, password, router_up, join_s
        self._host = "wattwind"
        self.joins = []                      # (time s, ssid) of every connect() call
        net = self

        class WLAN:
            _all = {}

            def __new__(cls, iface):
                if iface not in cls._all:
                    w = object.__new__(cls)
                    w.iface, w.on, w.target, w.since, w.cfg = iface, False, None, None, {}
                    cls._all[iface] = w
                return cls._all[iface]

            def active(self, v=None):
                if v is None:
                    return self.on
                self.on = bool(v)
                if not v:
                    self.target = None

            def config(self, *a, **kw):
                if a == ("mac",):
                    return b"\x28\xcd\xc1\x00\x1a\x2b"
                self.cfg.update(kw)

            def connect(self, ssid, password):
                net.joins.append((net.clock.s, ssid))
                self.target, self.since = (ssid, password), net.clock.s

            def disconnect(self):
                self.target = None

            def _right(self):
                return self.target is not None and self.target[0] == net.ssid

            def isconnected(self):
                return (self.on and self._right() and self.target[1] == net.password
                        and net.router_up(net.clock.s) and net.clock.s - self.since >= net.join_s)

            def status(self, what=None):
                if what == "rssi":
                    return -60
                if self.isconnected():
                    return net.STAT_GOT_IP
                if not self._right() or not net.router_up(net.clock.s):
                    return net.STAT_NO_AP_FOUND if self.target else net.STAT_IDLE
                if self.target[1] != net.password and net.clock.s - self.since >= 1:
                    return net.STAT_WRONG_PASSWORD
                return net.STAT_CONNECTING

            def ifconfig(self):
                return ("192.168.4.1",) if self.iface == net.AP_IF else ("192.168.1.50",)

            def scan(self):
                return []

        self.WLAN = WLAN

    def hostname(self, h=None):
        if h is None:
            return self._host
        self._host = h


def run_until(coro, clock, until_s, stop=None, also=()):
    """Run coro (plus the coroutines in `also`) on the virtual clock until `stop()` is true or until_s passes,
    then cancel. Returns the virtual time (s) at the end. Exceptions from the tasks propagate."""
    async def main():
        tasks = [asyncio.ensure_future(c) for c in (coro,) + tuple(also)]
        try:
            while clock.s < until_s and not (stop and stop()):
                for t in tasks:
                    if t.done():
                        t.result()           # raises if it crashed
                await _real_sleep(0)
                if all(t.done() for t in tasks):
                    break
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for t in tasks:
                if t.done() and not t.cancelled() and t.exception():
                    raise t.exception()
        return clock.s
    return _real_run(main())
