"""Write docs/demo.html: the fan's real page (firmware/www/index.html) as a demo on the project site.

The page stays exactly the fan's page; docs/demo.js (hand-written) loads before the page's own script and answers
its requests in the browser: a made-up rider, and the auto mode copied from firmware/fan_logic.py. Run after
editing firmware/www/index.html, firmware/config.py (defaults) or firmware/version.py:

    python tools/make_site_demo.py

A test (firmware/tests/test_site_demo.py) fails while docs/demo.html is out of date. The copy only changes what
works on the fan alone: the title, the home-screen icon, the help link (to the site's manual), and the demo's
scripts (the firmware's default settings and version, then demo.js) before the page's script.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(HERE, "..", "firmware")
SRC = os.path.join(FW, "www", "index.html")
DST = os.path.join(HERE, "..", "docs", "demo.html")
SECRETS = ("wifi_password", "settings_pin", "link_key", "follow_key")   # never in the demo (all empty anyway)

STAMP = "<!-- generated from firmware/www/index.html by tools/make_site_demo.py: edit that file, not this one -->\n"


def init_json():
    """The firmware's default settings (the demo's Reset buttons use them) and its version, from the firmware."""
    sys.path.insert(0, FW)
    try:
        import config
        import version
    finally:
        sys.path.pop(0)
    defaults = {k: v for k, v in config.DEFAULTS.items() if k not in SECRETS}
    return json.dumps({"version": version.VERSION, "board": version.BOARD, "defaults": defaults},
                      sort_keys=True, ensure_ascii=False)


def changes():
    """(fan page text, demo page text): each must occur exactly once in the source."""
    return [
        ('<title>WattWind</title>', '<title>WattWind: live demo</title>'),
        ('<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n', ''),
        ('<meta name="apple-mobile-web-app-title" content="WattWind">\n', ''),
        ('<a href="/help" class="help"', '<a href="help.html" class="help"'),
        ('<script>\nvar $=function',
         '<script>var DEMO_INIT=' + init_json() + ';</script>\n<script src="demo.js"></script>\n<script>\nvar $=function'),
    ]


def render(src_text):
    nl = "\r\n" if "\r\n" in src_text else "\n"
    out = src_text.replace("\r\n", "\n")
    for a, b in changes():
        if out.count(a) != 1:
            raise SystemExit("make_site_demo: expected exactly one %r in index.html" % a[:50])
        out = out.replace(a, b)
    first = out.index("\n") + 1                      # after the doctype line
    out = out[:first] + STAMP + out[first:]
    return out.replace("\n", nl)


def main():
    with open(SRC, encoding="utf-8", newline="") as f:
        text = render(f.read())
    with open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("docs/demo.html written (%d bytes)" % len(text.encode("utf-8")))


if __name__ == "__main__":
    sys.exit(main())
