#!/usr/bin/env python3
"""Can a palette grid be hand-built: does a panel paint, and does it see clicks?

    DISPLAY=:98 python3 dev/probe_paint.py [seconds]

A palette picker needs two things the settings dialog does not use yet: a
surface to draw colour cells on, and the position of the click inside it.  This
puts one panel in a dialog, paints a grid of coloured rectangles in its paint
handler, and reports what the mouse listener receives.  If either half fails the
picker has to be built out of buttons instead, so this is checked first.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402
import unohelper  # noqa: E402
from com.sun.star.awt import XMouseListener, XPaintListener  # noqa: E402
from com.sun.star.beans import PropertyValue  # noqa: E402

COLOURS = [0xC0504D, 0x9BBB59, 0x4F81BD, 0x8064A2, 0x4BACC6, 0xF79646,
           0x000000, 0x808080, 0xC0C0C0, 0xFFFFFF, 0x1F6EC8, 0x22AA44]
CELL, COLUMNS = 28, 6


def prop(name, value):
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    context = lo.connect()
    toolkit = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", context)
    parent = None
    try:
        frame = lo.desktop(context).getCurrentFrame()
        parent = frame.getContainerWindow()
    except Exception:
        pass
    if parent is None:
        frame = lo.desktop(context).loadComponentFromURL(
            "private:factory/simpress", "_blank", 0, (prop("Hidden", True),))
        parent = frame.getContainerWindow()

    dialog_model = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", context)
    for name, value in (("Width", 240), ("Height", 160), ("Title", "paint probe")):
        try:
            dialog_model.setPropertyValue(name, value)
        except Exception as error:
            print("model %s: %s" % (name, error.__class__.__name__))
    # no UnoControlPanelModel can be created from the dialog model (it answers
    # None), so the grid surface is an image control with no image on it
    panel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
    for name, value in (("PositionX", 8), ("PositionY", 8),
                        ("Width", 6 * CELL + 4), ("Height", 2 * CELL + 4),
                        ("Border", 2), ("BackgroundColor", 0xFFFFFF)):
        try:
            panel_model.setPropertyValue(name, value)
        except Exception as error:
            print("panel %s: %s" % (name, error.__class__.__name__))
    dialog_model.insertByName("grid", panel_model)

    dialog = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialog", context)
    dialog.setModel(dialog_model)
    # UnoControlDialog has no createActionControls(); the peers come into
    # existence with createPeer, the way src/plan_impress/dialog.py does it.
    dialog.createPeer(toolkit, None)
    control = dialog.getControl("grid")

    painted, clicks = [], []

    class Painter(unohelper.Base, XPaintListener):
        def paint(self, event):
            try:
                window = event.Source
                page = window.getDrawPage()
                rows = (len(COLOURS) + COLUMNS - 1) // COLUMNS
                for index, colour in enumerate(COLOURS):
                    x = 2 + (index % COLUMNS) * CELL
                    y = 2 + (index // COLUMNS) * CELL
                    page.setFillColor(colour)
                    page.setLineColor(0x404040)
                    page.drawRectangle(uno.Struct("com.sun.star.awt.Rectangle",
                                                  {"X": x, "Y": y,
                                                   "Width": x + CELL,
                                                   "Height": y + CELL}))
                painted.append((len(COLOURS), rows))
            except Exception as error:
                painted.append("paint failed: %s %s" % (error.__class__.__name__, error))

        def disposing(self, event):
            pass

    class Mouse(unohelper.Base, XMouseListener):
        def mousePressed(self, event):
            clicks.append(("pressed", event.X, event.Y, event.Buttons))

        def mouseReleased(self, event):
            clicks.append(("released", event.X, event.Y, event.Buttons))

        def mouseEntered(self, event):
            clicks.append(("entered", event.X, event.Y))

        def mouseExited(self, event):
            clicks.append(("exited", event.X, event.Y))

        def mouseDragged(self, event):
            pass

        def mouseMoved(self, event):
            clicks.append(("moved", event.X, event.Y))

        def disposing(self, event):
            pass

    control.addMouseListener(Mouse())
    control.addPaintListener(Painter())
    dialog.setVisible(True)
    time.sleep(1.0)
    geometry = dialog.getPosSize()
    size = control.getPosSize()
    print("dialog %dx%d at %d,%d ; panel %dx%d"
          % (geometry.Width, geometry.Height, geometry.X, geometry.Y,
             size.Width, size.Height))
    # click the centre of the second cell of the second row
    target_x = geometry.X + size.X + 2 + 1 * CELL + CELL // 2
    target_y = geometry.Y + size.Y + 2 + 1 * CELL + CELL // 2
    for argv in (["mousemove", str(target_x), str(target_y)],
                 ["click", "1"]):
        subprocess.run(["xdotool"] + argv, check=False, timeout=10)
    time.sleep(1.0)
    print("painted: %s" % painted[:3])
    print("mouse events: %s" % clicks[:8])
    out = os.path.join(ROOT, "out", "probe-paint.png")
    subprocess.run(["scrot", "-o", out], check=True, timeout=30)
    print("wrote %s" % out)
    if seconds > 0:
        time.sleep(seconds)
    dialog.dispose()


if __name__ == "__main__":
    main()
