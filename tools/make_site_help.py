"""Write docs/help.html: the fan's user manual (firmware/www/help.html) as a page of the project site.

The fan's help page is the only source: edit firmware/www/help.html, then run

    python tools/make_site_help.py

A test (firmware/tests/test_site_help.py) fails while docs/help.html is out of date. The copy only changes
what works on the fan alone: the "back" link (to the site instead of the fan's page), the home-screen icon
link, the title, and a note at the top that the fan shows the same manual.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "firmware", "www", "help.html")
DST = os.path.join(HERE, "..", "docs", "help.html")

# (fan page text, site page text): each must occur exactly once in the source
CHANGES = [
    ('<title>WattWind: help</title>', '<title>WattWind: user manual</title>'),
    ('<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n', ''),
    ('</svg> help</h1><a class="back" href="/">← back</a></header>',
     '</svg> manual</h1><a class="back" href="index.html">← project</a></header>\n'
     '<p style="font-size:14px;color:var(--mute);margin:0 0 12px">The user manual of the WattWind fan. '
     'The fan shows this same page under the <b>?</b> next to its title (<i>/help</i>).</p>'),
]
STAMP = "<!-- generated from firmware/www/help.html by tools/make_site_help.py: edit that file, not this one -->\n"


def render(src_text):
    nl = "\r\n" if "\r\n" in src_text else "\n"
    out = src_text.replace("\r\n", "\n")
    for a, b in CHANGES:
        if out.count(a) != 1:
            raise SystemExit("make_site_help: expected exactly one %r in help.html" % a[:50])
        out = out.replace(a, b)
    first = out.index("\n") + 1                      # after the doctype line
    out = out[:first] + STAMP + out[first:]
    return out.replace("\n", nl)


def main():
    with open(SRC, encoding="utf-8", newline="") as f:
        text = render(f.read())
    with open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("docs/help.html written (%d bytes)" % len(text.encode("utf-8")))


if __name__ == "__main__":
    sys.exit(main())
