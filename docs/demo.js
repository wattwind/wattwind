/* WattWind demo: a pretend fan inside the browser, for the site's demo.html.

demo.html is the fan's real page (firmware/www/index.html, copied by tools/make_site_demo.py). This script loads
before the page's own script and answers its requests (/api/...) here in the browser instead of a fan: a made-up
rider does a workout at 10x speed, and the auto mode decides with a copy of the fan's logic (firmware/fan_logic.py),
so the levels, the dwell times, stopping and the idle off behave as on a real fan. Settings change only this page's
memory; a reload starts again. Links to the internet (Check for updates) go out as normal.

Old-style JavaScript like the page (var, function, .then): it must run wherever the page runs.
Keep in step with firmware/fan_logic.py: tests/test_site_demo.py checks the constants and the file's checksum
(LOGIC_SHA below); after changing fan_logic.py, port the change here and update LOGIC_SHA.
*/
(function () {
var INIT = window.DEMO_INIT || {};          // written by tools/make_site_demo.py: the firmware's defaults and version
var realFetch = window.fetch ? window.fetch.bind(window) : null;

// ---- auto mode: a copy of firmware/fan_logic.py -------------------------------------------------------------------
var LOGIC_SHA = '1b177db6b33b';             // first 12 hex digits of fan_logic.py's SHA-256 this copy matches
var RESPONSES = {calm: [20, 120, 90], normal: [12, 75, 60], quick: [6, 40, 30]};
var TAU_HR_S = 5, STOP_POWER_W = 20, STOP_DETECT_S = 5, LOST_HOLD_S = 120, FORCED_STEP_S = 60, NUDGE_MAX = 2;

function ema(value, target, dt, tau) { return value + (target - value) * (1 - Math.exp(-dt / tau)); }
function maxLevel(cfg) { return cfg.max_level == null ? 3 : cfg.max_level; }

function FanLogic(cfg) {
  this.cfg = cfg; this.level = 0; this.p_ema = null; this.hr_f = null;
  this.p_score = null; this.hr_score = null; this.demand = null; this.basis = null; this.idle_s = 0;
  this._last_t = null; this._level_since = null; this._stop_since = null; this._lost_since = null;
  this._idle_since = null; this._forced_next = null; this.nudge = 0; this.target = 0; this.why = '';
}
FanLogic.prototype.update = function (now, power, cadence, hr) {
  var cfg = this.cfg, r = RESPONSES[cfg.response] || RESPONSES.normal, tauUp = r[0], tauDown = r[1], hold = r[2];
  var dt = this._last_t === null ? 0 : Math.max(0, now - this._last_t);
  this._last_t = now;
  if (this._level_since === null) this._level_since = now;
  if (power !== null) {
    if (this.p_ema === null) this.p_ema = 0;
    this.p_ema = ema(this.p_ema, power, dt, power > this.p_ema ? tauUp : tauDown);
    this.p_score = Math.max(0, this.p_ema / cfg.ftp);
  } else this.p_score = null;
  if (hr !== null) {
    this.hr_f = this.hr_f === null ? hr : ema(this.hr_f, hr, dt, TAU_HR_S);
    this.hr_score = Math.max(0, (this.hr_f - cfg.hr_rest) / (cfg.hr_max - cfg.hr_rest));
  } else this.hr_score = null;
  var ps = this.p_score, hs = this.hr_score, use = cfg.use || 'both';
  if (use === 'power' && ps !== null) hs = null;
  else if (use === 'hr' && hs !== null) ps = null;
  var scores = [ps, hs].filter(function (s) { return s !== null; });
  this.demand = scores.length ? Math.max.apply(null, scores) : null;
  this.basis = ps !== null && hs !== null ? 'both' : ps !== null ? 'power' : hs !== null ? 'hr' : null;

  var stopped = (cadence !== null && cadence === 0) || (power !== null && power < STOP_POWER_W);
  this._stop_since = stopped ? (this._stop_since !== null ? this._stop_since : now) : null;
  var lost = power === null && hr === null;
  this._lost_since = lost ? (this._lost_since !== null ? this._lost_since : now) : null;
  if (stopped || lost) {
    if (this._idle_since === null) this._idle_since = now;
    this.idle_s = now - this._idle_since;
  } else { this._idle_since = null; this.idle_s = 0; }

  var ml = maxLevel(cfg);
  if (this.level > ml) this._set(ml, now, 'highest level ' + ml);
  if (this.idle_s >= cfg.idle_off_min * 60) {
    this._forced_next = null; this.nudge = 0;
    this._set(0, now, 'no riding for ' + cfg.idle_off_min + ' min');
  } else if (lost) this._forcedDown(now, this._lost_since + LOST_HOLD_S, 'no sensor data');
  else if (stopped && now - this._stop_since >= STOP_DETECT_S)
    this._forcedDown(now, this._stop_since + STOP_DETECT_S + hold, 'stopped pedaling');
  else { this._forced_next = null; this._hysteresis(now, stopped); }
  var t = this.level + this.nudge;
  if (this.level === 0 && this.nudge > 0 && (stopped || lost)) t = 0;
  this.target = Math.max(0, Math.min(ml, t));
  return this.target;
};
FanLogic.prototype.adopt = function (level, now, restartIdle) {
  this.level = level; this.target = Math.max(0, Math.min(3, level + this.nudge));
  this._level_since = now; this._forced_next = now + FORCED_STEP_S;
  if (restartIdle !== false && this._idle_since !== null) { this._idle_since = now; this.idle_s = 0; }
};
FanLogic.prototype._forcedDown = function (now, first, why) {
  if (this._forced_next === null) this._forced_next = first;
  if (this.level > 0 && now >= this._forced_next) { this._set(this.level - 1, now, why); this._forced_next = now + FORCED_STEP_S; }
};
FanLogic.prototype._hysteresis = function (now, stopped) {
  if (this.demand === null) return;
  var cfg = this.cfg, at = now - this._level_since, lv = this.level;
  if (lv < maxLevel(cfg) && !stopped && this.demand >= cfg.up_thresholds[lv] && at >= cfg.dwell_up_s)
    this._set(lv + 1, now, 'demand ' + this.demand.toFixed(2) + ' >= ' + cfg.up_thresholds[lv] + ' (' + this.basis + ')');
  else if (lv > 0 && this.demand < cfg.down_thresholds[lv - 1] && at >= cfg.dwell_down_s)
    this._set(lv - 1, now, 'demand ' + this.demand.toFixed(2) + ' < ' + cfg.down_thresholds[lv - 1] + ' (' + this.basis + ')');
};
FanLogic.prototype._set = function (level, now, why) {
  if (level !== this.level) { this.level = level; this._level_since = now; this.why = why || ''; }
};
window.DemoFanLogic = FanLogic;             // to compare it with fan_logic.py in a browser (same inputs, same levels)

// ---- settings (like config.py, profiles.py, checks.py) -------------------------------------------------------------
var FIELDS = ['ftp', 'hr_max', 'hr_rest', 'use', 'response', 'up_thresholds', 'down_thresholds', 'hr_addr'];
var DEFAULTS = INIT.defaults || {};
function copy(v) { return v && v.slice ? v.slice() : v; }
function clone(o) { return JSON.parse(JSON.stringify(o)); }
var cfg = clone(DEFAULTS);
cfg.hostname = 'wattwind'; cfg.wifi_ssid = 'HomeWiFi';
cfg.ftp = 240; cfg.hr_max = 186; cfg.hr_rest = 52;
cfg.hr_addr = 'c4:11:22:33:44:55'; cfg.power_addr = 'd8:66:77:88:99:aa';
function profileOf(name, from) { var p = {name: name}; FIELDS.forEach(function (f) { p[f] = copy(from[f]); }); return p; }
var sam = profileOf('Sam', DEFAULTS); sam.ftp = 205; sam.hr_max = 192; sam.hr_rest = 58; sam.hr_addr = '';
cfg.profiles = [profileOf('Alex', cfg), sam]; cfg.profile = 0;
function sync() {
  var i = cfg.profile, p = cfg.profiles[i];
  FIELDS.forEach(function (f) { p[f] = copy(cfg[f]); });
  if (p.hr_addr) cfg.profiles.forEach(function (q, j) { if (j !== i && q.hr_addr === p.hr_addr) q.hr_addr = ''; });
}
function activate(i) { sync(); cfg.profile = i; FIELDS.forEach(function (f) { cfg[f] = copy(cfg.profiles[i][f]); }); }
function riderName() { return cfg.profiles.length > 1 ? cfg.profiles[cfg.profile].name : ''; }
function publicCfg() {
  var o = clone(cfg);
  ['wifi_password', 'ap_password', 'settings_pin', 'link_key', 'follow_key'].forEach(function (k) { delete o[k]; });
  o.pin_set = true; o.ap_default = false;   // the demo fan is set up; it never asks for its (made-up) PIN
  return o;
}
var NUMBERS = {ftp: [50, 1000, 'FTP (W)'], hr_max: [100, 230, 'HR max (bpm)'], hr_rest: [30, 120, 'HR rest (bpm)'],
  dwell_up_s: [0, 600, 'Min. time before step up (s)'], dwell_down_s: [0, 600, 'Min. time before step down (s)'],
  manual_timeout_min: [0, 1440, 'Manual → auto after (min)'], idle_off_min: [1, 600, 'Auto: off after no pedaling (min)'],
  max_level: [1, 3, 'Auto: highest level']};
function checkSettings(d) {                 // the rules of checks.py, with its messages (the page marks the field)
  var m = clone(cfg), changed = [], k, i;
  for (k in d) {
    if (k === 'pin' || !d.hasOwnProperty(k)) continue;
    var v = d[k], n = NUMBERS[k];
    if (n && (typeof v !== 'number' || v % 1 || v < n[0] || v > n[1])) throw new Error(n[2] + ': a whole number from ' + n[0] + ' to ' + n[1]);
    if ((k === 'up_thresholds' || k === 'down_thresholds') && !(v.length === 3 && v.every(function (x) { return x > 0 && x <= 2; })))
      throw new Error('Step ' + (k === 'up_thresholds' ? 'up' : 'down') + ': each value must be a number above 0 and at most 2');
    if (k === 'hostname' && !/^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/.test(v))
      throw new Error('Hostname: 1 to 32 characters, only a-z, 0-9 and - (no - at the start or end)');
    if (k === 'ap_password' && (v.length < 8 || v.length > 63)) throw new Error('Access point password: 8 to 63 characters');
    if (k === 'ap_password' && v === DEFAULTS.ap_password) throw new Error('Access point password: choose your own, not the default');
    if (k === 'settings_pin' && (v.length < 4 || v.length > 16)) throw new Error('Settings PIN: 4 to 16 characters (a PIN can be changed, not removed)');
    if (k === 'settings_pin' || k === 'ap_password') { changed.push(k); continue; }   // the demo keeps no secrets
    if (JSON.stringify(m[k]) !== JSON.stringify(v)) { m[k] = v; changed.push(k); }
  }
  if (m.hr_rest >= m.hr_max) throw new Error('HR rest must be below HR max');
  var up = m.up_thresholds, down = m.down_thresholds;
  for (i = 0; i < 3; i++) if (!(down[i] < up[i])) throw new Error('Level ' + (i + 1) + ': step down (' + down[i] + ') must be below step up (' + up[i] + ')');
  [['up', up], ['down', down]].forEach(function (r) {
    for (i = 0; i < 2; i++) if (!(r[1][i] < r[1][i + 1]))
      throw new Error('Step ' + r[0] + ': level ' + (i + 1) + ' (' + r[1][i] + ') must be below level ' + (i + 2) + ' (' + r[1][i + 1] + ')');
  });
  changed.forEach(function (k) { if (k in m) cfg[k] = m[k]; });
  sync();
  return changed.sort();
}

// ---- the made-up rider: a workout, power and cadence from it, heart rate following the effort ------------------------
var PLAN = [[20, 0, 0, 'getting on the bike'], [600, 110, 175, 'warm-up'], [420, 195, 195, 'tempo']];
for (var n = 1; n <= 4; n++) PLAN.push([180, 300, 300, 'interval ' + n + ' of 4'], [120, 140, 140, 'recovery']);
PLAN.push([360, 185, 185, 'steady'], [300, 140, 110, 'cool-down']);
var RIDE_S = PLAN.reduce(function (a, p) { return a + p[0]; }, 0);
var BODY = {ftp: 240, hr_max: 186, hr_rest: 52};    // the rider's real body; the settings may say otherwise

function planAt(t) {
  for (var i = 0, s = 0; i < PLAN.length; s += PLAN[i][0], i++)
    if (t < s + PLAN[i][0]) { var p = PLAN[i], f = (t - s) / p[0]; return {w: p[1] + (p[2] - p[1]) * f, what: p[3]}; }
  return {w: 0, what: 'ride over: resting'};
}

// ---- the pretend fan ---------------------------------------------------------------------------------------------------
var S, logic, logLines, speed = 10, paused = false, coast = false, offUntil = 0;
function boot(reason) {
  S = {up: 0, ride: 0, mode: 'auto', level: 0, target: 0, manual_level: 0, manual_since: 0, off_at: null,
    manual_left: null, nudge: 0, last_switch: -9, prev_mode: 'auto', idle_logged: false, logic_level: 0,
    power: null, cadence: null, hr: null, hr_body: 68, notice: '', detail: S ? S.detail : null, pair_until: 0,
    share: cfg.hr_share ? 'waiting' : 'off', share_at: 0, reset_reason: reason};
  logic = new FanLogic(cfg);
  logLines = logLines || [];
  event('START WattWind ' + (INIT.version || '?') + ' (' + reason + ')');
}
function event(t) { logLines.push('up=' + S.up + ' ' + t); if (logLines.length > 400) logLines.shift(); }

function second() {                         // one second of the fan's life (main.py's control loop, simplified)
  S.up++;
  var p = planAt(S.ride), w = coast ? 0 : p.w;
  S.ride++;
  if (w > 0) {
    S.power = Math.max(0, Math.round(w * (1 + (Math.random() - 0.5) * 0.08)));
    S.cadence = Math.round((w > 250 ? 96 : 88) + (Math.random() - 0.5) * 6);
  } else { S.power = 0; S.cadence = 0; }
  var goal = BODY.hr_rest + (BODY.hr_max - BODY.hr_rest) * (w > 0 ? 0.15 + 0.6 * w / BODY.ftp : 0.12);
  S.hr_body = ema(S.hr_body, Math.min(goal, BODY.hr_max - 4), 1, goal > S.hr_body ? 25 : 40);
  S.hr = Math.round(S.hr_body + (Math.random() - 0.5) * 2);

  logic.nudge = S.mode === 'auto' ? S.nudge : 0;
  logic.update(S.up, S.power, S.cadence, S.hr);
  var idle = S.mode === 'auto' && logic.idle_s >= cfg.idle_off_min * 60;
  if (idle && !S.idle_logged) event('idle off: no riding for ' + cfg.idle_off_min + ' min, ride over');
  S.idle_logged = idle;
  if (S.mode === 'auto') S.nudge = logic.nudge;
  if (S.mode === 'manual') {
    var inManual = S.up - S.manual_since, timeout = cfg.manual_timeout_min * 60;
    S.manual_left = timeout ? Math.max(0, timeout - inManual) : null;
    if (S.off_at !== null && S.up >= S.off_at) { event('off timer ran out: fan off'); setManual(0); }
    else if (timeout && inManual >= timeout) { event('manual for ' + cfg.manual_timeout_min + ' min: back to Auto'); setAuto(); }
  } else S.manual_left = null;
  if (S.mode === 'auto' && S.prev_mode !== 'auto') logic.adopt(S.level, S.up);
  S.prev_mode = S.mode;
  S.target = S.mode === 'manual' ? S.manual_level : logic.target;
  if (S.target !== S.level && S.up - S.last_switch >= 2) {       // relay.py: at most one change per 2 s
    var why = S.mode === 'manual' ? 'manual' : logic.level !== S.logic_level ? 'auto: ' + logic.why
      : S.nudge ? 'auto: nudge ' + (S.nudge > 0 ? '+' : '') + S.nudge : 'auto';
    if (S.mode === 'auto') S.logic_level = logic.level;
    event('fan ' + S.level + ' -> ' + S.target + ' (' + why + ')');
    S.level = S.target; S.last_switch = S.up;
  }
  if (S.share === 'waiting' && S.up >= S.share_at) S.share = 'connected';
  if (S.detail && S.detail.on) { S.detail.left_s = Math.max(0, S.detail.left_s - 1); S.detail.kb = Math.round((S.up - S.detail.t0) * 0.06); }
}
function setManual(level) { S.mode = 'manual'; S.manual_level = level; S.manual_since = S.up; S.off_at = null; S.nudge = 0; }
function setAuto() { S.mode = 'auto'; S.off_at = null; }

function status() {
  return {
    setup: false, mode: S.mode, level: S.level, target: S.target, auto_available: true,
    power: S.power, cadence: S.cadence, hr: S.hr, hr_connected: true, power_connected: true,
    hr_name: 'HRM-Dual', power_name: 'KICKR CORE',
    p_ema: logic.p_ema, p_score: logic.p_score, hr_score: logic.hr_score, demand: logic.demand, basis: logic.basis,
    hr_off: false, hr_caps: 'contact, beat times', hr_share: S.share, hr_share_name: 'WattWind-4F2A HR',
    wifi: 'sta', ssid: 'HomeWiFi', ip: '192.168.1.50', rider: riderName(),
    uptime: S.up, notice: S.notice || null, manual_left_s: S.mode === 'manual' ? S.manual_left : null, nudge: S.nudge,
    off_left_s: S.off_at === null ? null : Math.max(0, S.off_at - S.up),
    version: INIT.version || '?', board: INIT.board || '?', reset_reason: S.reset_reason, files: 'ok',
    rssi: -58 - Math.round(Math.random() * 3), hr_battery: 80, power_battery: null,
    box_temp: 33 + S.level + (S.up % 7 ? 0 : 1), mem_free: 312000,
    link_id: 'a1b2c3', follow: null, pair_left_s: Math.max(0, S.pair_until - S.up), updating: false,
    detail: S.detail ? {on: S.detail.on, started: S.detail.started, left_s: S.detail.left_s, keep_s: 604800, kb: S.detail.kb} : null,
    safe_start: false, name: cfg.hostname
  };
}

// ---- the requests the page sends ----------------------------------------------------------------------------------------
var NOT_HERE = 'Not in the demo: there is no fan behind this page.';
function err(code, text) { return [{error: text}, code]; }
function handle(method, path, q, b) {
  var post = method === 'POST', i;
  if (path === '/api/status') return [status()];
  if (path === '/api/config' && !post) return [publicCfg()];
  if (path === '/api/config') {
    var ch; try { ch = checkSettings(b); } catch (e) { return err(400, e.message); }
    if (ch.indexOf('hr_share') >= 0) { S.share = cfg.hr_share ? 'waiting' : 'off'; S.share_at = S.up + 20; }
    if (ch.length) event('settings saved: ' + ch.join(', '));
    S.notice = ''; var o = publicCfg(); o.changed = ch; return [o];
  }
  if (path === '/api/mode') {
    if (b.mode === 'auto') {
      var nd = b.nudge !== undefined ? b.nudge : S.mode === 'auto' ? S.nudge : 0;
      if (nd % 1 || nd < -NUDGE_MAX || nd > NUDGE_MAX) return err(400, 'nudge must be -2 to 2');
      setAuto(); S.nudge = nd;
    } else if (b.mode === 'manual') {
      if (!(b.level >= 0 && b.level <= 3) || b.level % 1) return err(400, 'level must be 0-3');
      setManual(b.level);
    } else return err(400, 'mode must be auto or manual');
    S.target = S.mode === 'manual' ? S.manual_level : Math.max(0, Math.min(maxLevel(cfg), logic.level + S.nudge));
    event('button: ' + (b.mode === 'auto' ? 'Auto' + (S.nudge ? ' nudge ' + (S.nudge > 0 ? '+' : '') + S.nudge : '') : 'level ' + b.level));
    S.notice = ''; return [status()];
  }
  if (path === '/api/timer') {
    var m = b.minutes;
    if (m % 1 || m < 0 || m > 1440) return err(400, 'minutes must be 0 to 1440');
    if (m && (S.mode !== 'manual' || !S.manual_level)) return err(409, 'the timer is for a level picked by hand (1, 2 or 3)');
    S.off_at = m ? S.up + m * 60 : null; return [status()];
  }
  if (path === '/api/notice/dismiss') { S.notice = ''; return [status()]; }
  if (path === '/api/profile') {
    var ps = cfg.profiles, a = b.action; i = b.index;
    if (a !== 'add' && !(i >= 0 && i < ps.length)) return err(400, 'no such rider');
    var nm = typeof b.name === 'string' ? b.name.trim() : '';
    if ((a === 'add' || a === 'rename') && !(nm.length >= 1 && nm.length <= 16)) return err(400, 'Rider name: 1 to 16 characters');
    if (a === 'select') activate(i);
    else if (a === 'add') {
      if (ps.length >= 5) return err(400, 'At most 5 riders');
      var p = profileOf(nm, DEFAULTS); p.hr_addr = ''; sync(); ps.push(p); activate(ps.length - 1);
    } else if (a === 'rename') ps[i].name = nm;
    else if (a === 'delete') {
      if (ps.length <= 1) return err(400, "The last rider can't be deleted");
      var act = cfg.profile; sync(); ps.splice(i, 1);
      if (i === act) { cfg.profile = 0; FIELDS.forEach(function (f) { cfg[f] = copy(ps[0][f]); }); }
      else if (i < act) cfg.profile = act - 1;
    } else return err(400, 'action: select, add, rename or delete');
    event('rider ' + a + ': now ' + ps[cfg.profile].name); return [publicCfg()];
  }
  if (path === '/api/reset') {
    var keys = {rider: ['ftp', 'hr_max', 'hr_rest', 'use', 'response', 'up_thresholds', 'down_thresholds'],
      fan: ['dwell_up_s', 'dwell_down_s', 'manual_timeout_min', 'idle_off_min', 'max_level']}[b.what];
    if (!keys) return err(400, 'what: rider or fan');
    keys.forEach(function (k) { cfg[k] = copy(DEFAULTS[k]); }); sync();
    event('settings: ' + b.what + ' values back to the defaults'); return [publicCfg()];
  }
  if (path === '/api/scan') return [{devices: [
    {name: 'HRM-Dual', addr: 'c4:11:22:33:44:55', types: ['hr'], connected: true, rssi: null},
    {name: 'KICKR CORE', addr: 'd8:66:77:88:99:aa', types: ['power'], connected: true, rssi: null},
    {name: 'HRM-Pro', addr: 'e2:12:34:56:78:9a', types: ['hr'], connected: false, rssi: -74},
    {name: 'Assioma', addr: 'f1:98:76:54:32:10', types: ['power'], connected: false, rssi: -81}]}, 200, 3000];
  if (path === '/api/wifi/scan') return [{networks: [{ssid: 'HomeWiFi', rssi: -58, secure: true},
    {ssid: 'Neighbours', rssi: -77, secure: true}, {ssid: 'Cafe guest', rssi: -85, secure: false}]}, 200, 2000];
  if (path === '/api/link') return [{id: 'a1b2c3', name: cfg.hostname, follow: null, pair_left_s: Math.max(0, S.pair_until - S.up),
    heard: [{id: 'd4e5f6', name: 'wattwind2', ip: '192.168.1.51'}]}];
  if (path === '/api/link/pair') { S.pair_until = S.up + 60; return [{pair_left_s: 60}]; }
  if (path === '/api/link/unpair') { event('linked fans: new link key, every follower unpaired'); return [{ok: true}]; }
  if (path === '/api/follow') return err(409, 'Not in the demo: following needs a second fan on your network.');
  if (path === '/api/detail' && post) {
    if (b.action === 'start') S.detail = {on: true, started: new Date().toISOString().slice(0, 16).replace('T', ' ') + 'Z', left_s: 86400, kb: 0, t0: S.up};
    else if (b.action === 'stop' && S.detail) S.detail.on = false;
    else if (b.action === 'delete') S.detail = null;
    return [status()];
  }
  if (path === '/api/detail') return [S.detail ? 'WattWind detailed recording (demo: made-up values)\n' : '', S.detail ? 200 : 404, 0, 'text/plain'];
  if (path === '/api/log') return [q.old ? '' : logLines.join('\n') + '\n', 200, 0, 'text/plain'];
  if (path === '/api/diagnostics') return ['WattWind diagnostics (demo: made-up values)\n\nstatus:\n' + JSON.stringify(status()) +
    '\n\n== logbook ==\n' + logLines.join('\n') + '\n', 200, 0, 'text/plain'];
  if (path === '/api/backup') {
    var c = {}; for (var k in cfg) if (['wifi_password', 'ap_password', 'settings_pin', 'link_key', 'follow_key'].indexOf(k) < 0) c[k] = cfg[k];
    return [{wattwind_backup: 1, version: INIT.version, secrets: false, config: c}];
  }
  if (path === '/api/reboot') { offUntil = Date.now() + 5000; return [{ok: true}]; }
  if (path === '/api/restore' || path === '/api/erase' || path === '/api/wifi' || path === '/api/wifi/test' ||
      path === '/api/setup' || path.indexOf('/api/update/') === 0)
    return err(409, NOT_HERE + (path.indexOf('update') > 0 ? ' On your fan, this installs the update file.' : ''));
  return err(404, 'not found');
}

window.fetch = function (url, o) {
  url = String(url); o = o || {};
  var a = /^(?:https?:\/\/[^\/]+)?(\/api\/[^?#]*)(?:\?([^#]*))?/.exec(url.replace(/^\.?\/?(?=api\/)/, '/'));
  if (!a || /^https?:/.test(url)) {         // not the fan: the internet (Check for updates) as normal
    return realFetch ? realFetch(url, o) : Promise.reject(new TypeError('Failed to fetch'));
  }
  if (Date.now() < offUntil) return Promise.reject(new TypeError('Failed to fetch'));   // "restarting"
  if (offUntil) { offUntil = 0; boot('restart from the page'); }
  var q = {}; (a[2] || '').split('&').forEach(function (kv) { if (kv) q[kv.split('=')[0]] = decodeURIComponent(kv.split('=')[1] || ''); });
  var b = {}; try { b = o.body && typeof o.body === 'string' ? JSON.parse(o.body) : {}; } catch (e) { b = {}; }
  var r = handle((o.method || 'GET').toUpperCase(), a[1], q, b || {});
  var body = typeof r[0] === 'string' ? r[0] : JSON.stringify(r[0]);
  return new Promise(function (ok) {
    setTimeout(function () {
      ok(new Response(body, {status: r[1] || 200, headers: {'Content-Type': r[3] || 'application/json'}}));
    }, r[2] || 60);
  });
};

// ---- the bar on top: what this is, the ride clock, play / speed / stop pedaling --------------------------------------------
function clock(t) { var m = Math.floor(t / 60), s = t % 60; return m + ':' + (s < 10 ? '0' : '') + s; }
function bar() {
  var css = document.createElement('style');
  css.textContent = '.demo{background:var(--card);border:2px solid var(--acc);border-radius:12px;padding:10px 12px;margin-bottom:12px;font-size:14px}' +
    '.demo p{margin:0 0 8px}.demo .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}' +
    '.demo button,.demo select{height:40px;padding:0 12px;font-size:14px;width:auto}.demo .clk{flex:1 1 100%;font-weight:600}' +
    '.demo a{color:var(--acc)}';
  document.head.appendChild(css);
  var d = document.createElement('div'); d.className = 'demo'; d.id = 'demo';
  d.innerHTML = '<p><b>Demo</b>, no fan connected: a made-up rider does a ' + Math.round(RIDE_S / 60) + '-minute workout, sped up. Every button and ' +
    'setting works on this page only; reload to start again. <a href="index.html">← WattWind</a></p>' +
    '<div class="row"><span class="clk" id="dclk" aria-live="off"></span>' +
    '<button type="button" id="dplay">Pause</button>' +
    '<select id="dspeed" aria-label="speed"><option value="1">1×</option><option value="10" selected>10×</option><option value="30">30×</option></select>' +
    '<button type="button" id="dcoast">Stop pedaling</button><button type="button" id="dagain">Ride again</button></div>';
  var main = document.querySelector('main'); main.insertBefore(d, main.firstChild);
  document.getElementById('dplay').onclick = function () { paused = !paused; this.textContent = paused ? 'Play' : 'Pause'; show(); };
  document.getElementById('dspeed').onchange = function () { speed = +this.value; };
  document.getElementById('dcoast').onclick = function () { coast = !coast; this.textContent = coast ? 'Pedal again' : 'Stop pedaling'; show(); };
  document.getElementById('dagain').onclick = function () { S.ride = 0; coast = false; document.getElementById('dcoast').textContent = 'Stop pedaling'; show(); };
}
function show() {
  var e = document.getElementById('dclk'); if (!e) return;
  var what = coast ? 'not pedaling' : planAt(S.ride).what;
  e.textContent = (paused ? 'Paused · ' : '') + 'Ride ' + clock(Math.min(S.ride, RIDE_S)) + ' of ' + clock(RIDE_S) + ' · ' + what;
}

boot('power on');
var acc = 0, lastMs = Date.now();
setInterval(function () {
  var now = Date.now(), dt = Math.min(1000, now - lastMs); lastMs = now;
  if (paused || Date.now() < offUntil) return;
  acc += dt / 1000 * speed;
  while (acc >= 1) { acc -= 1; second(); }
  show();
}, 200);
bar(); show();
})();
