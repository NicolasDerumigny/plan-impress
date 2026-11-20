"""Does a FixedText underline its first character, and does Mnemonic=False stop it?

The picker's read-out came up with an underline under the "C" of "Colour", which
no property assertion can see.  This paints one label with the default
properties and one with ``Mnemonic`` off, 24 px apart, so the screenshot answers
both questions at once.
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

TEXT = "Colour  #1F4E79"


def main():
    ctx = lo.connect()
    mgr = ctx.ServiceManager
    win = mgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = mgr.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    win.setModel(model)
    for index, extra in enumerate(((), (("Mnemonic", False),))):
        control = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        props = [("Label", TEXT), ("PositionX", 4), ("PositionY", 4 + 14 * index),
                 ("Width", 70), ("Height", 9), ("FontHeight", 12)]
        props.extend(extra)
        for name, value in props:
            try:
                control.setPropertyValue(name, value)
            except Exception as error:
                print("%s: set %s -> %s" % (index, name, error))
        model.insertByName("label%d" % index, control)
    model.setPropertyValue("Width", 90)
    model.setPropertyValue("Height", 46)
    toolkit = mgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    win.createPeer(toolkit, None)
    win.setVisible(True)
    time.sleep(2.5)
    os.spawnv(os.P_WAIT, "/usr/bin/scrot",
              ["/usr/bin/scrot", "-o", "/tmp/opencode/mnemonic.png"])
    win.setVisible(False)
    win.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
