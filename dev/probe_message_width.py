#!/usr/bin/env python3
"""How many characters of a log path fit on one line of a message box.

"The *debug log enable/disable* window message has not enough width, the message is
cut (incomplete path)."  ``dialog.box_lines`` wraps at ``_BOX_CHARS`` characters and
each line is a ``FixedText`` ``_BOX_TEXT_W`` units wide - and a ``FixedText`` wraps
nothing and aligns nothing (fact 72), so a line that is one character too long is
simply painted past the edge of its box and the tail of the path never appears.

Nothing on the label says how wide its words are (fact 46), so the lines are painted
for real and photographed: each candidate is one label of ``n`` characters of a path
like the one the debug box prints, in the box's own font, in the box's own label
width; a reference label of the same text in a box four times as wide shows what the
whole line would measure.  The answer is the largest ``n`` whose ink still fits.

    DISPLAY=:98 python3 dev/probe_message_width.py
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

from plan_impress import dialog  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/message")
ANCHOR = 0x7FFF00
DIALOG_GREY = 0x383C4A
INK = 170
UNIT_X = 2.53
#: A path of the kind the debug box prints, and the only kind that matters here: no
#: spaces, so ``box_lines`` breaks it by length and never at a nicer place.
PATH = ("/home/derumigny/.config/libreoffice/4/user/planimpress/debug.log")


def add(model, name, service, props):
    control = model.createInstance(service)
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


def ink(image, origin, rect):
    """``(x0, x1)`` of the bright pixels inside a peer rectangle, screen pixels."""
    x0, y0 = origin
    band = numpy.asarray(image)[y0 + rect[1]: y0 + rect[1] + rect[3],
                                x0 + rect[0]: x0 + rect[0] + rect[2]]
    if not band.size:
        return None
    bright = band.astype(numpy.int16).max(axis=2) > INK
    columns = numpy.flatnonzero(bright.sum(axis=0) > 0)
    if not len(columns):
        return None
    return int(columns[0] + x0 + rect[0]), int(columns[-1] + x0 + rect[0])


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ctx = lo.connect()
    manager = ctx.ServiceManager
    box = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    box.setModel(model)

    widths = (30, 32, 34, 36, 38, 40, len(PATH))
    add(model, "anchor", "com.sun.star.awt.UnoControlFixedTextModel", [
        ("Label", ""), ("PositionX", 2), ("PositionY", 2), ("Width", 4),
        ("Height", 3), ("BackgroundColor", ANCHOR)])
    rows = {}
    for index, count in enumerate(widths):
        line = PATH[:count]
        y = 10 + index * 14
        add(model, "n%d" % index, "com.sun.star.awt.UnoControlFixedTextModel", [
            ("Label", line), ("PositionX", 4), ("PositionY", y),
            ("Width", dialog._BOX_TEXT_W), ("Height", dialog._BOX_LINE_H),
            ("FontHeight", dialog._FONT)])
        add(model, "r%d" % index, "com.sun.star.awt.UnoControlFixedTextModel", [
            ("Label", line), ("PositionX", 4), ("PositionY", y + 7),
            ("Width", 3 * dialog._BOX_TEXT_W), ("Height", dialog._BOX_LINE_H),
            ("FontHeight", dialog._FONT)])
        rows[index] = (count, y)
    height = 12 + len(widths) * 14 + 10
    for property_name, value in (("Width", 4 * dialog._BOX_TEXT_W),
                                 ("Height", height),
                                 ("Title", "message width"),
                                 ("BackgroundColor", DIALOG_GREY)):
        try:
            model.setPropertyValue(property_name, value)
        except Exception as error:
            print("dialog %s: %s" % (property_name, error.__class__.__name__))
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    box.createPeer(toolkit, None)
    box.setVisible(True)
    time.sleep(1.2)

    shot = os.path.join(SHOT, "width.png")
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d   (label width %d units = %d px, font %s pt, window %d units)"
          % (shot, code, dialog._BOX_TEXT_W, dialog._BOX_TEXT_W * UNIT_X,
             dialog._FONT, 5 * dialog._BOX_TEXT_W))
    image = Image.open(shot).convert("RGB")
    origin = origin_of(image, box.getControl("anchor").getPeer().getPosSize())
    print("client area begins at %s" % (origin,))
    if not origin:
        box.dispose()
        return 1

    def peer(name):
        rect = box.getControl(name).getPeer().getPosSize()
        return (rect.X, rect.Y, rect.Width, rect.Height)

    whole = None
    for index in sorted(rows):
        reference = ink(image, origin, peer("r%d" % index))
        if reference:
            whole = reference[1] - reference[0] + 1
            break
    print("the whole path is %s px of ink in a box nothing can cut" % whole)
    for index in sorted(rows):
        count, _y = rows[index]
        line = ink(image, origin, peer("n%d" % index))
        reference = ink(image, origin, peer("r%d" % index))
        if not line or not reference:
            print("%3d characters: nothing painted" % count)
            continue
        painted = line[1] - line[0] + 1
        wanted = reference[1] - reference[0] + 1
        print("%3d characters: %3d px of ink in the box, %3d px for the whole line "
              "-> %s" % (count, painted, wanted,
                         "whole" if painted >= wanted - 2 else "CUT"))
    print("_BOX_CHARS is %d and _BOX_TEXT_W is %d units"
          % (dialog._BOX_CHARS, dialog._BOX_TEXT_W))
    box.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
