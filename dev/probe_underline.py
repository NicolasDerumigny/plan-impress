"""Why does the picker's read-out underline its first letter and its captions not?

The read-out is the one label in the chooser with an underline under its "C", and
there is no ``Mnemonic`` or ``Decorative`` property on a control model built from a
dialog model (``dev/probe_mnemonic.py`` prints the exceptions), so the only way to
find out what draws it is to put candidate labels next to each other in a dialog
that looks like the picker - buttons with a default one and an edit field - and
photograph the result.
"""
import os
import sys
import time

BASE = "/home/derumigny/Documents/plan-impress"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(BASE, "loprofile/user/planimpress"))

import dev.lo as lo  # noqa: E402

LABELS = ("Colour  #1F4E79", "Zebra  #1F4E79", "_Colour  #1F4E79")


def main():
    ctx = lo.connect()
    mgr = ctx.ServiceManager
    win = mgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = mgr.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    win.setModel(model)
    for index, text in enumerate(LABELS):
        control = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        for name, value in (("Label", text), ("PositionX", 4),
                            ("PositionY", 4 + 14 * index), ("Width", 70),
                            ("Height", 9), ("FontHeight", 12)):
            control.setPropertyValue(name, value)
        model.insertByName("label%d" % index, control)
    edit = model.createInstance("com.sun.star.awt.UnoControlEditModel")
    for name, value in (("Text", "1F4E79"), ("PositionX", 4), ("PositionY", 48),
                        ("Width", 26), ("Height", 14), ("FontHeight", 12)):
        edit.setPropertyValue(name, value)
    model.insertByName("hex", edit)
    for name, x, default in (("ok", 34, True), ("cancel", 62, False)):
        button = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        for prop, value in (("Label", name), ("PositionX", x), ("PositionY", 48),
                            ("Width", 26), ("Height", 14), ("FontHeight", 12),
                            ("DefaultButton", default)):
            button.setPropertyValue(prop, value)
        model.insertByName(name, button)
    model.setPropertyValue("Width", 92)
    model.setPropertyValue("Height", 68)
    toolkit = mgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    win.createPeer(toolkit, None)
    win.setVisible(True)
    time.sleep(2.5)
    os.spawnv(os.P_WAIT, "/usr/bin/scrot",
              ["/usr/bin/scrot", "-o", "/tmp/opencode/underline.png"])
    win.setVisible(False)
    win.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
