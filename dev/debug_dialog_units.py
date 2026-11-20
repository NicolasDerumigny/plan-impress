"""Calibrate the settings dialog's control units against what reaches the screen.

    python3 dev/debug_dialog_units.py            # measure
    python3 dev/debug_dialog_units.py show 6     # also stay visible for a screenshot

Control models created by the *dialog model's* own ``createInstance`` keep
``PositionX``/``PositionY``/``Width``/``Height`` (that is what
``wizards/ui/UnoDialog.py`` does); models from the service manager do not, which
is why the settings dialog piled every control up at 0,0.  What the units of
those numbers are is what this measures: five controls are placed at known
"units" and both the peer geometry and the on-screen pixels are printed, so the
factor between the two is visible rather than assumed.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
EDIT = "com.sun.star.awt.UnoControlEditModel"
LABEL = "com.sun.star.awt.UnoControlFixedTextModel"
BUTTON = "com.sun.star.awt.UnoControlButtonModel"

# name, service, own properties, x, y, width, height  (dialog units)
GRID = (
    ("a", LABEL, (("Label", "unit 0,0"),), 0, 0, 100, 20),
    ("b", LABEL, (("Label", "x=100"),), 100, 0, 100, 20),
    ("c", LABEL, (("Label", "y=50"),), 0, 50, 100, 20),
    ("d", EDIT, (("Text", "wide"),), 0, 100, 200, 20),
    ("e", BUTTON, (("Label", "OK"),), 0, 150, 100, 30),
)
DIALOG_UNITS = (320, 200)


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:80])


def main():
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "show" else 0.0
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)

    for name, service, own, x, y, width, height in GRID:
        child = model.createInstance(service)
        pairs = list(own) + [("PositionX", x), ("PositionY", y),
                             ("Width", width), ("Height", height)]
        names = tuple(n for n, _v in pairs)
        values = tuple(v for _n, v in pairs)
        try:
            uno.invoke(child, "setPropertyValues", (names, values))
        except Exception as error:
            print("%-2s setPropertyValues -> %s" % (name, detail(error)))
        model.insertByName(name, child)

    toolkit = MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)
    dialog.createPeer(toolkit, None)
    dialog.setTitle("Plan Impress (unit calibration)")

    size = dialog.getPosSize()
    print("dialog asked %dx%d units -> peer %dx%d at %d,%d"
          % (DIALOG_UNITS[0], DIALOG_UNITS[1], size.Width, size.Height, size.X, size.Y))
    print("controls (asked in units, read back from the peer):")
    ratios = []
    for name, _service, _own, x, y, width, height in GRID:
        peer = dialog.getControl(name).getPosSize()
        ratios.append((peer.X / float(x) if x else 0, peer.Y / float(y) if y else 0,
                       peer.Width / float(width), peer.Height / float(height)))
        print("  %-2s %3d,%-3d %3dx%-3d  ->  %4d,%-4d %4dx%-4d   x/%d y/%d w/%.2f h/%.2f"
              % (name, x, y, width, height, peer.X, peer.Y, peer.Width, peer.Height,
                 peer.X / float(x) if x else 0, peer.Y / float(y) if y else 0,
                 peer.Width / float(width), peer.Height / float(height)))
    usable = [(r[2], r[3]) for r in ratios if r[2] and r[3]]
    if usable:
        print("mean size factor: x %.2f, y %.2f" % (
            sum(w for w, _h in usable) / len(usable),
            sum(h for _w, h in usable) / len(usable)))
    positions = set((dialog.getControl(n).getPosSize().X,
                     dialog.getControl(n).getPosSize().Y)
                    for n, _s, _o, _x, _y, _w, _h in GRID)
    print("distinct positions: %d of %d" % (len(positions), len(GRID)))

    if seconds:
        dialog.setVisible(True)
        print("visible for %g s (screenshot now)" % seconds)
        time.sleep(seconds)
    dialog.dispose()


if __name__ == "__main__":
    main()
