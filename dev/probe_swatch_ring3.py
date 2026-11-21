#!/usr/bin/env python3
"""Can the swatch's bitmap come from memory, and does the control stretch it?

    DISPLAY=:98 python3 dev/probe_swatch_ring3.py

``dev/probe_swatch_ring.py`` showed an ``UnoControlImageControlModel`` paints a PNG of
our own with a 1-px ring in any colour we ask for, answers the mouse and takes a new
bitmap after ``createPeer``.  Two things are still between that and ``picker.py``, and
``dev/probe_swatch_ring2.py`` narrowed them down:

* the model has no ``ImageData`` but it *does* have ``Graphic`` - an
  ``com.sun.star.graphic.XGraphic``.  If a graphic can be made from a byte sequence by
  the ``GraphicProvider``, nothing has to be written to a user's disk at all, which is
  the difference between a picker with a cache folder and one without.  So the same
  swatch goes in three ways: ``ImageURL`` from a file, ``Graphic`` from a
  ``SequenceInputStream``, and ``Graphic`` from a ``Pipe``;
* the model has no ``ImagePosition`` but it has ``ScaleMode`` and ``ScaleImage``, so the
  question "does a bitmap of the wrong pixel size leave grey in the corners" has an
  answer to measure.  A swatch whose PNG is 4 x 3 px goes into a 28 x 19 px control:
  stretched, the drawn ring ends up several pixels thick; not stretched, grey shows.
  Every value of ``ScaleMode`` is tried, and the grey and red pixel counts say which is
  which.

The pixel counts are taken from the control's own rectangle on the screen, found with
``xdotool`` because the window's peer answers ``0,0`` (fact 76).
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
import numpy  # noqa: E402
from PIL import Image  # noqa: E402
import uno  # noqa: E402

TITLE = "plan-impress graphic probe"
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


def graphic_from_bytes(ctx, payload, route):
    """An XGraphic out of the PNG bytes, the two ways that do not touch the disk."""
    from com.sun.star.beans import PropertyValue
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", ctx)
    argument = PropertyValue()
    if route == "sequence":
        stream = uno.createUnoStruct("com.sun.star.io.SequenceInputStream")
        stream.InputStream = tuple(payload)
        argument.Name = "InputStream"
        argument.Value = stream
    else:
        pipe = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.io.Pipe", ctx)
        pipe.writeBytes(tuple(payload))
        pipe.closeOutput()
        argument.Name = "InputStream"
        argument.Value = pipe
    return provider.queryGraphic((argument,))


def set_properties(control, values, name):
    for property_name, value in values:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("   %s.%s: %s" % (name, property_name, error.__class__.__name__))


def main():
    if not os.path.isdir(os.environ.get("PROBE_SHOT", "/tmp/opencode/ring3")):
        os.makedirs(os.environ["PROBE_SHOT"])
    shot_dir = os.environ["PROBE_SHOT"]
    big = png_bytes(28, 19, COLOUR, RING)
    tiny = png_bytes(4, 3, COLOUR, RING)
    path = os.path.join(shot_dir, "swatch.png")
    with open(path, "wb") as handle:
        handle.write(big)
    tiny_path = os.path.join(shot_dir, "tiny.png")
    with open(tiny_path, "wb") as handle:
        handle.write(tiny)
    url = uno.systemPathToFileUrl(path)
    tiny_url = uno.systemPathToFileUrl(tiny_path)

    ctx = lo.connect()
    manager = ctx.ServiceManager

    graphics = {}
    for route in ("sequence", "pipe"):
        try:
            graphics[route] = graphic_from_bytes(ctx, big, route)
            print("graphic from %-9s %s" % (route, graphics[route]))
        except Exception as error:
            print("graphic from %-9s %s: %s" % (route, error.__class__.__name__, error))

    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)

    y = 8
    rows = []

    def add(name, values, scale=None):
        control = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
        base = [("BackgroundColor", GREY), ("PositionX", 8), ("PositionY", y),
                ("Width", W), ("Height", H), ("Border", 0)]
        set_properties(control, list(values) + base, name)
        if scale is not None:
            set_properties(control, (("ScaleMode", scale),), name)
        model.insertByName(name, control)

    add("url", (("ImageURL", url),))
    rows.append("url")
    y += STEP
    for route in ("sequence", "pipe"):
        if route in graphics:
            add("graphic-%s" % route, (("Graphic", graphics[route]),))
            rows.append("graphic-%s" % route)
            y += STEP
    # the stretch question: a bitmap a seventh the size of the control, at every
    # ScaleMode the enum could plausibly hold
    for scale in range(0, 5):
        name = "tiny-%d" % scale
        add(name, (("ImageURL", tiny_url),), scale=scale)
        rows.append(name)
        y += STEP

    model.setPropertyValue("Width", 40)
    model.setPropertyValue("Height", y + 4)
    model.setPropertyValue("Title", TITLE)
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)

    shot = os.path.join(shot_dir, "graphic.png")
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(shot_dir, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    origin = window_origin(TITLE)
    print("-- painted, from each route (%s)" % (origin,))
    for name in rows:
        control = dialog.getControl(name)
        rect = control.getPeer().getPosSize()
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        total = (box[2] - box[0] + 1) * (box[3] - box[1] + 1)
        print("   %-16s %2dx%2d px  colour %3d  ring %3d  grey %3d of %d"
              % (name, rect.Width, rect.Height, count(image, box, COLOUR),
                 count(image, box, RING), count(image, box, GREY), total))

    # and the same at runtime: a cell changing colour is a palette switch
    for name in [row for row in rows if not row.startswith("tiny")]:
        control = model.getByName(name)
        if control is None:
            continue
        if name == "url":
            set_properties(control, (("ImageURL", tiny_url),), name)
        else:
            try:
                control.setPropertyValue("Graphic", graphic_from_bytes(ctx, tiny,
                                                                       "sequence"))
            except Exception as error:
                print("%s runtime Graphic: %s" % (name, error.__class__.__name__))
        try:
            dialog.getControl(name).getPeer().invalidate(3)
        except Exception as error:
            print("%s invalidate: %s" % (name, error.__class__.__name__))
    shot = os.path.join(shot_dir, "graphic-changed.png")
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(shot_dir, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    print("-- after each was given the 4 x 3 bitmap at runtime")
    for name in ("url", "graphic-sequence", "graphic-pipe"):
        if name not in rows:
            continue
        rect = dialog.getControl(name).getPeer().getPosSize()
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width - 1,
               origin[1] + rect.Y + rect.Height - 1)
        total = (box[2] - box[0] + 1) * (box[3] - box[1] + 1)
        print("   %-16s colour %3d  ring %3d  grey %3d of %d"
              % (name, count(image, box, COLOUR), count(image, box, RING),
                 count(image, box, GREY), total))
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
