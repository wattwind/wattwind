"""Shared runtime state. Every task reads and writes this one module.

Tasks never switch relays themselves: they set mode / manual_level here,
and the control task in main.py applies it with relay.set_level().
"""

# Mode
mode = "auto"            # "auto", "manual" or "follow" (same-level follower); starts in auto / follow (relays off)
manual_level = 0         # level chosen in manual mode (0-3)
manual_since_s = 0       # uptime when manual mode was chosen
nudge = 0                # auto nudge -2..2 (effort counts 15 % more per step); cleared by manual and at ride end
auto_available = False   # True once the control task has started fan_logic

# Fan
target_level = 0         # what the control task wants
level = 0                # what the relays actually are

# Sensors (None = missing)
power = None
cadence = None
hr = None
hr_connected = False
power_connected = False
hr_name = ""             # advertised name of the connected sensor
power_name = ""

# Auto-mode diagnostics
p_ema = None
p_score = None
hr_score = None
demand = None
basis = None             # what decided the demand: "power", "hr", "both" or None (fan_logic.basis)
hr_off = None            # heart-rate sensor connected but not worn: "contact" / "beats" (ble_parse.HrContact), else None
hr_caps = ""             # what the connected heart-rate sensor reports (contact flag, beat times)

# Network
wifi_mode = "off"        # "off", "connecting", "sta" or "ap"
wifi_ssid = ""           # network joined (sta) or broadcast (ap)
ip = ""                  # "" while not connected
wifi_test = {"state": "idle", "ssid": "", "ip": "", "error": ""}   # test join from the AP
wifi_test_request = None # (ssid, password): set by the web API, taken by the Wi-Fi task
notice = ""              # one-time message for the page (e.g. after the PIN reset)
safe_start = False       # started with default ride settings after repeated crashes (main.py); settings can't be saved
page_seen_s = -9999        # uptime of the last status poll from the page (someone is using it)
manual_left_s = None     # seconds until manual hands back to auto (None: not in manual / no timeout)
files = ""                # firmware file check (integrity.py): "ok", "changed: ...", "not checked ..."
reset_reason = ""         # why the Pico last started (diagnostics on the page)
rssi = None              # Wi-Fi signal in dBm while on the home network
box_temp = None          # temperature inside the box, from the Pico's own sensor, degC (smoothed)
hr_battery = None        # battery % reported by the sensors (Battery Service), None if not offered
power_battery = None
share = "off"            # heart rate sharing (ble_share.py): "off", "waiting" (advertising) or "connected"
share_sent = 0           # readings passed on to the connected receiver
share_name = ""          # the name the fan shows itself under as a heart-rate sensor (WattWind-XXXX HR)
rider = ""               # active rider's name when there are several profiles ("" with one)
rider_by_hand = False    # a rider chosen on the page stays until chosen again or restart: no automatic switching
off_at_s = None          # manual "off in ..." timer: uptime when the fan turns off (None: no timer)
reboot_requested = False # set by the web API (new Wi-Fi settings, reboot button); main.py reboots
reboot_reason = ""       # with reboot_requested: what the logbook and the page say (default: restart from the page)
erase_requested = False   # POST /api/erase: main.py deletes the user files, then restarts
host_refused = 0         # requests refused by the DNS rebinding guard (web.py)
pin_fails = 0            # wrong settings PINs in a row (web.py slows guessing)
pin_wait_until = 0       # no PIN accepted before this uptime
update_until_s = 0       # a firmware update is coming in until this uptime: fan off (updater.py, web.py)

# Linked fans (link.py)
link_id = ""             # this fan's id on the network (WattWind-XXXX)
follow = None            # {"id", "name", "mode", "offset"} of the leader this fan follows; None = own sensors
follow_same = False      # a same-level follower: its default mode is "follow" instead of "auto"
leader_level = None      # followed leader's running level (None: not heard for link.STALE_S)
leader_seen_s = None     # uptime of the last packet from the followed leader
follow_fresh = False     # followed leader heard recently
follow_unpaired = False  # followed leader heard, but with a new key (it pressed "Unpair all followers")
leaders_heard = []       # [{"id", "name", "ip", "age_s"}] leaders on the network (for the page)
pair_until_s = 0         # leader: pairing window open until this uptime

heartbeats = {}          # task name -> time.ticks_ms() of last "I'm alive"
uptime_s = 0


def set_manual(new_level):
    global mode, manual_level, manual_since_s, target_level, nudge, off_at_s
    mode = "manual"
    nudge = 0
    if new_level == 0:
        off_at_s = None        # already off: nothing left for the timer to do
    manual_level = new_level
    target_level = new_level   # at once, so the reply to POST /api/mode doesn't show the old target
    manual_since_s = uptime_s


def set_auto():
    """Back to the default mode: "auto", or "follow" on a same-level follower."""
    global mode, off_at_s
    mode = "follow" if follow_same else "auto"
    off_at_s = None            # the off timer belongs to manual (ordinary-fan use)
