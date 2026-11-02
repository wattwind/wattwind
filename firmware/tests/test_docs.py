"""Docs stay in step with the features: each feature is described where riders and builders look for it, and phrases
that describe old behaviour don't come back. When a feature changes, update this list together with the docs."""
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DOCS = {"manual": "firmware/www/help.html", "site": "docs/index.html", "build": "docs/build.html",
        "features": "docs/features.html", "claude": "CLAUDE.md"}

# feature: phrase that must appear in each of these documents (case-insensitive)
FEATURES = {
    "decide by": ("Decide by", ["manual", "features", "claude"]),
    "decide by, site": ("power / heart rate / both", ["site"]),
    "firmware update": ("Firmware update", ["manual", "site", "build", "claude", "features"]),
    "unpair": ("Unpair all", ["manual", "site", "claude", "features"]),
    "one higher": ("one higher", ["manual", "site"]),
    "off timer": ("Off in 30 min", ["manual", "site", "features"]),
    "nudge": ("nudge", ["manual", "site", "claude", "features"]),
    "logbook": ("logbook", ["manual", "site", "claude", "features"]),
    "pico 2 w": ("Pico 2 W", ["site", "build", "claude"]),
    "fourth plug-in": ("fourth", ["manual", "site"]),
    "backup": ("Download settings", ["manual"]),
    "host check": ("not addressed to this fan", ["manual"]),
    "diagnostics": ("saves a diagnostics file", ["manual"]),
    "pin wait": ("too many wrong PINs", ["manual"]),
    "backup, site and notes": ("backup", ["site", "claude"]),
    "erase everything": ("Erase everything", ["manual", "build", "claude", "features"]),
    "your data": ("Your data", ["manual"]),
    "usb update mode": ("Plugging in USB changes nothing", ["build"]),
    "home assistant": ("rest_command", ["build"]),
    "first setup": ("Set up your fan", ["manual", "build"]),
    "forget pin": ("Forget the PIN on this device", ["manual"]),
    "signed updates": ("signature", ["manual", "build"]),
    "make keys": ("make_keys.py", ["build", "claude"]),
    "security and privacy": ("Security and privacy", ["site"]),
    "signing key": ("Your signing key", ["build"]),
    "strap not worn": ("not worn", ["manual", "claude", "features"]),
    "unsaved settings": ("Unsaved changes", ["manual"]),
    "settings groups": ("Wi-Fi and address", ["manual", "build"]),
    "test versions": ("Test version", ["manual", "build"]),
    "detailed recording": ("Detailed recording", ["manual", "site", "claude", "features"]),
    "maintenance group": ("Maintenance", ["manual", "site", "build", "claude"]),
    "failed relay": ("A relay contact has probably failed", ["manual"]),
    "safe start": ("Safe start", ["manual", "claude", "features"]),
    "settings checked at start": ("checked again at each start", ["site"]),
    "ride test": ("Same numbers as your bike computer", ["site"]),
    "check for updates": ("Check for updates", ["manual", "site", "build", "features", "claude"]),
    "release emails": ("Watch → Custom", ["manual", "build"]),
    "share heart rate": ("Share heart rate", ["manual", "site", "build", "claude", "features"]),
}

# phrases of old behaviour, anywhere in the docs or in the site's SVG images
STALE = [
    "Network name and PIN",                 # 0.9.81: the groups are "Wi-Fi and address" and "PIN"
    "Settings → Wi-Fi network",
    "shown at the top of",                  # the address moved from the page's top to Settings → Wi-Fi and address
    "<b>Save settings</b>",                 # the form's Save / Undo buttons are gone: the Unsaved bar saves (0.9.78)
    "Undo changes</b>",
    "the rest with Save settings",
    "home network again every",           # the first retry from the access point is after 2 min, then every 5
    "update mode</i>: normal",             # old restart reason after an update
    "USB</b> for firmware updates",         # updates go over Wi-Fi now
    "Pico W + 4 relays",                    # the Pico 2 W is the supported Pico
    "Pico W also works",
    "lines go first",                       # the logbook swaps whole files
    "not encrypted",                        # linked-fans packets are encrypted since 0.9.50
    "FTP 250",                              # examples use FTP 240 (the ride chart, the screenshots)
    "must run the same firmware",            # only updates that change the link need it
    "Remove settings PIN",                  # a PIN can be changed, not removed (0.9.53)
    "PIN if you like",
    "PIN on this phone",                    # remembered per device, not only phones
    "not yet for who made them",            # updates are signed since 0.9.57
    "what decides",                         # the setting is called "Decide by" (page, manual)
    "</i> unless changed",                  # the AP password is the user's own after the first setup
    "max 185 W   fuse",                     # the label's power follows the fuse and the mains voltage
    "PIN:</b> optional",
]


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def present(name):
    """The public copy has no CLAUDE.md (project notes): its checks are skipped there."""
    return os.path.exists(os.path.join(ROOT, DOCS[name]))


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_feature_is_documented(feature):
    phrase, where = FEATURES[feature]
    missing = [d for d in where if present(d) and phrase.lower() not in read(DOCS[d]).lower()]
    assert not missing, "{!r} not in: {}".format(phrase, ", ".join(DOCS[d] for d in missing))


def test_no_stale_phrases():
    files = [DOCS[d] for d in DOCS if present(d)] + ["firmware/www/index.html", "firmware/README.md"] + [
        "docs/img/" + n for n in os.listdir(os.path.join(ROOT, "docs", "img")) if n.endswith(".svg")]   # the page too
    hits = ["{}: {!r}".format(f, p) for f in files for p in STALE if p in read(f)]
    assert not hits, "old wording found: " + "; ".join(hits)
