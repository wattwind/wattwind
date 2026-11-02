"""Auto mode: fan level 0-3 from power, cadence and heart rate.

Pure Python (only `math`): runs on the Pico and under CPython for tests/test_fan_logic.py.
Time is a parameter, so tests can simulate whole rides in milliseconds.

    p_ema    power EMA, rising / falling time constants from the "response" setting
             (normal: 12 s / 75 s; starts at 0: the fan ramps up)
    hr_f     heart rate EMA, ~5 s (starts at the first value)
    p_score  = p_ema / ftp
    hr_score = (hr_f - hr_rest) / (hr_max - hr_rest)
    demand   = max of the scores that are available

Levels step one at a time with hysteresis (up_thresholds / down_thresholds) after
dwell_up_s / dwell_down_s at the current level. Special cases, in priority order:
    idle      not pedaling, or no sensor data at all, for idle_off_min: off
    lost      no power and no HR: hold 120 s, then one level down per 60 s
    stopped   cadence 0 or power < 20 W for 5 s: hold (normal: 60 s), then one level down per 60 s
              (no stepping up while stopped, even before the 5 s)
"""

import math

# "response" setting: (power EMA rising s, power EMA falling s, hold after stopping s)
USES = ("both", "power", "hr")   # setting "use": what decides; the other one only steps in when that is missing

RESPONSES = {
    "calm": (20, 120, 90),
    "normal": (12, 75, 60),
    "quick": (6, 40, 30),
}
TAU_HR_S = 5
STOP_POWER_W = 20
STOP_DETECT_S = 5
LOST_HOLD_S = 120
FORCED_STEP_S = 60
NUDGE_MAX = 2                # Auto nudge: levels added to what auto computes, -2 .. +2


def _ema(value, target, dt, tau):
    return value + (target - value) * (1 - math.exp(-dt / tau))


class FanLogic:
    def __init__(self, cfg):
        self.cfg = cfg               # read on every update: settings changes apply at once
        self.level = 0
        self.p_ema = None
        self.hr_f = None
        self.p_score = None
        self.hr_score = None
        self.demand = None
        self.basis = None
        self.idle_s = 0              # seconds without pedaling (or without any sensor data)
        self._last_t = None
        self._level_since = None
        self._stop_since = None
        self._lost_since = None
        self._idle_since = None
        self._forced_next = None     # next forced step down (stopped / lost)
        self.nudge = 0               # -NUDGE_MAX..NUDGE_MAX levels: today's "a bit more / less" in auto
        self.target = 0              # the level to switch to: self.level (computed) + nudge
        self.why = ""                # why the computed level last changed (for the logbook)

    def update(self, now_s, power, cadence, hr):
        """One step, about once per second. None = value missing. Returns the target level."""
        cfg = self.cfg
        tau_up, tau_down, stop_hold_s = RESPONSES.get(cfg.get("response"), RESPONSES["normal"])
        dt = 0 if self._last_t is None else max(0, now_s - self._last_t)
        self._last_t = now_s
        if self._level_since is None:
            self._level_since = now_s

        # Filters and scores
        if power is not None:
            if self.p_ema is None:
                self.p_ema = 0.0
            tau = tau_up if power > self.p_ema else tau_down
            self.p_ema = _ema(self.p_ema, power, dt, tau)
            self.p_score = max(0.0, self.p_ema / cfg["ftp"])
        else:
            self.p_score = None
        if hr is not None:
            self.hr_f = float(hr) if self.hr_f is None else _ema(self.hr_f, hr, dt, TAU_HR_S)
            self.hr_score = max(0.0, (self.hr_f - cfg["hr_rest"]) / (cfg["hr_max"] - cfg["hr_rest"]))
        else:
            self.hr_score = None
        ps, hs = self.p_score, self.hr_score
        use = cfg.get("use", "both")
        if use == "power" and ps is not None:
            hs = None                   # power decides; heart rate only while power is missing
        elif use == "hr" and hs is not None:
            ps = None                   # heart rate decides; power only while heart rate is missing
        scores = [s for s in (ps, hs) if s is not None]
        self.demand = max(scores) if scores else None
        self.basis = ("both" if ps is not None and hs is not None else "power" if ps is not None
                      else "hr" if hs is not None else None)          # shown on the page next to demand

        # Conditions
        stopped = (cadence is not None and cadence == 0) or (power is not None and power < STOP_POWER_W)
        self._stop_since = (self._stop_since if self._stop_since is not None else now_s) if stopped else None
        lost = power is None and hr is None
        self._lost_since = (self._lost_since if self._lost_since is not None else now_s) if lost else None
        if stopped or lost:             # heart rate alone counts as riding (no power sensor needed)
            if self._idle_since is None:
                self._idle_since = now_s
            self.idle_s = now_s - self._idle_since
        else:
            self._idle_since = None
            self.idle_s = 0

        # Decide (the computed level never stays above max_level, e.g. when it is lowered mid-ride)
        if self.level > cfg.get("max_level", 3):
            self._set(cfg.get("max_level", 3), now_s, "highest level {}".format(cfg.get("max_level", 3)))
        if self.idle_s >= cfg["idle_off_min"] * 60:
            self._forced_next = None
            self.nudge = 0                # the ride is over: the nudge was for that ride only
            self._set(0, now_s, "no riding for {} min".format(cfg["idle_off_min"]))
        elif lost:
            self._forced_down(now_s, self._lost_since + LOST_HOLD_S, "no sensor data")
        elif stopped and now_s - self._stop_since >= STOP_DETECT_S:
            self._forced_down(now_s, self._stop_since + STOP_DETECT_S + stop_hold_s, "stopped pedaling")
        else:
            self._forced_next = None
            self._hysteresis(now_s, stopped)
        # Nudge: whole levels on top of the computed one. It never switches the fan on while you aren't
        # pedalling (stopped, or no sensor data), so the fan still goes off after the ride.
        t = self.level + self.nudge
        if self.level == 0 and self.nudge > 0 and (stopped or lost):
            t = 0
        self.target = max(0, min(cfg.get("max_level", 3), t))   # auto never goes above max_level
        return self.target

    def adopt(self, level, now_s, restart_idle=True):
        """Continue from the level the fan is at (switching from manual back to auto), instead of
        jumping to the level computed in the background. Normal dwell times count from now, and
        a running stop / sensor-loss step-down waits a full FORCED_STEP_S before its next step.
        restart_idle: the idle timer starts again, so a long idle period (or no sensors) doesn't
        turn the fan off the moment auto is chosen; False for the idle timeout's own switch."""
        self.level = level
        self.target = max(0, min(3, level + self.nudge))
        self._level_since = now_s
        self._forced_next = now_s + FORCED_STEP_S      # next forced step (stopped / lost); the next
                                                       # update clears it if no step-down is running
        if restart_idle and self._idle_since is not None:
            self._idle_since = now_s
            self.idle_s = 0

    def _forced_down(self, now_s, first_step_s, why):
        if self._forced_next is None:
            self._forced_next = first_step_s
        if self.level > 0 and now_s >= self._forced_next:
            self._set(self.level - 1, now_s, why)
            self._forced_next = now_s + FORCED_STEP_S

    def _hysteresis(self, now_s, stopped):
        if self.demand is None:
            return
        cfg = self.cfg
        at_level = now_s - self._level_since
        lv = self.level
        if lv < cfg.get("max_level", 3) and not stopped and self.demand >= cfg["up_thresholds"][lv] \
                and at_level >= cfg["dwell_up_s"]:
            self._set(lv + 1, now_s, "demand {:.2f} >= {} ({})".format(self.demand, cfg["up_thresholds"][lv], self.basis))
        elif lv > 0 and self.demand < cfg["down_thresholds"][lv - 1] \
                and at_level >= cfg["dwell_down_s"]:
            self._set(lv - 1, now_s, "demand {:.2f} < {} ({})".format(self.demand, cfg["down_thresholds"][lv - 1], self.basis))

    def _set(self, level, now_s, why=""):
        if level != self.level:
            self.level = level
            self._level_since = now_s
            self.why = why
