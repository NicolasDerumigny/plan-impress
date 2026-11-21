#!/usr/bin/env python3
"""Does the palette selector actually have room for the name it shows?

    DISPLAY=:98 python3 dev/probe_selector_fit.py

``picker.selector_width()`` says how wide the dropdown has to be, and a number
worked out from a per-glyph estimate is exactly the kind of number that looks
reasonable and clips the words.  The office cannot be asked how wide its words are
(fact 46: no ``FontDescriptor`` on a peer, no text metrics anywhere), so this asks
the pixels, with the two renderings of the *same words* in the same window:

* a ``FixedText`` of the same font, wide enough that it cannot be cut - the
  reference for what the words look like when nothing is missing;
* a dropdown at the width :func:`picker.selector_width` asks for, one row per name.

The client area is anchored on a square painted a colour the theme never uses at a
known rectangle, because the window's peer answers ``0,0`` whatever the window
manager decided (fact 76).  In the dropdown's own box the arrow at its right is ink
too, so that zone is excluded; what is left is compared with the reference, and
fewer bright columns than the ``FixedText`` has means the name is being cut.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import numpy  # noqa: E402
import uno  # noqa: E402
from PIL import Image  # noqa: E402

from plan_impress import palettes, picker  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/fit")
ANCHOR = 0x7FFF00                   # no theme paints this: findable by colour
INK = 170
UNIT_X, UNIT_Y = 2.53, 2.39
ARROW_UNITS = 11                    # the dropdown's own arrow, at its right
X0, LABEL_W = 6, 80
LABEL_H = 9
ROW = LABEL_H + picker._HEADER_H + 6


def names():
    """The strings the selector has to be able to say, longest last."""
    found = [name for name, _colours in palettes.load_palettes()]
    for extra in (picker.RECENT_CAPTION, "In this presentation"):
        if extra not in found:
            found.append(extra)
    return sorted(set(found), key=len)


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


def ink_span(image, origin, top_units, bottom_units, left_units, right_units):
    """``(x0, x1)`` of the bright pixels of a strip, in screen pixels."""
    x0, y0 = origin
    band = numpy.asarray(image)[y0 + int(top_units * UNIT_Y) - 1:
                                y0 + int(bottom_units * UNIT_Y) + 1,
                                x0 + int(left_units * UNIT_X):
                                x0 + int(right_units * UNIT_X)]
    if not band.size:
        return None
    bright = band.astype(numpy.int16).max(axis=2) > INK
    columns = numpy.flatnonzero(bright.sum(axis=0) > 0)
    if not len(columns):
        return None
    left = x0 + int(left_units * UNIT_X)
    return int(columns[0] + left), int(columns[-1] + left)


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
    wanted = names()
    combo_w = picker.selector_width(wanted)
    forced = os.environ.get("PROBE_SELECTOR_W")
    if forced:
        combo_w = int(forced)
        print("PROBE_SELECTOR_W: every dropdown is %d units wide" % combo_w)
    add(model, "anchor", "FixedText", [
        ("Label", ""), ("PositionX", 2), ("PositionY", 2), ("Width", 4),
        ("Height", 3), ("BackgroundColor", ANCHOR)])
    for index, name in enumerate(wanted):
        top = 8 + index * ROW
        add(model, "t%d" % index, "FixedText", [
            ("Label", name), ("PositionX", X0), ("PositionY", top),
            ("Width", LABEL_W), ("Height", LABEL_H),
            ("FontHeight", picker.font_height())])
        add(model, "l%d" % index, "ListBox", [
            ("StringItemList", uno.Any("[]string", (name,))),
            # the selection has to travel with the model into insertByName, or the
            # box shows nothing at all and there is no ink to measure (fact 30)
            ("SelectedItems", uno.Any("[]short", (0,))),
            ("Dropdown", True), ("PositionX", X0), ("PositionY", top + LABEL_H),
            ("Width", combo_w), ("Height", picker._HEADER_H),
            ("FontHeight", picker.font_height())])
    # the window has to be wider than *both* strips: a strip that runs past its
    # right edge measures whatever window is behind on the desktop, which reads as
    # ink and invents a cut
    for property_name, value in (("Width", X0 + max(combo_w, LABEL_W) + 8),
                                 ("Height", 8 + len(wanted) * ROW),
                                 ("Title", "selector fit")):
        try:
            model.setPropertyValue(property_name, value)
        except Exception as error:
            print("dialog %s: %s" % (property_name, error.__class__.__name__))
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)

    shot = os.path.join(SHOT, "fit.png")
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (shot, code))
    image = Image.open(shot).convert("RGB")
    anchor = dialog.getControl("anchor").getPeer().getPosSize()
    origin = origin_of(image, anchor)
    print("client area begins at %s; the selector is given %d units = %d px"
          % (origin, combo_w, combo_w * UNIT_X))
    cut = []
    if origin:
        for index, name in enumerate(wanted):
            top = 8 + index * ROW
            reference = ink_span(image, origin, top, top + LABEL_H, X0, X0 + LABEL_W)
            box = ink_span(image, origin, top + LABEL_H,
                           top + LABEL_H + picker._HEADER_H, X0,
                           X0 + combo_w - ARROW_UNITS)
            if not reference or not box:
                print("%-24s reference %s, dropdown %s" % (name, reference, box))
                cut.append(name)
                continue
            words, shown = reference[1] - reference[0], box[1] - box[0]
            verdict = "CUT" if shown < words - 2 else "fits"
            if verdict == "CUT":
                cut.append(name)
            print("%-24s %2d chars  words %3d px  dropdown %3d px  %s"
                  % (name, len(name), words, shown, verdict))
    widest = max(len(name) for name in wanted)
    print("=> %d of %d names cut at %d units (%.2f units per glyph of the longest)"
          % (len(cut), len(wanted), combo_w, combo_w / float(widest)))
    if cut:
        print("   cut: %s" % ", ".join(cut))
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
