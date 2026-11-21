#!/usr/bin/env python3
"""How do we put a thin ring of our own colour round a swatch?

    DISPLAY=:98 python3 dev/probe_swatch_ring.py

``Border`` cannot do it: ``dev/probe_border_colour.py`` sweeps every ``BorderStyle``
value on a label and paints ``#2B2E39`` - the theme's own line colour - whatever is
asked for, so a dark colour on a dark dialog has no edge at all.  The office's own
colour dropdown draws a thin **light** line there, so the line has to be ours.

Six candidates go into one window, each measured on the pixels *of its own control*:
how much of the crop is the colour, how much is the ring, whether the ring closes on
all four sides, and whether a click on it arrives.

``img-url`` / ``img-data``
    one ``UnoControlImageControlModel`` carrying a PNG written here with ``zlib`` and
    ``struct`` - as a file URL, and as ``ImageData`` bytes, because the second needs
    nothing written to disk inside a user's office.  ``dev/probe_swatch_bitmap.py``
    showed an image control paints what it is given and repaints when the bitmap
    changes after ``createPeer``.
``nest-a`` / ``nest-b`` / ``nest-tab``
    the ring as a label of its own with the colour label inset on top of it - in both
    insertion orders and with ``TabIndex`` set, because a forms container stacks its
    controls by tab order, so which of the two lands in front is exactly what has to
    be measured (only the one in front can be the click's source, fact 79).
``label``
    the current single label with ``Border``: the reference for what the theme's own
    ring looks like.

The pointer is driven through the window's real screen position - ``xdotool`` finds the
window by its title, because the dialog's own peer answers ``0,0`` (fact 76) - and the
shot is taken synchronously (fact 74).
"""
import os
import struct
import subprocess
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
import uno  # noqa: E402
from com.sun.star.awt import XMouseListener  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/ring")
TITLE = "plan-impress ring probe"
COLOUR = 0x1F4E79          # the swatch: nothing else in the window is this blue
RING = 0xFF0000            # the ring: red, so it cannot be mistaken for the theme
MARK = 0x3366CC            # a strip of known colour, to find the window in the shot
W, H = 11, 8               # a picker cell's size, in dialog units
STEP = 14
TOLERANCE = 22


def png_bytes(width, height, fill, ring=None):
    """The bytes of a ``width`` x ``height`` PNG, with zlib and struct only.

    LibreOffice's own Python has no imaging library, and the extension must not need
    one, so this is the recipe the picker would have to carry.
    """
    def row_bytes(y):
        row = bytearray()
        for x in range(width):
            inside = (ring is None
                      or (1 <= x < width - 1 and 1 <= y < height - 1))
            colour = fill if inside else ring
            row += bytes(((colour >> 16) & 255, (colour >> 8) & 255, colour & 255))
        return bytes(row)

    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + row_bytes(y) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def count(image, box, colour):
    """How many pixels of ``image`` inside ``box`` are within tolerance of ``colour``."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return 0, 0
    crop = numpy.asarray(image.crop((x0, y0, x1 + 1, y1 + 1))).astype(numpy.int16)
    wanted = numpy.array(
        [(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
        dtype=numpy.int16)
    mask = numpy.abs(crop - wanted).max(axis=2) <= TOLERANCE
    return int(mask.sum()), int(crop.shape[0] * crop.shape[1])


def sides(image, box, colour):
    """How much of each edge of ``box`` is ``colour``: does the ring close?"""
    x0, y0, x1, y1 = box
    wanted = numpy.array(
        [(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
        dtype=numpy.int16)

    def part(pixels):
        if not pixels:
            return "  -  "
        hits = sum(1 for p in pixels
                   if numpy.abs(numpy.array(p, dtype=numpy.int16)
                                - wanted).max() <= TOLERANCE)
        return "%3d/%-3d" % (hits, len(pixels))

    top = [image.getpixel((x, y0)) for x in range(x0, x1 + 1)]
    bottom = [image.getpixel((x, y1)) for x in range(x0, x1 + 1)]
    left = [image.getpixel((x0, y)) for y in range(y0, y1 + 1)]
    right = [image.getpixel((x1, y)) for y in range(y0, y1 + 1)]
    return "T%s B%s L%s R%s" % (part(top), part(bottom), part(left), part(right))


def window_origin(title):
    """Where the window manager put the window, from ``xdotool``."""
    try:
        found = subprocess.run(["xdotool", "search", "--name", title],
                               capture_output=True, text=True, timeout=10).stdout
        win = found.split()[0]
        shell = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win],
                               capture_output=True, text=True, timeout=10).stdout
        values = dict(line.split("=", 1) for line in shell.splitlines() if "=" in line)
        return int(values["X"]), int(values["Y"])
    except Exception as error:
        print("window_origin: %s" % error)
        return None


def shoot(name):
    shot = os.path.join(SHOT, name)
    time.sleep(0.5)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (name, code))
    return Image.open(shot).convert("RGB")


class Press(unohelper.Base, XMouseListener):
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def mousePressed(self, event):
        self.events.append((self.name, "pressed"))

    def mouseReleased(self, event):
        self.events.append((self.name, "released"))

    def mouseEntered(self, event):
        self.events.append((self.name, "entered"))

    def mouseExited(self, event):
        pass

    def disposing(self, event):
        pass


def set_properties(control, values, name):
    for property_name, value in values:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("   %s.%s: %s" % (name, property_name, error.__class__.__name__))


def label(model, name, x, y, width, height, colour, border=0):
    control = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    set_properties(control, (("Label", ""), ("BackgroundColor", colour),
                             ("PositionX", x), ("PositionY", y),
                             ("Width", width), ("Height", height),
                             ("Border", border)), name)
    model.insertByName(name, control)
    return control


def image_control(model, name, x, y, payload, url=None):
    control = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
    values = [("BackgroundColor", 0x808080), ("HelpText", "the colour name"),
              ("PositionX", x), ("PositionY", y),
              ("Width", W), ("Height", H), ("Border", 0)]
    if url is not None:
        values.insert(0, ("ImageURL", url))
    if payload is not None:
        values.insert(0, ("ImageData", tuple(payload[i] for i in range(len(payload)))))
    set_properties(control, values, name)
    model.insertByName(name, control)
    return control


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ringed = png_bytes(28, 19, COLOUR, RING)
    flat = png_bytes(28, 19, COLOUR)
    with open(os.path.join(SHOT, "ringed.png"), "wb") as handle:
        handle.write(ringed)
    with open(os.path.join(SHOT, "flat.png"), "wb") as handle:
        handle.write(flat)
    ringed_url = uno.systemPathToFileUrl(os.path.join(SHOT, "ringed.png"))
    flat_url = uno.systemPathToFileUrl(os.path.join(SHOT, "flat.png"))

    ctx = lo.connect()
    manager = ctx.ServiceManager
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)

    y = 8
    rows = []                       # (tag, control whose peer is measured and clicked)

    image_control(model, "img-url", 8, y, None, url=ringed_url)
    rows.append(("img-url", "img-url"))
    y += STEP
    image_control(model, "img-data", 8, y, ringed)
    rows.append(("img-data", "img-data"))
    y += STEP

    # the ring label and the colour label, in the three orders that could decide which
    # one the office paints in front
    label(model, "colour-a", 8, y, W, H, COLOUR)
    label(model, "ring-a", 7, y - 1, W + 2, H + 2, RING)
    rows.append(("nest-a", "colour-a"))
    y += STEP
    label(model, "ring-b", 7, y - 1, W + 2, H + 2, RING)
    label(model, "colour-b", 8, y, W, H, COLOUR)
    rows.append(("nest-b", "colour-b"))
    y += STEP
    ring = label(model, "ring-t", 7, y - 1, W + 2, H + 2, RING)
    colour = label(model, "colour-t", 8, y, W, H, COLOUR)
    for control, index in ((colour, 1), (ring, 2)):
        try:
            control.setPropertyValue("TabIndex", index)
        except Exception as error:
            print("   %s.TabIndex: %s" % (control.Name, error.__class__.__name__))
    rows.append(("nest-tab", "colour-t"))
    y += STEP
    label(model, "plain", 8, y, W, H, COLOUR, border=2)
    rows.append(("label", "plain"))
    y += STEP

    label(model, "mark", 4, 3, 100, 2, MARK)

    model.setPropertyValue("Width", 40)
    model.setPropertyValue("Height", y + 4)
    model.setPropertyValue("Title", TITLE)
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)

    events = []
    rects = {}
    for tag, clickable in rows:
        control = dialog.getControl(clickable)
        if control is None:
            print("%s: no control" % clickable)
            continue
        try:
            control.addMouseListener(Press(tag, events))
        except Exception as error:
            print("%s addMouseListener: %s" % (tag, error.__class__.__name__))
        peer = control.getPeer()
        rects[tag] = peer.getPosSize() if peer is not None else None

    time.sleep(1.2)
    image = shoot("ring.png")
    origin = window_origin(TITLE)
    print("window at %s" % (origin,))
    print("-- what each candidate paints, on the pixels of its own control")
    for tag, clickable in rows:
        rect = rects.get(tag)
        if origin is None or rect is None:
            print("   %-9s cannot be measured" % tag)
            continue
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        paint, total = count(image, box, COLOUR)
        ring, _ = count(image, box, RING)
        centre = image.getpixel(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
        print("   %-9s %3d px colour %3d px ring of %-4d  ring %s  centre #%02X%02X%02X"
              % (tag, paint, ring, total, sides(image, box, RING),
                 centre[0], centre[1], centre[2]))

    if origin:
        for tag, clickable in rows:
            control = dialog.getControl(clickable)
            if control is None or control.getPeer() is None:
                continue
            rect = control.getPeer().getPosSize()
            px, py = origin[0] + rect.X + rect.Width // 2, \
                origin[1] + rect.Y + rect.Height // 2
            for argv in (["mousemove", str(px), str(py)], ["click", "1"]):
                subprocess.run(["xdotool"] + argv, check=False, timeout=10)
            time.sleep(0.3)
    print("events: %s" % (events,))

    # a palette switch is the same bitmap asked for again in another colour: does a
    # control that is already on the screen take the new one?
    for name in ("img-url", "img-data"):
        control = model.getByName(name)
        if control is None:
            continue
        try:
            if name == "img-url":
                control.setPropertyValue("ImageURL", flat_url)
            else:
                control.setPropertyValue("ImageData",
                                         tuple(flat[i] for i in range(len(flat))))
        except Exception as error:
            print("%s runtime: %s" % (name, error.__class__.__name__))
        try:
            dialog.getControl(name).getPeer().invalidate(3)
        except Exception as error:
            print("%s invalidate: %s" % (name, error.__class__.__name__))
    for name in ("ring-a", "ring-b", "ring-t"):
        control = model.getByName(name)
        if control is not None:
            control.setPropertyValue("BackgroundColor", 0x00FF00)
    image = shoot("ring-changed.png")
    print("-- after the model was changed (a palette switch)")
    for tag, clickable in rows:
        rect = rects.get(tag)
        if origin is None or rect is None:
            continue
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        paint, total = count(image, box, COLOUR)
        ring, _ = count(image, box, RING)
        green, _ = count(image, box, 0x00FF00)
        print("   %-9s %3d px colour %3d px ring %3d px green of %-4d"
              % (tag, paint, ring, green, total))
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
