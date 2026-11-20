"""The settings dialog laid out the way LibreOffice's own wizards do it.

    python3 dev/debug_dialog_form.py            # measure
    python3 dev/debug_dialog_form.py show 8     # stay visible for a screenshot

The two halves of the recipe, both measured here:

* the **dialog model** accepts ``PositionX``/``PositionY``/``Width``/``Height``,
  which is what sizes the window (``Width=140, Height=90`` -> peer 354x214);
* **control models** must come from ``dialogModel.createInstance(service)``, not
  from the service manager - only then do they keep their own geometry.

Prints the peer geometry of every control plus the dialog, so "all controls in
the same place" cannot come back unnoticed, and reports which dialog-model
properties the modal buttons need.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import config, dialog  # noqa: E402

POS_SIZE = 3


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:80])


def main():
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "show" else 0.0
    ctx = lo.connect()
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x1F6EC8,
                     "title": "Plan", "master": "Master2"})
    window = dialog.SettingsDialog(ctx, settings, ["Master1", "Master2"])
    window.build()
    window._peer()
    window.dialog.setTitle("Plan Impress - Settings")

    for name, value in (("ButtonOK", 3), ("ButtonCancel", 4), ("Close", True)):
        try:
            window.model.setPropertyValue(name, value)
            print("dialog model %-12s = %s accepted" % (name, value))
        except Exception as error:
            print("dialog model %-12s -> %s" % (name, detail(error)))

    size = window.dialog.getPosSize()
    print("dialog peer: %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
    seen = {}
    rows = []
    for name, _service, _props in dialog._field_specs(window.values, window.masters):
        peer = window.control(name).getPosSize()
        rows.append((name, peer.X, peer.Y, peer.Width, peer.Height))
        seen.setdefault((peer.X, peer.Y), []).append(name)
        print("%-18s %4d,%-4d %4dx%-4d" % (name, peer.X, peer.Y, peer.Width, peer.Height))
    print("distinct positions: %d of %d  %s"
          % (len(seen), len(rows), "" if len(seen) == len(rows) else "OVERLAP: %s"
             % [v for v in seen.values() if len(v) > 1]))
    unsized = [name for name, _x, _y, w, h in rows if w <= 0 or h <= 0]
    print("controls with no size: %s" % (", ".join(unsized) or "none"))
    hidden = [name for name, x, y, w, h in rows
              if x + w > size.Width + 4 or y + h > size.Height + 4]
    print("controls outside the window: %s" % (", ".join(hidden) or "none"))

    if seconds:
        window.dialog.setVisible(True)
        print("visible for %g s (screenshot now)" % seconds)
        time.sleep(seconds)
    window.dispose()


if __name__ == "__main__":
    main()
