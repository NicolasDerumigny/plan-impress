"""The wizard way of building a dialog: ``dialogModel.createInstance(...)``.

    python3 dev/debug_dialog_wizard.py [show] [seconds]

``/usr/lib/libreoffice/program/wizards/ui/UnoDialog.py`` does this:

    xControlModel = self.xDialogModel.createInstance(serviceName)
    uno.invoke(xControlModel, "setPropertyValues", (names, values))
    self.xDialogModel.insertByName(name, xControlModel)

i.e. the control model comes from the **dialog model's own factory**, not from
the service manager.  That is the one route not tried yet, and it is the one
LibreOffice's own Python wizards use, so their dialogs do lay out.  This script
checks whether such a model accepts ``PositionX``/``Width`` and whether the
numbers reach the screen.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
GEOMETRY = (("PositionX", 120), ("PositionY", 40), ("Width", 260), ("Height", 34))
WIDGETS = (
    ("lbl", "com.sun.star.awt.UnoControlFixedTextModel", (("Label", "Muted colour:"),)),
    ("txt", "com.sun.star.awt.UnoControlEditModel", (("Text", "B0B0B0"),)),
    ("btn", "com.sun.star.awt.UnoControlButtonModel", (("Label", "OK"),)),
)


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:80])


def main():
    show = len(sys.argv) > 2 and sys.argv[1] == "show"
    seconds = float(sys.argv[2]) if show else 0.0

    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    print("dialog model has createInstance: %s" % hasattr(model, "createInstance"))

    for name, service, own in WIDGETS:
        try:
            child = model.createInstance(service)
        except Exception as error:
            print("%-4s createInstance -> %s" % (name, detail(error)))
            continue
        names = [n for n, _v in GEOMETRY] + [n for n, _v in own]
        values = [v for _n, v in GEOMETRY] + [v for _n, v in own]
        try:
            uno.invoke(child, "setPropertyValues", (tuple(names), tuple(values)))
            print("%-4s setPropertyValues %s ok" % (name, names))
        except Exception as error:
            print("%-4s setPropertyValues -> %s" % (name, detail(error)))
        for prop_name, value in own:            # prove which ones really took
            try:
                child.getPropertyValue(prop_name)
            except Exception as error:
                print("     %s unreadable: %s" % (prop_name, detail(error)))
        for prop_name, _value in GEOMETRY:
            try:
                got = child.getPropertyValue(prop_name)
                print("     %-10s = %s" % (prop_name, got))
            except Exception as error:
                print("     %-10s -> %s" % (prop_name, detail(error)))
        try:
            model.insertByName(name, child)
        except Exception as error:
            print("%-4s insertByName -> %s" % (name, detail(error)))

    toolkit = MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)
    try:
        parent = toolkit.getDesktopWindow()
        print("parent = desktop window")
    except Exception as error:
        parent = None
        print("getDesktopWindow -> %s" % detail(error))
    try:
        dialog.createPeer(toolkit, parent)
    except Exception as error:
        print("createPeer -> %s" % detail(error))
        dialog.createPeer(toolkit, None)

    for prop_name in ("PosSizeMapMode", "TileLeftToRight", "TabstopFlow"):
        try:
            print("dialog model %-15s = %s" % (prop_name, model.getPropertyValue(prop_name)))
        except Exception as error:
            print("dialog model %-15s -> %s" % (prop_name, detail(error)))

    size = dialog.getPosSize()
    print("dialog peer: %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
    positions = []
    for name, _service, _own in WIDGETS:
        peer = dialog.getControl(name).getPosSize()
        positions.append((peer.X, peer.Y, peer.Width, peer.Height))
        print("%-4s peer %dx%d at %d,%d   (wanted 260x34 at 120,40)"
              % (name, peer.Width, peer.Height, peer.X, peer.Y))
    ok = all(p == (120, 40, 260, 34) for p in positions)
    print("POSITION AND SIZE: %s" % ("OK" if ok else "not as asked"))
    if show:
        dialog.setTitle("Plan Impress (wizard probe)")
        dialog.setVisible(True)
        print("visible for %g s" % seconds)
        time.sleep(seconds)
    dialog.dispose()


if __name__ == "__main__":
    main()
