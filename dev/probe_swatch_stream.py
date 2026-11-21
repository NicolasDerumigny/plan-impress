#!/usr/bin/env python3
"""Which way will a GraphicProvider take PNG bytes without a file?

    DISPLAY=:98 python3 dev/probe_swatch_ring3.py

The picker needs a bitmap per colour, and a file for each of them inside a user's
office is the difference between a widget with a cache folder and one without.
``UnoControlImageControlModel`` has a ``Graphic`` property (a
``com.sun.star.graphic.XGraphic``), so ``GraphicProvider.queryGraphic`` is the door - but
it wants an ``XInputStream``, and pyuno will not marshal just any object into that
type: ``SequenceInputStream`` is refused ("no attribute getTypes") and a ``Pipe`` fed
with ``bytes`` is refused too ("VALUE is out of range", because ``sequence<octet>`` is
signed).  Four spellings are tried here, each one painted into its own control so the
answer is a picture rather than an exception:

``pipe-signed``  a ``com.sun.star.io.Pipe`` written with ``sequence<octet>`` in the
                 signed spelling pyuno wants.
``pipe-bytes``   the same with the raw ``bytes`` object.
``sequence``     a Python object implementing ``XInputStream`` itself, which is what
                 the SDK examples do when nothing else converts.
``file``         the file URL, the route already known to work, as the control.
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
from com.sun.star.io import XInputStream  # noqa: E402

TITLE = "plan-impress stream probe"
COLOUR = 0x1F4E79
RING = 0xFF0000
GREY = 0x808080
W, H = 11, 8
STEP = 14
TOLERANCE = 22


def png_bytes(width, height, fill, ring=None):
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


class BytesIn(unohelper.Base, XInputStream):
    """The smallest ``XInputStream`` that will answer a graphic loader."""

    def __init__(self, data):
        self.data = data
        self.position = 0

    def readBytes(self, count):
        chunk = self.data[self.position:self.position + count]
        self.position += len(chunk)
        return tuple(byte - 256 if byte > 127 else byte for byte in chunk)

    def readSomeBytes(self, count):
        return self.readBytes(count)

    def skipBytes(self, count):
        self.position = min(len(self.data), self.position + count)

    def available(self):
        return len(self.data) - self.position

    def reset(self):
        self.position = 0

    def dispose(self):
        pass


def graphic_from_bytes(ctx, payload, route):
    from com.sun.star.beans import PropertyValue
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", ctx)
    argument = PropertyValue()
    if route == "file":
        argument.Name = "URL"
        argument.Value = payload
    elif route == "sequence":
        argument.Name = "InputStream"
        argument.Value = BytesIn(payload)
    else:
        pipe = ctx.ServiceManager.createInstanceWithContext("com.sun.star.io.Pipe", ctx)
        data = payload if route == "pipe-bytes" else tuple(
            byte - 256 if byte > 127 else byte for byte in payload)
        pipe.writeBytes(data)
        pipe.closeOutput()
        argument.Name = "InputStream"
        argument.Value = pipe
    return provider.queryGraphic((argument,))


def count(image, box, colour):
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return 0
    crop = numpy.asarray(image.crop((x0, y0, x1 + 1, y1 + 1))).astype(numpy.int16)
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
                         dtype=numpy.int16)
    return int((numpy.abs(crop - wanted).max(axis=2) <= TOLERANCE).sum())


def window_origin(title):
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


def set_properties(control, values, name):
    for property_name, value in values:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("   %s.%s: %s" % (name, property_name, error.__class__.__name__))


def main():
    shot_dir = os.environ.get("PROBE_SHOT", "/tmp/opencode/ring4")
    if not os.path.isdir(shot_dir):
        os.makedirs(shot_dir)
    payload = png_bytes(28, 19, COLOUR, RING)
    path = os.path.join(shot_dir, "swatch.png")
    with open(path, "wb") as handle:
        handle.write(payload)

    ctx = lo.connect()
    manager = ctx.ServiceManager

    routes = ["file", "pipe-signed", "pipe-bytes", "sequence"]
    values = {}
    for route in routes:
        try:
            values[route] = graphic_from_bytes(
                ctx, uno.systemPathToFileUrl(path) if route == "file" else payload,
                route)
            print("%-12s -> %s" % (route, type(values[route]).__name__))
        except Exception as error:
            print("%-12s -> %s: %s" % (route, error.__class__.__name__,
                                       str(error).splitlines()[0][:90]))

    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)
    y = 8
    for route in routes:
        name = "c-" + route
        control = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
        if route == "file":
            given = (("ImageURL", values[route]),)
        elif route in values:
            given = (("Graphic", values[route]),)
        else:
            given = ()
        set_properties(control, list(given) + [
            ("BackgroundColor", GREY), ("PositionX", 8), ("PositionY", y),
            ("Width", W), ("Height", H), ("Border", 0), ("ScaleMode", 2)], name)
        model.insertByName(name, control)
        y += STEP
    model.setPropertyValue("Width", 40)
    model.setPropertyValue("Height", y + 4)
    model.setPropertyValue("Title", TITLE)
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)
    shot = os.path.join(shot_dir, "streams.png")
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(shot_dir, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    origin = window_origin(TITLE)
    print("-- painted (%s)" % (origin,))
    for route in routes:
        control = dialog.getControl("c-" + route)
        rect = control.getPeer().getPosSize()
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        print("   %-12s colour %3d  ring %3d  grey %3d of %d"
              % (route, count(image, box, COLOUR), count(image, box, RING),
                 count(image, box, GREY), (box[2] - box[0] + 1) * (box[3] - box[1] + 1)))
    # a palette switch is the same control asked for another bitmap: does it follow?
    green = png_bytes(23, 17, 0x22AA44, RING)
    for route in ("pipe-signed", "file"):
        name = "c-" + route
        control = model.getByName(name)
        if control is None:
            continue
        try:
            if route == "file":
                with open(os.path.join(shot_dir, "green.png"), "wb") as handle:
                    handle.write(green)
                control.setPropertyValue("ImageURL", uno.systemPathToFileUrl(
                    os.path.join(shot_dir, "green.png")))
            else:
                control.setPropertyValue("Graphic", graphic_from_bytes(ctx, green,
                                                                       route))
        except Exception as error:
            print("%s runtime: %s %s" % (name, error.__class__.__name__, error))
        try:
            dialog.getControl(name).getPeer().invalidate(3)
        except Exception as error:
            print("%s invalidate: %s" % (name, error.__class__.__name__))
    shot = os.path.join(shot_dir, "streams-changed.png")
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(shot_dir, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    print("-- after each was given a GREEN bitmap with the same red ring")
    for route in ("pipe-signed", "file"):
        rect = dialog.getControl("c-" + route).getPeer().getPosSize()
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        print("   %-12s green %3d  ring %3d  old colour %3d of %d"
              % (route, count(image, box, 0x22AA44), count(image, box, RING),
                 count(image, box, COLOUR),
                 (box[2] - box[0] + 1) * (box[3] - box[1] + 1)))
    # the grid must not be tabbable: a label is not, an image control might be
    for name in ("c-pipe-signed",):
        for property_name, value in (("Tabstop", False), ("Tag", "00FF00"),
                                     ("Name", name)):
            try:
                model.getByName(name).setPropertyValue(property_name, value)
            except Exception as error:
                print("%s.%s: %s" % (name, property_name, error.__class__.__name__))
    print("tabstop/tag accepted")
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
