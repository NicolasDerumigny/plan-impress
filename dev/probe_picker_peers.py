#!/usr/bin/env python3
"""Model rectangles next to the pixels the peers actually occupy.

    DISPLAY=:98 python3 dev/probe_picker_peers.py

The picker is judged by how it looks, and the two can disagree: a control's
rectangle is a *model* property, the peer is what is painted.  This opens the
chooser the way the settings dialog does and prints both, so "the buttons are not
flush with the grid" can be traced to whichever of the two is lying.

It then photographs the chooser and measures the *ink*: the window's peer will not
say where the window is (fact 76), so the dialog is found by the colour it paints and
the bright clusters of the selector row - the ``<``, the page indicator and the ``>`` -
are located in pixels.  The arrows centre their own glyphs, so the middle of their two
centres is where the middle of the indicator's ink belongs, and "the page number is
not centred between the arrows" becomes a number: 0 px means the layout and the eye
agree.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
from plan_impress import palettes, picker  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/peers")
INK = 170                          # a glyph is the light thing on this dark theme
UNIT_X, UNIT_Y = 2.53, 2.39        # px per dialog unit, fact 28
RECENT = 0x112233                  # the colour the probe's recent row starts with


def client_origin(image, colour):
    """Where the dialog's client area is, in screen pixels.

    The window's peer answers ``0,0`` whatever the window manager decided (fact 76),
    and the desktop here is the same grey as the dialog, so neither the peer nor a
    background-colour search finds the window.  The picker's own first square does:
    its colour is known, its peer's rectangle inside the client area is known, and
    the two together say where the client area begins.
    """
    import numpy
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
                         dtype=numpy.int16)
    arr = numpy.asarray(image).astype(numpy.int16)
    mask = numpy.abs(arr - wanted).max(axis=2) <= 12
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 4)
    columns = numpy.flatnonzero(mask.sum(axis=0) >= 2)
    if not len(rows) or not len(columns):
        return None
    return int(columns.min()), int(rows.min())


def clusters_in(image, origin, top_units, bottom_units, left_units, right_units):
    """The bright clusters of a strip of the dialog, as ``[(x0, x1)]`` in pixels."""
    import numpy
    x0, y0 = origin
    top = y0 + int(top_units * UNIT_Y) - 3
    bottom = y0 + int(bottom_units * UNIT_Y) + 3
    left = x0 + int(left_units * UNIT_X)
    right = x0 + int(right_units * UNIT_X)
    band = numpy.asarray(image)[top:bottom, left:right]
    if not band.size:
        return [], (top, bottom)
    bright = (band.astype(numpy.int16).max(axis=2) > INK)
    columns = numpy.flatnonzero(bright.sum(axis=0) > 0)
    out, start, previous = [], None, None
    for column in columns:
        if start is None:
            start = previous = column
        elif column > previous + 4:
            out.append((int(start + left), int(previous + left)))
            start = column
        previous = column
    if start is not None:
        out.append((int(start + left), int(previous + left)))
    return out, (top, bottom)


def main():
    names = palettes.load_palettes()
    p = picker.ColourPicker(lo.connect(), names, current=0x1F4E79,
                            title="Heading colour",
                            recent=[("#112233", 0x112233)])
    p.build()
    p.show()
    time.sleep(1.0)
    print("%-10s %-24s %s" % ("control", "model (units)", "peer (px)"))
    for name in ("palettes", "previous", "page", "next", "caption0", "caption1",
                 "cell0", "cell1", "cell10", "preview", "name", "hex", "ok",
                 "cancel"):
        model = p.model.getByName(name)
        try:
            model_rect = tuple(int(getattr(model, k)) for k in
                               ("PositionX", "PositionY", "Width", "Height"))
        except Exception as error:
            model_rect = str(error)
        try:
            rect = p.control(name).getPeer().getPosSize()
            peer_rect = (rect.X, rect.Y, rect.Width, rect.Height)
        except Exception as error:
            peer_rect = "%s: %s" % (type(error).__name__, error)
        print("%-10s %-24s %s" % (name, model_rect, peer_rect))
    try:
        print("window peer: %s" % (p.dialog.getPeer().getPosSize(),))
    except Exception as error:
        print("window peer: %s" % error)
    print("model: grid x %d..%d, dialog %dx%d units"
          % (picker._GRID_X, picker._GRID_X + picker._GRID_W, picker.DIALOG_WIDTH,
             p.model.Height))

    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    shot = os.path.join(SHOT, "peers.png")
    time.sleep(0.4)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (shot, code))
    from PIL import Image
    image = Image.open(shot).convert("RGB")
    rect = p.control("cell0").getPeer().getPosSize()
    corner = client_origin(image, RECENT)
    origin = None
    if corner:
        origin = (corner[0] - rect.X, corner[1] - rect.Y)
    print("client area begins at %s (found by the first recent square)" % (origin,))
    if origin:
        # the pager: everything right of the selector, in the selector's own row
        found, band = clusters_in(image, origin, picker._MARGIN,
                                  picker._MARGIN + picker._HEADER_H,
                                  picker._GRID_X + picker._COMBO_W + 1,
                                  picker.DIALOG_WIDTH)
        print("pager row y %d..%d, ink clusters: %s" % (band[0], band[1], found))
        if len(found) >= 3:
            left, middle, right = found[-3], found[-2], found[-1]
            between = ((left[0] + left[1]) / 2.0 + (right[0] + right[1]) / 2.0) / 2.0
            centre = (middle[0] + middle[1]) / 2.0
            print("ink: indicator centre %.1f, midway between the arrows %.1f -> "
                  "off centre by %+.1f px (a unit is %.2f px)"
                  % (centre, between, centre - between, UNIT_X))
    p.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
