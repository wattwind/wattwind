"""fan_logic.FanLogic: scores, filters, thresholds, hysteresis, dwell, stops, sensor loss, idle."""
import math

import pytest

import config
from fan_logic import FanLogic

# hr_rest 60, hr_max 160: hr_score = (hr - 60) / 100, so hr = 60 + 100 * score.
CFG = dict(config.DEFAULTS, ftp=200, hr_rest=60, hr_max=160)


def hr_for(score):
    return 60 + 100 * score


def make(**over):
    return FanLogic(dict(CFG, **over))


def ride(fl, start, seconds, power=None, cadence=None, hr=None):
    """Call update once per second for `seconds`; returns (next time, list of levels)."""
    levels = []
    for t in range(start, start + seconds):
        levels.append(fl.update(t, power, cadence, hr))
    return start + seconds, levels


def first_change(levels, frm):
    """Index of the first level different from `frm` (None if it never changes)."""
    for i, lv in enumerate(levels):
        if lv != frm:
            return i
    return None


# --- scores and filters -------------------------------------------------------------------

def test_starts_off_without_data():
    fl = make()
    assert fl.update(0, None, None, None) == 0
    assert fl.demand is None and fl.p_score is None and fl.hr_score is None


def test_hr_score_and_demand():
    fl = make()
    fl.update(0, None, None, hr_for(0.5))
    assert fl.hr_score == pytest.approx(0.5)
    assert fl.demand == pytest.approx(0.5)


def test_power_ema_rises_with_12s_time_constant():
    fl = make()
    fl.update(0, 200, 90, None)                  # p_ema starts at 0
    for t in range(1, 13):
        fl.update(t, 200, 90, None)
    assert fl.p_ema == pytest.approx(200 * (1 - math.exp(-12 / 12)), rel=0.02)


def test_power_ema_falls_with_75s_time_constant():
    fl = make()
    t, _ = ride(fl, 0, 300, power=200, cadence=90)   # settle at 200
    start = fl.p_ema
    for i in range(75):
        fl.update(t + i, 100, 90, None)
    expected = 100 + (start - 100) * math.exp(-75 / 75)
    assert fl.p_ema == pytest.approx(expected, rel=0.02)


def test_hr_filter_about_5s():
    fl = make()
    fl.update(0, None, None, 100)                 # starts at the first value
    assert fl.hr_f == 100
    for t in range(1, 6):
        fl.update(t, None, None, 150)
    assert fl.hr_f == pytest.approx(150 - 50 * math.exp(-1), rel=0.02)


def test_demand_is_max_of_scores():
    fl = make()
    ride(fl, 0, 300, power=100, cadence=90, hr=hr_for(0.8))   # p_score -> 0.5
    assert fl.p_score == pytest.approx(0.5, rel=0.02)
    assert fl.demand == pytest.approx(fl.hr_score)
    assert fl.hr_score == pytest.approx(0.8, rel=0.02)


def test_scores_never_negative():
    fl = make()
    fl.update(0, None, None, 40)                  # below hr_rest
    assert fl.hr_score == 0


# --- stepping up ----------------------------------------------------------------------------

def test_step_up_after_dwell():
    fl = make()
    _, levels = ride(fl, 0, 30, hr=hr_for(0.5))   # above 0.45
    i = first_change(levels, 0)
    assert levels[i] == 1 and i == 15              # 15 s at level 0 first


def test_below_up_threshold_stays_off():
    fl = make()
    _, levels = ride(fl, 0, 120, hr=hr_for(0.44))
    assert set(levels) == {0}


def test_up_one_level_at_a_time_with_dwell():
    fl = make()
    _, levels = ride(fl, 0, 60, hr=hr_for(0.95))  # demand for level 3
    assert levels[15] == 1 and levels[30] == 2 and levels[45] == 3
    assert all(abs(b - a) <= 1 for a, b in zip(levels, levels[1:]))
    assert levels[14] == 0 and levels[29] == 1 and levels[44] == 2


@pytest.mark.parametrize("score, level", [(0.46, 1), (0.71, 2), (0.89, 3)])
def test_up_thresholds(score, level):
    fl = make()
    _, levels = ride(fl, 0, 120, hr=hr_for(score))
    assert levels[-1] == level


# --- stepping down and hysteresis ----------------------------------------------------------

def test_hysteresis_band_holds_level():
    fl = make()
    t, _ = ride(fl, 0, 30, hr=hr_for(0.5))        # level 1
    _, levels = ride(fl, t, 300, hr=hr_for(0.40)) # between 0.38 and 0.45
    assert set(levels) == {1}


def test_step_down_after_dwell():
    fl = make()
    t, _ = ride(fl, 0, 30, hr=hr_for(0.5))        # reaches level 1 at t=15
    _, levels = ride(fl, t, 120, hr=hr_for(0.30))
    i = first_change(levels, 1)
    assert levels[i] == 0
    assert t + i == 15 + 60                         # 60 s after reaching level 1


def test_down_one_level_at_a_time_with_dwell():
    fl = make()
    t, _ = ride(fl, 0, 120, hr=hr_for(0.95))      # level 3
    assert fl.level == 3
    _, levels = ride(fl, t, 300, hr=hr_for(0.0))
    assert all(abs(b - a) <= 1 for a, b in zip(levels, levels[1:]))
    changes = [i for i in range(1, len(levels)) if levels[i] != levels[i - 1]]
    assert len(changes) >= 2
    assert all(b - a >= 60 for a, b in zip(changes, changes[1:]))
    assert levels[-1] == 0


@pytest.mark.parametrize("start_score, down_score, frm", [(0.5, 0.37, 1), (0.75, 0.62, 2), (0.95, 0.80, 3)])
def test_down_thresholds(start_score, down_score, frm):
    fl = make()
    t, _ = ride(fl, 0, 120, hr=hr_for(start_score))
    assert fl.level == frm
    t, _ = ride(fl, t, 120, hr=hr_for(down_score + 0.02))   # just above: holds
    assert fl.level == frm
    _, levels = ride(fl, t, 120, hr=hr_for(down_score))
    assert levels[-1] == frm - 1


# --- not pedaling ----------------------------------------------------------------------------

def riding_level_2(fl):
    """HR keeps demand at level 2 even when power stops (like a rider still breathing hard)."""
    t, _ = ride(fl, 0, 120, power=150, cadence=90, hr=hr_for(0.75))
    assert fl.level == 2
    return t


def test_stop_holds_60s_then_steps_down_per_60s():
    fl = make()
    t = riding_level_2(fl)
    _, levels = ride(fl, t, 400, power=0, cadence=0, hr=hr_for(0.75))
    # detected after 5 s, held 60 s more, then one level per 60 s
    assert levels[64] == 2 and levels[65] == 1
    assert levels[124] == 1 and levels[125] == 0
    assert levels[-1] == 0


def test_short_stop_changes_nothing():
    fl = make()
    t = riding_level_2(fl)
    t, levels = ride(fl, t, 4, power=0, cadence=0, hr=hr_for(0.75))
    t, more = ride(fl, t, 120, power=150, cadence=90, hr=hr_for(0.75))
    assert set(levels + more) == {2}


def test_cadence_zero_counts_as_stop():
    fl = make()
    t = riding_level_2(fl)
    _, levels = ride(fl, t, 70, power=150, cadence=0, hr=hr_for(0.75))
    assert levels[-1] == 1


def test_low_power_counts_as_stop():
    fl = make()
    t = riding_level_2(fl)
    _, levels = ride(fl, t, 70, power=15, cadence=60, hr=hr_for(0.75))
    assert levels[-1] == 1


def test_pedaling_again_during_hold_keeps_level():
    fl = make()
    t = riding_level_2(fl)
    t, _ = ride(fl, t, 50, power=0, cadence=0, hr=hr_for(0.75))
    _, levels = ride(fl, t, 120, power=150, cadence=90, hr=hr_for(0.75))
    assert set(levels) == {2}


def test_no_step_up_while_stopped():
    fl = make()
    t, _ = ride(fl, 0, 30, power=150, cadence=90, hr=hr_for(0.5))   # level 1
    _, levels = ride(fl, t, 60, power=0, cadence=0, hr=hr_for(0.95))
    assert max(levels) == 1


# --- sensor loss ----------------------------------------------------------------------------

def test_power_missing_uses_hr_only():
    fl = make()
    t, _ = ride(fl, 0, 300, power=180, cadence=90, hr=hr_for(0.3))   # p_score 0.9: level 3
    assert fl.level == 3
    t, _ = ride(fl, t, 300, power=None, cadence=None, hr=hr_for(0.5))
    assert fl.p_score is None and fl.demand == pytest.approx(0.5, rel=0.02)
    assert fl.level == 1


def test_hr_missing_uses_power_only():
    fl = make()
    t, _ = ride(fl, 0, 300, power=100, cadence=90, hr=hr_for(0.95))
    assert fl.level == 3
    t, _ = ride(fl, t, 400, power=100, cadence=90, hr=None)
    assert fl.hr_score is None and fl.demand == pytest.approx(0.5, rel=0.02)
    assert fl.level == 1


def test_both_missing_hold_120s_then_down_per_60s():
    fl = make()
    t, _ = ride(fl, 0, 120, power=150, cadence=90, hr=hr_for(0.75))
    assert fl.level == 2
    _, levels = ride(fl, t, 400)
    assert levels[119] == 2 and levels[120] == 1
    assert levels[179] == 1 and levels[180] == 0
    assert fl.demand is None


def test_sensor_back_after_loss_resumes_normally():
    fl = make()
    t, _ = ride(fl, 0, 120, power=150, cadence=90, hr=hr_for(0.75))
    t, _ = ride(fl, t, 60)                                   # short loss: held
    assert fl.level == 2
    _, levels = ride(fl, t, 120, power=150, cadence=90, hr=hr_for(0.75))
    assert set(levels) == {2}


# --- idle ------------------------------------------------------------------------------------

def test_idle_counts_time_without_pedaling():
    fl = make()
    t, _ = ride(fl, 0, 30, power=150, cadence=90)
    assert fl.idle_s == 0
    t, _ = ride(fl, t, 100, power=0, cadence=0)
    assert fl.idle_s == pytest.approx(100, abs=1)
    t, _ = ride(fl, t, 1, power=150, cadence=90)
    assert fl.idle_s == 0


def test_heart_rate_alone_is_not_idle():
    # no power sensor at all (rollers, basic trainer): the strap alone counts as riding
    fl = make()
    ride(fl, 0, 50, hr=hr_for(0.5))
    assert fl.idle_s == 0


def test_no_sensor_data_counts_as_idle():
    fl = make()
    ride(fl, 0, 50)
    assert fl.idle_s == pytest.approx(50, abs=1)


def test_idle_timeout_forces_off():
    fl = make(idle_off_min=1)
    t, _ = ride(fl, 0, 120, power=150, cadence=90, hr=hr_for(0.75))
    # stopped pedaling while HR is still high: idle after 60 s forces 0
    _, levels = ride(fl, t, 70, power=0, cadence=0, hr=hr_for(0.95))
    assert levels[-1] == 0


def test_power_without_cadence_detects_stop():
    # power meter / trainer that sends no crank data: cadence stays None, the stop is seen from power
    fl = make(idle_off_min=3)
    t, levels = ride(fl, 0, 300, power=230, cadence=None)
    assert levels[-1] == 3
    t, levels = ride(fl, t, 64, power=0, cadence=None)
    assert levels[-1] == 3                    # 5 s to detect + 60 s hold
    t, levels = ride(fl, t, 60, power=0, cadence=None)
    assert levels[-1] == 2                    # then one level per minute
    t, levels = ride(fl, t, 60, power=0, cadence=None)
    assert levels[-1] == 0                    # idle 3 min: off
    assert fl.idle_s >= 180


def test_heart_rate_only_ride():
    # strap only, for longer than the idle timeout: the fan follows HR up and back down
    fl = make(idle_off_min=5)
    t, warm = ride(fl, 0, 120, hr=hr_for(0.3))
    assert max(warm) == 0
    t, hard = ride(fl, t, 15 * 60, hr=hr_for(0.95))
    assert hard[-1] == 3                      # not switched off after 5 min
    t, easy = ride(fl, t, 6 * 60, hr=hr_for(0.2))
    assert easy[-1] == 0                      # steps down as HR falls
    assert all(b - a <= 0 for a, b in zip(easy, easy[1:]))   # one way, down


# --- whole ride ------------------------------------------------------------------------------

def test_whole_ride():
    """Warm-up, intervals, stop, cool-down, trainer off: sane levels throughout."""
    fl = make()
    t = 0
    seq = []
    for seconds, p, cad, hr in [
        (300, 100, 85, 110), (600, 160, 90, 140), (180, 230, 95, 165), (300, 120, 85, 150),
        (40, 0, 0, 140), (600, 170, 90, 150), (300, 90, 80, 120), (600, None, None, None),
    ]:
        t, levels = ride(fl, t, seconds, power=p, cadence=cad, hr=hr)
        seq += levels
    assert all(0 <= lv <= 3 for lv in seq)
    assert all(abs(b - a) <= 1 for a, b in zip(seq, seq[1:]))
    assert max(seq) == 3            # the hard interval reaches level 3
    assert seq[-1] == 0             # off after the trainer is switched off


# --- fan response presets ------------------------------------------------------------------

@pytest.mark.parametrize("response, hold", [("calm", 90), ("normal", 60), ("quick", 30)])
def test_response_sets_stop_hold(response, hold):
    fl = make(response=response)
    t, _ = ride(fl, 0, 300, power=150, cadence=90, hr=hr_for(0.75))
    assert fl.level == 2
    _, levels = ride(fl, t, 300, power=0, cadence=0, hr=hr_for(0.75))
    assert first_change(levels, 2) == 5 + hold


@pytest.mark.parametrize("response, tau", [("calm", 20), ("normal", 12), ("quick", 6)])
def test_response_sets_power_rise(response, tau):
    fl = make(response=response)
    for t in range(tau + 1):
        fl.update(t, 200, 90, None)
    assert fl.p_ema == pytest.approx(200 * (1 - math.exp(-1)), rel=0.02)


def test_unknown_response_falls_back_to_normal():
    fl = make(response="bogus")
    for t in range(13):
        fl.update(t, 200, 90, None)
    assert fl.p_ema == pytest.approx(200 * (1 - math.exp(-1)), rel=0.02)


# --- switching from manual back to auto ------------------------------------------------------

def test_adopt_while_stopped_steps_down_per_minute():
    """Auto -> manual 3 -> Auto while not pedaling: continue from 3, one level down per 60 s."""
    fl = make()
    t, _ = ride(fl, 0, 300, power=0, cadence=0)         # long stop: fan_logic's own level is 0
    assert fl.level == 0
    fl.adopt(3, t)
    _, levels = ride(fl, t, 200, power=0, cadence=0)
    assert levels[0] == 3 and levels[59] == 3 and levels[60] == 2
    assert levels[119] == 2 and levels[120] == 1 and levels[180] == 0


def test_adopt_while_riding_hard_stays():
    fl = make()
    t, _ = ride(fl, 0, 300, power=230, cadence=90)      # p_score ~0.96: level 3
    fl.adopt(1, t)
    _, levels = ride(fl, t, 60, power=230, cadence=90)
    assert levels[0] == 1 and levels[-1] == 3           # steps up again, one per 15 s


def test_adopt_while_riding_easy_steps_down_after_dwell():
    fl = make()
    t, _ = ride(fl, 0, 300, power=60, cadence=90)       # p_score 0.3: level 0
    fl.adopt(3, t)
    _, levels = ride(fl, t, 200, power=60, cadence=90)
    assert levels[59] == 3 and levels[60] == 2 and levels[120] == 1 and levels[180] == 0


def test_adopt_without_sensors_steps_down_per_minute():
    fl = make()
    t, _ = ride(fl, 0, 300)                              # no data at all
    fl.adopt(2, t)
    _, levels = ride(fl, t, 150)
    assert levels[59] == 2 and levels[60] == 1 and levels[120] == 0


def test_adopt_after_long_idle_steps_down_instead_of_off():
    """Auto chosen by hand after 15+ min without pedaling (or without sensors): the idle timer
    restarts, so the fan steps down one level per minute instead of going off at once."""
    fl = make()                                          # idle_off_min 15
    t, _ = ride(fl, 0, 1000)                             # no sensors for ~17 min
    assert fl.idle_s >= 900
    fl.adopt(3, t)
    _, levels = ride(fl, t, 200)
    assert levels[59] == 3 and levels[60] == 2 and levels[120] == 1 and levels[180] == 0


def test_idle_still_turns_off_after_adopt():
    fl = make(idle_off_min=5)
    t, _ = ride(fl, 0, 400, power=0, cadence=0)
    fl.adopt(1, t)
    _, levels = ride(fl, t, 400, power=0, cadence=0)
    assert fl.idle_s >= 300 and levels[-1] == 0


def test_adopt_keeping_idle_goes_off():
    """The idle timeout's own switch from manual to auto: off at once, as the spec says."""
    fl = make(idle_off_min=1)
    t, _ = ride(fl, 0, 120, power=0, cadence=0)
    fl.adopt(3, t, restart_idle=False)
    assert fl.update(t, 0, 0, None) == 0


# --- auto nudge ------------------------------------------------------------------------------

def test_nudge_adds_whole_levels():
    # power score 0.55: level 1; +1 -> 2, +2 -> 3, -1 -> 0
    for nudge, want in ((0, 1), (1, 2), (2, 3), (-1, 0)):
        fl = make()
        fl.nudge = nudge
        _, levels = ride(fl, 0, 300, power=0.55 * 200, cadence=90)
        assert levels[-1] == want, (nudge, levels[-1])
        assert fl.level == 1                     # the computed level itself is unchanged


def test_nudge_is_capped_at_3():
    fl = make()
    fl.nudge = 2
    _, levels = ride(fl, 0, 600, power=0.95 * 200, cadence=90)
    assert fl.level == 3 and levels[-1] == 3


def test_nudge_switches_on_while_pedalling_easily():
    fl = make()
    fl.nudge = 1
    _, levels = ride(fl, 0, 120, power=0.25 * 200, cadence=80)
    assert fl.level == 0 and levels[-1] == 1


def test_nudge_does_not_switch_on_when_not_pedalling():
    fl = make()
    fl.nudge = 1
    _, levels = ride(fl, 0, 120, power=0, cadence=0)          # trainer on, rider not pedalling
    assert max(levels) == 0
    fl2 = make()
    fl2.nudge = 1
    _, levels = ride(fl2, 0, 120)                             # no sensor data at all
    assert max(levels) == 0


def test_nudge_resets_when_the_ride_ends():
    fl = make(idle_off_min=1)
    fl.nudge = 1
    t, _ = ride(fl, 0, 120, power=0.6 * 200, cadence=90)
    assert fl.nudge == 1
    ride(fl, t, 70, power=0, cadence=0)          # stopped for the idle time: off, nudge cleared
    assert fl.target == 0 and fl.nudge == 0


def test_max_level_caps_auto_and_the_nudge():
    fl = make(max_level=2)
    fl.nudge = 1
    _, levels = ride(fl, 0, 600, power=0.95 * 200, cadence=90)
    assert max(levels) == 2


def test_max_level_steps_down_promptly_after_a_stop():
    # with max 2 the computed level stays at 2, so a stop steps 2 -> 1 -> 0 without a hidden extra step
    fl = make(max_level=2)
    t, _ = ride(fl, 0, 600, power=0.95 * 200, cadence=90)
    assert fl.level == 2
    _, levels = ride(fl, t, 5 + 60 + 120 + 2, power=0, cadence=0)
    assert levels[-1] == 0


# --- what decides (setting "use") -------------------------------------------------------

@pytest.mark.parametrize("use, demand", [("both", 0.9), ("power", 0.5), ("hr", 0.9)])
def test_use_picks_the_score(use, demand):
    fl = make(use=use, ftp=200, hr_rest=60, hr_max=160)
    ride(fl, 0, 120, power=100, cadence=90, hr=150)   # power score 0.5, heart-rate score 0.9
    assert fl.demand == pytest.approx(demand, abs=0.02)


def test_use_falls_back_when_the_chosen_sensor_is_missing():
    fl = make(use="power", ftp=200, hr_rest=60, hr_max=160)
    ride(fl, 0, 60, power=None, cadence=None, hr=150)
    assert fl.demand == pytest.approx(0.9, abs=0.02)        # no power: heart rate steps in
    fl = make(use="hr", ftp=200)
    ride(fl, 0, 120, power=100, cadence=90, hr=None)
    assert fl.demand == pytest.approx(0.5, abs=0.02)        # no heart rate: power steps in


def test_basis_says_what_decided():
    """Shown on the page next to demand: which sensor decided."""
    for use, both, p_only, hr_only in (("both", "both", "power", "hr"), ("power", "power", "power", "hr"),
                                       ("hr", "hr", "power", "hr")):
        logic = FanLogic(dict(config.DEFAULTS, use=use))
        logic.update(0, 150, 85, 130)
        assert logic.basis == both, use
        logic.update(1, 150, 85, None)
        assert logic.basis == p_only, use                  # heart rate missing: power steps in
        logic.update(2, None, None, 130)
        assert logic.basis == hr_only, use
        logic.update(3, None, None, None)
        assert logic.basis is None


def test_why_the_level_changed():
    """The reason goes into the logbook line of each fan level change (main.py)."""
    fl = make()
    ride(fl, 0, 60, power=200, cadence=90)                  # demand 1.0: up, one level per dwell
    assert fl.level >= 1 and fl.why.startswith("demand ") and ">=" in fl.why and "(power)" in fl.why
    ride(fl, 60, 200, power=0, cadence=0)                   # stopped: hold, then steps down
    assert fl.why == "stopped pedaling"
    fl2 = make()
    ride(fl2, 0, 60, power=200, cadence=90)
    ride(fl2, 60, 400, power=None, cadence=None, hr=None)   # no sensor data at all
    assert fl2.why == "no sensor data"
