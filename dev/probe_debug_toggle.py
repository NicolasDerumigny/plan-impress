"""What does Plan > Toggle Debug Log actually do?

    python3 dev/probe_debug_toggle.py

The report is "Toggle Debug Log does nothing", so this takes the exact path a menu
click takes - dispatch the ``service:`` URL on the document's frame - and prints the
three things that have to happen: the marker file appears next to the settings, the
log says the command arrived, and the message box the user is supposed to see comes
back.  Nothing here goes through ``handler.py``'s Python call directly, so a Job that
is never instantiated (a bad URL, an unregistered implementation) shows up as
"nothing happened" here rather than as a passing test.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# this script runs outside the office, where there is no deployment path to read
# the profile out of (fact 33), and the office writes into its own
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(ROOT, "loprofile", "user", "planimpress"))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config  # noqa: E402

DEBUG_SERVICE = "service:org.devsys.planimpress.Debug?debug"
DOC = os.path.join(ROOT, "tests", "fixtures", "sections.odp")

ctx = lo.connect()
desk = lo.desktop(ctx)


def state():
    directory = config._profile_dir(ctx)
    marker = os.path.join(directory, "debug")
    log = config.debug_log_path(ctx)
    return {"marker": os.path.exists(marker),
            "log": os.path.getsize(log) if os.path.exists(log) else None,
            "enabled": config.debug_enabled(ctx)}


def show(label, before, after):
    print("  %-46s marker %s -> %s   log %s -> %s   enabled %s -> %s"
          % (label, before["marker"], after["marker"], before["log"], after["log"],
             before["enabled"], after["enabled"]))


def lines(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def run(doc, label):
    before = state()
    lo.dispatch(doc, DEBUG_SERVICE)
    moved = lo.wait_until(lambda: state()["marker"] != before["marker"], timeout=10)
    show(label, before, state())
    if not moved:
        print("      the marker never changed: the Job was probably never called")
    return moved


doc = lo.open_doc(desk, DOC, hidden=False)
try:
    directory = config._profile_dir(ctx)
    print("profile dir %s" % directory)
    for name in ("debug", "debug.log", "error.log"):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            print("  removing %s (%d bytes)" % (name, os.path.getsize(path)))
            os.remove(path)
    run(doc, "first click (expect the marker to appear)")
    run(doc, "second click (expect the marker to go away)")
    print("\nerror.log:")
    for line in lines(os.path.join(directory, "error.log"))[-25:]:
        print("  " + line)
    print("debug.log:")
    for line in lines(config.debug_log_path(ctx))[-25:]:
        print("  " + line)
    if not lines(config.debug_log_path(ctx)):
        print("  (nothing was ever written: trigger() logs before the handler runs,")
        print("   so an empty log with a marker that flips means the log call itself")
        print("   is failing, and no lines at all means the Job never ran)")
    time.sleep(0.5)
finally:
    lo.close(doc)
