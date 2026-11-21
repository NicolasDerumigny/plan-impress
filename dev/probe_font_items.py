"""Can the font dropdown be filled in *after* the dialog has a peer?  (debug)

    DISPLAY=:98 python3 dev/probe_font_items.py

``installed_fonts`` needs a window peer to ask, and creating a **second** top-level
peer halfway through building the settings dialog hung the client once a menu popup
had been on screen.  The alternative is to fill the combo from the dialog's own
peer, after ``createPeer`` - which fact 70 says works for words and colours but not
for geometry.  This builds the dialog with an empty combo, attaches a peer, writes
``StringItemList`` to the control model and prints what the *control* then answers,
which is what the user would see in the dropdown.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402

from plan_impress import config, dialog  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
NAMES = ("Liberation Sans", "Liberation Serif", "DejaVu Sans")


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    window = dialog.SettingsDialog(ctx, dict(config.DEFAULTS), ["Master 1"],
                                   fonts=[])          # as if the office said nothing
    window.build()
    try:
        window._peer()
        window.dialog.setVisible(True)
        time.sleep(0.5)
        control = window.control("SectionFont")
        print("before            : itemCount=%s text=%r"
              % (control.getItemCount(), control.getText()))
        model = window.control_model("SectionFont")
        model.setPropertyValue("StringItemList",
                               uno.Any("[]string", NAMES))
        window._repaint("SectionFont")
        time.sleep(0.5)
        print("after  model write: itemCount=%s text=%r"
              % (control.getItemCount(), control.getText()))
        try:
            print("  items            :", [control.getItem(i)
                                           for i in range(control.getItemCount())])
        except Exception as error:
            print("  items            : %s: %s" % (type(error).__name__, error))
        print("  the typed value survived:", repr(control.getText()))
        # and the result the dialog would save, which is the only thing that matters
        print("  result()          : section_font=%r" % window.result()["section_font"])
    finally:
        window.dispose()
        lo.close(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
