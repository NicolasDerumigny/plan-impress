"""Does a second top-level peer hang while the Plan menu popup is open?  (debug)

    DISPLAY=:98 python3 dev/probe_font_menu.py

``dev/probe_font_peer.py`` shows the five steps of
:func:`plan_impress.dialog.installed_fonts` answering in 0.1 s with a document open,
so the hang the settings dialog once showed before it appeared is not in those lines.
The one thing ``dev/measure_text.py`` did before building the dialog that nothing else
does is **open the Plan menu** with the pointer - a popup that holds the grab.  This
does exactly that and then asks, with a wall-clock time against each step and a hard
timeout on the whole thing: if the office dies or the last line never prints, that is
the answer, and it is why the font list is read from the dialog's own peer
(:meth:`plan_impress.dialog.SettingsDialog._fill_fonts`).
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

from plan_impress import dialog  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
MENU_CLICK = (422, 39)                     # "Plan" in the menu bar, as measure_text.py
START = time.time()


def say(*args):
    print("%6.1fs %s" % (time.time() - START,
                         " ".join("%s" % item for item in args)), flush=True)


def xdo(*args):
    subprocess.run(["xdotool"] + list(args), check=False, timeout=10)


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    say("document open:", doc.DrawPages.Count, "slides")
    xdo("search", "--name", "sections.odp", "windowmove", "0", "30")
    xdo("activate", "--name", "sections.odp")
    time.sleep(1.0)

    say("installed_fonts with no popup   :", len(dialog.installed_fonts(ctx)), "names")

    xdo("mousemove", str(MENU_CLICK[0]), str(MENU_CLICK[1]), "click", "1")
    say("clicked the Plan menu")
    time.sleep(1.0)
    # the office is the thing that may not come back, so say it before asking
    say("installed_fonts with the menu open...")
    names = dialog.installed_fonts(ctx)
    say("-> %d names" % len(names))

    xdo("key", "Escape")
    xdo("key", "Escape")
    xdo("mousemove", "700", "700", "click", "1")
    lo.close(doc)
    say("closed; the office survived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
