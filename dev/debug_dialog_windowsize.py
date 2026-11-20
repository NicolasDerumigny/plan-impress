"""How to give the settings dialog a window size that fits its controls.

    python3 dev/debug_dialog_units.py show 6    # for the control side of the story
    python3 dev/debug_dialog_windowsize.py       # here

Control models built by the dialog model's own ``createInstance`` keep their
geometry (see ``dev/debug_dialog_units.py``), but the dialog's own window stays
at the 300x450-unit default: ``dialog.setPosSize`` moves it without resizing it,
and the dialog model created from the service manager refuses ``Width``.

Variants, each printing the peer geometry it achieved:

  A  ``dialog.getPeer().setPosSize(...)``          - the peer is an XWindow too
  B  ``dialog.setPosSize`` after ``setVisible``
  C  properties on the dialog model (Width/Height/PositionX/PosSizeMapMode)
  D  parent window from a WindowDescriptor of the wanted size
  E  ``dialog.setPosSize`` with the SIZE flag before ``createPeer``
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
EDIT = "com.sun.star.awt.UnoControlEditModel"
BUTTON = "com.sun.star.awt.UnoControlButtonModel"
WANT = (40, 30, 140, 90)                      # x, y, width, height in units
POS_SIZE = 3                                  # com.sun.star.awt.PosSize POS | SIZE


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:80])


def new_dialog():
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    for name, service, own in (("e", EDIT, (("Text", "hello"),)),
                               ("b", BUTTON, (("Label", "OK"),))):
        child = model.createInstance(service)
        pairs = list(own) + [("PositionX", 10), ("PositionY", 10 if name == "e" else 40),
                             ("Width", 100), ("Height", 12)]
        uno.invoke(child, "setPropertyValues",
                   (tuple(n for n, _v in pairs), tuple(v for _n, v in pairs)))
        model.insertByName(name, child)
    return dialog, model


def report(label, dialog, extra=(), parent=None):
    try:
        size = dialog.getPosSize()
        text = "dialog %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y)
    except Exception as error:
        text = "dialog %s" % detail(error)
    try:
        peer = dialog.getPeer()
        psize = peer.getPosSize()
        text += " | peer %dx%d at %d,%d" % (psize.Width, psize.Height, psize.X, psize.Y)
    except Exception as error:
        text += " | peer %s" % detail(error)
    print("%-26s %s" % (label, text))
    for note in extra:
        print("      %s" % note)
    if parent is not None:
        try:
            g = parent.getPosSize()
            print("      parent %dx%d at %d,%d" % (g.Width, g.Height, g.X, g.Y))
        except Exception as error:
            print("      parent %s" % detail(error))


def toolkit():
    return MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)


def variant_a():
    dialog, _model = new_dialog()
    dialog.createPeer(toolkit(), None)
    notes = []
    try:
        dialog.getPeer().setPosSize(WANT[0], WANT[1], WANT[2], WANT[3], POS_SIZE)
    except Exception as error:
        notes.append("peer.setPosSize -> %s" % detail(error))
    report("A peer.setPosSize", dialog, notes)
    dialog.dispose()


def variant_b():
    dialog, _model = new_dialog()
    dialog.createPeer(toolkit(), None)
    notes = []
    try:
        dialog.setVisible(True)
    except Exception as error:
        notes.append("setVisible -> %s" % detail(error))
    try:
        dialog.setPosSize(WANT[0], WANT[1], WANT[2], WANT[3], POS_SIZE)
    except Exception as error:
        notes.append("setPosSize -> %s" % detail(error))
    try:
        dialog.getPeer().setPosSize(WANT[0], WANT[1], WANT[2], WANT[3], POS_SIZE)
    except Exception as error:
        notes.append("peer.setPosSize -> %s" % detail(error))
    report("B after setVisible", dialog, notes)
    if len(sys.argv) > 1:
        dialog.setTitle("B: peer.setPosSize after setVisible")
    else:
        dialog.dispose()


def variant_c():
    dialog, model = new_dialog()
    notes = []
    for name, value in (("Width", WANT[2]), ("Height", WANT[3]),
                        ("PositionX", WANT[0]), ("PositionY", WANT[1]),
                        ("PosSizeMapMode", 0), ("TileLeftToRight", True)):
        try:
            model.setPropertyValue(name, value)
            notes.append("%s=%s accepted" % (name, value))
        except Exception as error:
            notes.append("%s -> %s" % (name, detail(error)))
    dialog.createPeer(toolkit(), None)
    report("C dialog model props", dialog, notes)
    dialog.dispose()


def variant_d():
    dialog, _model = new_dialog()
    notes = []
    parent = None
    descriptor = uno.createUnoStruct("com.sun.star.awt.WindowDescriptor")
    notes.append("descriptor fields with x/y/width/height/map: %s"
                 % [f for f in dir(descriptor)
                    if f in ("X", "Y", "Width", "Height", "PosSize", "Style", "Type",
                             "Parent", "MapMode", "Rect")])
    descriptor.Type = 0                     # com.sun.star.awt.WindowType.TOP
    descriptor.Style = 0x04                 # com.sun.star.awt.WindowAttribute.CLOSE
    descriptor.X, descriptor.Y, descriptor.Width, descriptor.Height = WANT
    try:
        parent = toolkit().createWindow(descriptor)
        parent.setVisible(True)
    except Exception as error:
        notes.append("createWindow -> %s" % detail(error))
    try:
        dialog.createPeer(toolkit(), parent)
    except Exception as error:
        notes.append("createPeer(parent) -> %s" % detail(error))
    report("D sized parent window", dialog, notes, parent)
    dialog.dispose()
    if parent is not None:
        try:
            parent.dispose()
        except Exception:
            pass


def variant_e():
    dialog, _model = new_dialog()
    notes = []
    try:
        dialog.setPosSize(WANT[0], WANT[1], WANT[2], WANT[3], POS_SIZE)
    except Exception as error:
        notes.append("setPosSize before createPeer -> %s" % detail(error))
    dialog.createPeer(toolkit(), None)
    report("E setPosSize before peer", dialog, notes)
    dialog.dispose()


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    for variant in (variant_a, variant_b, variant_c, variant_d, variant_e):
        variant()
    if seconds:
        print("staying alive %g s so the windows can be screenshotted" % seconds)
        time.sleep(seconds)


if __name__ == "__main__":
    main()
