#!/usr/bin/env python3
"""How wide the palette selector has to be for the words it has to show.

    DISPLAY=:98 python3 dev/probe_picker_width.py

The report is that the chooser cuts "In this presentation" - the name
``palettes.deck_palette()`` gives the deck's own colours, and the first entry of
the list.  Nothing on a list box says how wide its words are (no ``FontDescriptor``
on a peer, fact 46, and no text metrics anywhere), so this measures the *same words*
in a `FixedText` of the same font: one candidate per row, photographed, and the
bright pixels of each row give the ink width in pixels.

The window's peer answers ``0,0`` whatever the window manager decided (fact 76), so
the client area is anchored on a small square painted a known colour at a known
rectangle: its peer says where it is inside the window and the screenshot says where
it is on the screen.

Prints, per name: the ink in pixels, that in dialog units (2.53 px, fact 28), and
the units per glyph - which is what ``picker._LIST_CHAR_W`` is.  Also prints what
the selector is currently given, so a too-narrow box is visible as a number.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import numpy  # noqa: E402
from PIL import Image  # noqa: E402

from plan_impress import palettes, picker  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/width")
ANCHOR = 0x1F4E79                  # far from the theme's greys: findable by colour
INK = 170
UNIT_X, UNIT_Y = 2.53, 2.39
X0, LABEL_W = 24, 90               # dialog units
LABEL_H, STEP = 9, 16


def candidates():
    """The strings the selector has to be able to say, longest last."""
    names = [name for name, _colours in palettes.load_palettes()]
    for extra in (picker.RECENT_CAPTION, "In this presentation"):
        if extra not in names:
            names.append(extra)
    return sorted(set(names), key=len)


def add(model, name, service, props):
    control = model.createInstance("com.sun.star.awt.UnoControl%sModel" % service)
    for property_name, value in props:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("%s.%s: %s" % (name, property_name, error.__class__.__name__))
    model.insertByName(name, control)


def origin_of(image, peer_rect):
    """Where the window's client area is, found through the anchor square."""
    wanted = numpy.array([(ANCHOR >> 16) & 255, (ANCHOR >> 8) & 255, ANCHOR & 255],
                         dtype=numpy.int16)
    arr = numpy.asarray(image).astype(numpy.int16)
    mask = numpy.abs(arr - wanted).max(axis=2) <= 12
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 2)
    columns = numpy.flatnonzero(mask.sum(axis=0) >= 2)
    if not len(rows) or not len(columns):
        return None
    return int(columns.min() - peer_rect.X), int(rows.min() - peer_rect.Y)


def ink_row(image, origin, top_units, bottom_units, left_units, right_units):
    """The ``(x0, x1)`` of the bright pixels of a strip, in screen pixels."""
    x0, y0 = origin
    band = numpy.asarray(image)[y0 + int(top_units * UNIT_Y) - 2:
                                y0 + int(bottom_units * UNIT_Y) + 2,
                                x0 + int(left_units * UNIT_X):
                                x0 + int(right_units * UNIT_X)]
    if not band.size:
        return None
    bright = band.astype(numpy.int16).max(axis=2) > INK
    columns = numpy.flatnonzero(bright.sum(axis=0) > 0)
    if not len(columns):
        return None
    return int(columns[0] + x0 + int(left_units * UNIT_X)), \
        int(columns[-1] + x0 + int(left_units * UNIT_X))


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ctx = lo.connect()
    manager = ctx.ServiceManager
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog",
                                               ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)
    names = candidates()
    add(model, "anchor", "FixedText", [
        ("Label", ""), ("PositionX", 4), ("PositionY", 2), ("Width", 4),
        ("Height", 3), ("BackgroundColor", ANCHOR)])
    for index, name in enumerate(names):
        add(model, "t%d" % index, "FixedText", [
            ("Label", name), ("PositionX", X0), ("PositionY", 6 + index * STEP),
            ("Width", LABEL_W), ("Height", LABEL_H),
            ("FontHeight", picker.font_height())])
        add(model, "l%d" % index, "ListBox", [
            ("StringItemList", (name,)), ("Dropdown", True),
            ("PositionX", X0 + LABEL_W + 4), ("PositionY", 4 + index * STEP),
            ("Width", picker._COMBO_W), ("Height", picker._HEADER_H),
            ("FontHeight", picker.font_height())])
    height = 8 + len(names) * STEP
    for property_name, value in (("Width", X0 + 2 * LABEL_W + 20), ("Height", height),
                                 ("Title", "selector width")):
        try:
            model.setPropertyValue(property_name, value)
        except Exception as error:
            print("dialog %s: %s" % (property_name, error.__class__.__name__))
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)

    shot = os.path.join(SHOT, "width.png")
    time.sleep(0.4)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (shot, code))
    image = Image.open(shot).convert("RGB")
    anchor = dialog.getControl("anchor").getPeer().getPosSize()
    origin = origin_of(image, anchor)
    print("client area begins at %s" % (origin,))
    if not origin:
        dialog.dispose()
        return 1

    widest = 0.0
    for index, name in enumerate(names):
        row = ink_row(image, origin, 6 + index * STEP, 6 + index * STEP + LABEL_H,
                      X0, X0 + LABEL_W)
        if not row:
            print("%-28s no ink" % name)
            continue
        px = row[1] - row[0] + 1
        units = px / UNIT_X
        per_glyph = units / max(1, len(name))
        widest = max(widest, per_glyph)
        print("%-28s %2d chars  ink %3d px = %5.1f units  %.2f units/glyph"
              % (name, len(name), px, units, per_glyph))
    need = picker._COMBO_W
    print("the selector is given %d units; the longest name needs %.1f units of "
          "words plus the arrow" % (need, widest * 20))
    print("=> picker._LIST_CHAR_W = %.2f  (widest measured %.2f)"
          % (widest, widest))
    for name in names[-3:]:
        print("   %-28s at that size: %.1f units" % (name, widest * len(name)))
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
