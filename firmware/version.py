"""Firmware and board version, shown on the page. Semantic versioning: MAJOR.MINOR.PATCH.
0.x = before the first public release; the first GitHub release is 1.0.0 (tag v1.0.0).
Until then: bump the last number (0.9.1, 0.9.2, ...) every time new firmware goes onto the fan, so the
version on the page and in the logbook identifies the build. After 1.0.0: PATCH fixes, MINOR features, MAJOR breaking.
Test builds (to try a fix with someone, before the release): the coming version plus -test.N, e.g. 1.0.1-test.1,
1.0.1-test.2, then 1.0.1. A dash counts as older than the plain number (semver), so the release replaces them; the
page marks them "test version". Signed with the same key; share them on the issue or as a GitHub pre-release.
"""
VERSION = "1.0.0"
BOARD = "v2.0-3.x"        # relay boards this firmware is made for (same relay pins); not read from the board
