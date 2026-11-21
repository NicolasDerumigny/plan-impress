#!/usr/bin/env python3
"""What an image control will accept, and what the office will say about its theme.

    DISPLAY=:98 python3 dev/probe_swatch_ring2.py

``dev/probe_swatch_ring.py`` settled the mechanism: one ``UnoControlImageControlModel``
paints a PNG of our own - a 1-px ring in any colour, the colour inside it - answers the
mouse and takes a new bitmap after ``createPeer``.  Four questions stand between that
and code in ``picker.py``, and all four are answered by pixels or by what the API
answers, not by an assumption:

1. **Does it stretch?** ``ImagePosition`` and ``ImageData`` are absent from this build's
   model, so there may be no knob at all. If the control draws the bitmap at its natural
   size, a bitmap made for another screen's DPI leaves grey in the corners, and the PNGs
   would have to be written at the control's *pixel* size after the peer exists. Three
   cells therefore get the same swatch as a tiny, an exact and a huge bitmap, and the
   amount of grey left in the crop is the answer.
2. **Which properties does the model actually have?** Printed in full: the ones that
   exist decide whether the ring, the fill and the tooltip can be set at all.
3. **Where may the files be written?** The bytes have to live in a file - there is no
   ``ImageData`` - so the office's own temp folder is the polite answer:
   ``/org.openoffice.Office.Common/Path/Current`` says where it is.
4. **How dark is the theme?** The ring has to be the contrast of the dialog, so
   something has to say whether the dialog is dark. Everything the office can be asked
   is asked here: ``XControl::getBackground`` on the dialog and on a control nobody
   coloured, the ``Appearance`` and ``Accessibility`` configuration nodes, and the
   environment. Whatever *works* is what ``picker`` will read.
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
import numpy  # noqa: E402
from PIL import Image  # noqa: E402
import uno  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/ring2")
COLOUR = 0x1F4E79
RING = 0xFF0000
GREY = 0x808080                 # the control's own background: uncovered pixels
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


def set_properties(control, values, name):
    for property_name, value in values:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("   %s.%s: %s" % (name, property_name, error.__class__.__name__))


def property_names(control):
    try:
        return sorted(p.Name for p in control.getPropertySetInfo().getProperties())
    except Exception as error:
        return ["<%s>" % error.__class__.__name__]


def configuration(ctx, node):
    from com.sun.star.beans import PropertyValue
    try:
        provider = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", ctx)
        argument = PropertyValue()
        argument.Name = "ReadOnly"
        argument.Value = True
        argument2 = PropertyValue()
        argument2.Name = "Nodepath"
        argument2.Value = node
        view = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess", (argument, argument2))
        return dict((name, view.getByName(name)) for name in view.ElementNames)
    except Exception as error:
        print("%s: %s" % (node, error.__class__.__name__))
        return {}


def theme(ctx, dialog, model):
    print("-- how dark is the theme")
    for holder, name in ((dialog, "dialog control"),
                         (dialog.getControl("tiny"), "an image control"),
                         (dialog.getControl("plain"), "a label")):
        if holder is None:
            continue
        try:
            background = holder.getBackground()
        except Exception as error:
            print("   %-16s getBackground: %s" % (name, error.__class__.__name__))
            continue
        if background is None:
            print("   %-16s getBackground: None (nobody set one)" % name)
            continue
        answer = {}
        for method in ("getBackgroundColor", "getTextColor", "getFillColor"):
            try:
                answer[method] = int(getattr(background, method)()) & 0xFFFFFF
            except Exception as error:
                answer[method] = error.__class__.__name__
        print("   %-16s getBackground: %s" % (name, answer))
    for node in ("/org.openoffice.Office.Common/Appearance",
                 "/org.openoffice.Office.Common/Accessibility",
                 "/org.openoffice.Office.Common/Colors/Modify"):
        values = configuration(ctx, node)
        for key in sorted(values):
            if any(word in key for word in ("Theme", "Appearance", "Contrast",
                                            "Color", "Dark", "Background")):
                print("   %-46s %s = %r" % (node, key, values[key]))
    for variable in ("GTK_THEME", "XDG_CURRENT_DESKTOP", "KDE_FULL_SESSION",
                     "COLORFGBG", "QT_QPA_PLATFORMTHEME"):
        print("   env %-23s %s" % (variable, os.environ.get(variable, "<unset>")))


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    # the same swatch three ways: much smaller, exactly the control's pixel size, and
    # much bigger, so stretching against natural size is visible rather than guessed
    sizes = {"tiny": (4, 3), "exact": (28, 19), "huge": (70, 48)}
    paths = {}
    for tag, (width, height) in sizes.items():
        path = os.path.join(SHOT, "swatch-%s.png" % tag)
        with open(path, "wb") as handle:
            handle.write(png_bytes(width, height, COLOUR, RING))
        paths[tag] = uno.systemPathToFileUrl(path)

    ctx = lo.connect()
    manager = ctx.ServiceManager
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)

    print("-- the image control model's own properties")
    probe = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
    names = property_names(probe)
    print("   %s" % ", ".join(names))
    for wanted in ("ImagePosition", "ImageScale", "ImageData", "NativeImage",
                   "FixedImagePosition", "Border", "BorderColor", "HelpText",
                   "BackgroundColor"):
        print("   has %-18s %s" % (wanted, wanted in names))

    y = 8
    for tag in ("tiny", "exact", "huge"):
        control = model.createInstance("com.sun.star.awt.UnoControlImageControlModel")
        set_properties(control, (("ImageURL", paths[tag]),
                                 ("BackgroundColor", GREY),
                                 ("HelpText", "the colour name"),
                                 ("PositionX", 8), ("PositionY", y),
                                 ("Width", W), ("Height", H), ("Border", 0)), tag)
        model.insertByName(tag, control)
        y += STEP
    label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    set_properties(label, (("Label", ""), ("BackgroundColor", GREY),
                           ("PositionX", 8), ("PositionY", y),
                           ("Width", W), ("Height", H), ("Border", 0)), "plain")
    model.insertByName("plain", label)
    y += STEP

    model.setPropertyValue("Width", 40)
    model.setPropertyValue("Height", y + 4)
    model.setPropertyValue("Title", "plan-impress stretch probe")
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)

    shot = os.path.join(SHOT, "stretch.png")
    time.sleep(0.4)
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(SHOT, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    print("-- does the bitmap fill the control?")
    for tag in list(sizes) + ["plain"]:
        control = dialog.getControl(tag)
        rect = control.getPeer().getPosSize()
        print("   %-6s peer %dx%d px" % (tag, rect.Width, rect.Height))
    print("   (the window's own peer says %s - fact 76, so the shot is searched)"
          % ((dialog.getPeer().getPosSize() if dialog.getPeer() else None),))
    # find the dialog in the shot by its grey controls: the plain one is a known block
    arr = numpy.asarray(image).astype(numpy.int16)
    wanted = numpy.array([(GREY >> 16) & 255, (GREY >> 8) & 255, GREY & 255],
                         dtype=numpy.int16)
    mask = numpy.abs(arr - wanted).max(axis=2) <= TOLERANCE
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 4)
    groups, start, previous = [], rows[0], rows[0]
    for row in rows[1:]:
        if row > previous + 2:
            groups.append((start, previous))
            start = row
        previous = row
    groups.append((start, previous))
    print("-- %d rows of grey: %s" % (len(groups), groups))
    for (top, bottom), tag in zip(groups, list(sizes) + ["plain"]):
        columns = numpy.flatnonzero(mask[top:bottom + 1].sum(axis=0) >= 2)
        box = (int(columns.min()), int(top), int(columns.max()), int(bottom))
        total = (box[2] - box[0] + 1) * (box[3] - box[1] + 1)
        print("   %-6s crop %-22s of %-4d  colour %3d  ring %3d  grey %3d"
              % (tag, box, total, count(image, box, COLOUR), count(image, box, RING),
                 count(image, box, GREY)))

    theme(ctx, dialog, model)
    print("-- the office's temp folder")
    values = configuration(ctx, "/org.openoffice.Office.Common/Path/Current")
    for key in sorted(values):
        if "emp" in key:
            print("   %-14s %r" % (key, values[key]))
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
