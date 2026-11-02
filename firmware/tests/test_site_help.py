import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import make_site_help  # noqa: E402


def test_site_manual_is_up_to_date():
    """docs/help.html must be the current fan help: after editing firmware/www/help.html run
    python tools/make_site_help.py."""
    with open(make_site_help.SRC, encoding="utf-8", newline="") as f:
        expected = make_site_help.render(f.read()).replace("\r\n", "\n")
    with open(make_site_help.DST, encoding="utf-8", newline="") as f:
        actual = f.read().replace("\r\n", "\n")
    assert actual == expected, "docs/help.html is out of date: run python tools/make_site_help.py"


def test_site_manual_has_no_fan_only_links():
    with open(make_site_help.DST, encoding="utf-8") as f:
        page = f.read()
    assert 'href="/"' not in page and "apple-touch-icon" not in page and 'href="index.html"' in page
