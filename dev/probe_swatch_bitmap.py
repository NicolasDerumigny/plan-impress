#!/usr/bin/env python3
"""Can a swatch be a small image we drew ourselves, ring and all?

    DISPLAY=:98 python3 dev/probe_swatch_bitmap.py

``Border`` cannot do it: every ``BorderStyle`` value on a label paints the ring in the
theme's own ``#2B2E39`` and ignores ``BorderColor`` entirely (``dev/probe_border_colour.py``
sweeps 0..6 - none of them is red).  The office's own colour dropdown nevertheless
shows a thin **light** line round each swatch on a dark theme, so the line has to be
something we paint.  The one control that paints pixels of its own is the image
control, so the question is whether it can do the four things a palette cell needs:

  * paint a bitmap at the cell's size (``ImageURL`` + ``ImagePosition``),
  * change to another bitmap **after** ``createPeer`` - a palette switch is exactly
    that, and fact 75 says a peer is not told when its model changes,
  * give its mouse events to a listener (fact 64: mouse works, paint does not),
  * carry ``HelpText``, so hovering says which colour the square is.

The bitmaps are written here with ``zlib`` and ``struct`` only: the extension has to
run inside LibreOffice's own Python, which has no PIL, so this is also a check that
the recipe needs nothing beyond the standard library.

Also prints what the office will say about the theme, which is what decides whether
the ring is light or dark: ``/org.openoffice.Office.Common/Appearance``.
"""
import os
import struct
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import unohelper  # noqa: E402
import numpy  # noqa: E402
from PIL import Image  # noqa: E402
from com.sun.star.awt import XMouseListener  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/bitmap")
BLUE, GREEN, RED = 0x1F4E79, 0x22AA44, 0xFF0000
W, H = 24, 14                      # dialog units
TOLERANCE = 12
#: ``com.sun.star.awt.ImagePosition``: 0 top-left, 4 SIZE (stretch to the control)
POSITIONS = (("TOPLEFT", 0), ("SIZE", 4))


def write_png(path, width, height, fill, ring=None, ring_width=1):
    """A PNG of exactly ``width`` x ``height``, no dependency beyond zlib.

    ``ring`` is the colour of the outer ``ring_width`` pixels; ``None`` paints a flat
    square, which is the control for "did the image paint at all".
    """
    def row_bytes(y):
        row = bytearray()
        for x in range(width):
            inside = (ring_width <= x < width - ring_width
                      and ring_width <= y < height - ring_width)
            colour = fill if (ring is None or inside) else ring
            row += bytes(((colour >> 16) & 255, (colour >> 8) & 255, colour & 255))
        return bytes(row)

    raw = b"".join(b"\x00" + row_bytes(y) for y in range(height))
    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return path


def blocks(image, colour, expected, label):
    """The ``(x0, y0, x1, y1)`` of each block painted ``colour``, top to bottom."""
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
                         dtype=numpy.int16)
    arr = numpy.asarray(image).astype(numpy.int16)
    mask = numpy.abs(arr - wanted).max(axis=2) <= TOLERANCE
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 4)
    out = []
    if len(rows):
        groups, start, previous = [], rows[0], rows[0]
        for row in rows[1:]:
            if row > previous + 2:
                groups.append((start, previous))
                start = row
            previous = row
        groups.append((start, previous))
        for top, bottom in groups:
            columns = numpy.flatnonzero(mask[top:bottom + 1].sum(axis=0) >= 2)
            out.append((int(columns.min()), int(top), int(columns.max()),
                        int(bottom)))
    print("   %-22s %d block(s) of #%06X, expected %d: %s"
          % (label, len(out), colour, expected, out))
    return out


def ring_pixels(image, block, wanted):
    """How much of the ring round a block is ``wanted``: the yes/no of the border."""
    x0, y0, x1, y1 = block
    target = numpy.array([(wanted >> 16) & 255, (wanted >> 8) & 255, wanted & 255],
                         dtype=numpy.int16)
    count = total = 0
    for x, y in ([(x, y0 - 1) for x in range(x0 - 1, x1 + 2)]
                 + [(x, y1 + 1) for x in range(x0 - 1, x1 + 2)]
                 + [(x0 - 1, y) for y in range(y0, y1 + 1)]
                 + [(x1 + 1, y) for y in range(y0, y1 + 1)]):
        try:
            pixel = numpy.array(image.getpixel((x, y)), dtype=numpy.int16)
        except Exception:
            continue
        total += 1
        if numpy.abs(pixel - target).max() <= 30:
            count += 1
    return "%d/%d" % (count, total)


def appearance(ctx):
    """What the office says about its own theme: the light-or-dark question."""
    from com.sun.star.beans import PropertyValue
    try:
        provider = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", ctx)
    except Exception as error:
        print("appearance: ConfigurationProvider %s" % error)
        return
    argument = PropertyValue()
    argument.Name = "ReadOnly"
    argument.Value = True
    for node in ("/org.openoffice.Office.Common/Appearance",
                 "/org.openoffice.Office.Common/Accessibility"):
        try:
            argument.Name = "Nodepath"
            argument.Value = node
            view = provider.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationAccess", (argument,))
            names = list(view.ElementNames)
        except Exception as error:
            print("%s: %s" % (node, error.__class__.__name__))
            continue
        print("%s:" % node)
        for name in names:
            try:
                print("   %-28s %r" % (name, view.getByName(name)))
            except Exception as error:
                print("   %-28s %s" % (name, error.__class__.__name__))


def shoot(name):
    shot = os.path.join(SHOT, name)
    time.sleep(0.5)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (name, code))
    return Image.open(shot).convert("RGB")


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ctx = lo.connect()
    manager = ctx.ServiceManager
    pictures = {}
    for tag, fill, ring in (("flat", BLUE, None), ("ringed", BLUE, RED),
                            ("other", GREEN, RED)):
        pictures[tag] = write_png(os.path.join(SHOT, "swatch-%s.png" % tag),
                                  23, 17, fill, ring)

    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)
    rows = []
    for position_name, position in POSITIONS:
        for tag in ("flat", "ringed"):
            name = "img-%s-%s" % (tag, position_name)
            control = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
            for property_name, value in (("ImageURL",
                                          uno_url(pictures[tag])),
                                         ("ImagePosition", position),
                                         ("BackgroundColor", 0x808080),
                                         ("PositionX", 8), ("PositionY", 8
                                                            + len(rows) * 20),
                                         ("Width", W), ("Height", H),
                                         ("Border", 0),
                                         ("HelpText", "the colour name")):
                try:
                    control.setPropertyValue(property_name, value)
                except Exception as error:
                    print("%s.%s: %s" % (name, property_name,
                                         error.__class__.__name__))
            model.insertByName(name, control)
            rows.append((name, tag, position_name))
    model.setPropertyValue("Width", 60)
    model.setPropertyValue("Height", 8 + len(rows) * 20 + 8)
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)

    events = []

    class Press(unohelper.Base, XMouseListener):
        def __init__(self, name):
            self.name = name

        def mousePressed(self, event):
            events.append((self.name, "pressed"))

        def mouseReleased(self, event):
            events.append((self.name, "released"))

        def mouseEntered(self, event):
            events.append((self.name, "entered"))

        def mouseExited(self, event):
            pass

        def disposing(self, event):
            pass

    for name, _tag, _position in rows:
        control = dialog.getControl(name)
        print("%-20s control=%s peer=%s"
              % (name, control is not None,
                 control is not None and control.getPeer() is not None))
        if control is not None:
            listener = Press(name)
            try:
                control.addMouseListener(listener)
            except Exception as error:
                print("%s addMouseListener: %s" % (name, error.__class__.__name__))
            for property_name in ("HelpText", "ImageURL", "ImagePosition",
                                  "BackgroundColor", "Border"):
                print("      has %-16s %s" % (property_name, hasattr(control, "get"
                                                                      + property_name)))
    time.sleep(1.0)
    image = shoot("bitmap-before.png")
    print("-- as built")
    blocks(image, BLUE, len(rows), "the image's fill")
    ringed = blocks(image, RED, 2, "the drawn ring")
    for block in ringed:
        print("   ring round %s is red: %s" % (block, ring_pixels(image, block, RED)))

    # the palette switch: another bitmap, after the peer exists
    for name, _tag, _position in rows:
        try:
            model.getByName(name).setPropertyValue("ImageURL",
                                                   uno_url(pictures["other"]))
        except Exception as error:
            print("%s ImageURL: %s" % (name, error.__class__.__name__))
    for name, _tag, _position in rows:
        try:
            dialog.getControl(name).getPeer().invalidate(3)
        except Exception as error:
            print("%s invalidate: %s" % (name, error.__class__.__name__))
    print("-- after the bitmap was changed (a palette switch)")
    image = shoot("bitmap-after.png")
    blocks(image, GREEN, len(rows), "the new image's fill")
    blocks(image, BLUE, 0, "the old image's fill")

    # and does it answer the mouse: a colour one cannot pick is not a cell
    import subprocess
    for name, _tag, _position in rows:
        try:
            rect = dialog.getControl(name).getPeer().getPosSize()
        except Exception:
            continue
        for argv in (["mousemove", str(rect.X + rect.Width // 2),
                      str(rect.Y + rect.Height // 2)], ["click", "1"]):
            subprocess.run(["xdotool"] + argv, check=False, timeout=10)
        time.sleep(0.25)
    print("events: %s" % (events,))
    appearance(ctx)
    dialog.dispose()
    return 0


def uno_url(path):
    import uno
    return uno.systemPathToFileUrl(path)


if __name__ == "__main__":
    sys.exit(main())
