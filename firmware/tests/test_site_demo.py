"""The site's demo (docs/demo.html + docs/demo.js): generated from the fan's page, and its pretend fan in step with
the firmware. The JS logic itself was compared with fan_logic.py in a browser (window.DemoFanLogic, random rides)."""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import make_site_demo  # noqa: E402

FW = os.path.join(HERE, "..")
DEMO_JS = os.path.join(HERE, "..", "..", "docs", "demo.js")


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def test_demo_page_is_up_to_date():
    """docs/demo.html must be the current fan page: after editing firmware/www/index.html, config.py or
    version.py run python tools/make_site_demo.py."""
    expected = make_site_demo.render(_read(make_site_demo.SRC))
    assert _read(make_site_demo.DST) == expected, "docs/demo.html is out of date: run python tools/make_site_demo.py"


def test_demo_page_has_no_fan_only_links_or_secrets():
    page = _read(make_site_demo.DST)
    assert 'href="/help"' not in page and "apple-touch-icon" not in page and 'href="help.html"' in page
    init = json.loads(re.search(r"var DEMO_INIT=(\{.*?\});</script>", page).group(1))
    for k in make_site_demo.SECRETS:
        assert k not in init["defaults"]


def test_demo_logic_matches_fan_logic_version():
    """demo.js copies fan_logic.py. After changing fan_logic.py: port the change to demo.js,
    compare the two over the same inputs (window.DemoFanLogic in a browser), then set LOGIC_SHA."""
    with open(os.path.join(FW, "fan_logic.py"), "rb") as f:
        sha = hashlib.sha256(f.read().replace(b"\r", b"")).hexdigest()[:12]
    js = _read(DEMO_JS)
    assert "var LOGIC_SHA = '{}'".format(sha) in js, "fan_logic.py changed: update docs/demo.js (see this test)"


def test_demo_logic_constants():
    sys.path.insert(0, FW)
    import fan_logic
    js = _read(DEMO_JS)
    for name in ("TAU_HR_S", "STOP_POWER_W", "STOP_DETECT_S", "LOST_HOLD_S", "FORCED_STEP_S", "NUDGE_MAX"):
        assert re.search(r"\b{} = {}\b".format(name, getattr(fan_logic, name)), js), name
    for k, (a, b, c) in fan_logic.RESPONSES.items():
        assert "{}: [{}, {}, {}]".format(k, a, b, c) in js, k


def test_demo_answers_every_status_field_and_request():
    """The pretend fan gives every /api/status field the fan gives, and answers every request the page makes."""
    web = _read(os.path.join(FW, "web.py"))
    body = web[web.index("def status():"):web.index("\n\n", web.index("def status():"))]
    js = _read(DEMO_JS)
    status_js = js[js.index("function status()"):js.index("// ---- the requests")]
    for key in re.findall(r'"(\w+)":', body):
        assert re.search(r"\b{}:".format(key), status_js), "demo.js status() lacks " + key
    page = _read(make_site_demo.SRC)
    for path in set(re.findall(r"'(/api/[a-z/]+)", page)):
        group = path[:path.rindex("/") + 1]         # '/api/update/' answers start, file and finish
        assert "'" + path.rstrip("/") in js or "'" + group + "'" in js, "demo.js doesn't answer " + path


def test_demo_js_is_old_style():
    """Like the page (made to run on old phones too): no arrow functions, let/const, template strings."""
    js = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read(DEMO_JS), flags=re.S)
    assert "=>" not in js and "`" not in js
    assert not re.search(r"\b(let|const|async|await)\s", js)
