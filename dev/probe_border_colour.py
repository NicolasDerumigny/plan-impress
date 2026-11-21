#!/usr/bin/env python3
"""Can a swatch be outlined in a colour of our own, and how dark is the theme?

    DISPLAY=:98 python3 dev/probe_border_colour.py

The office's own colour dropdown paints a thin **light** line round every swatch on
a dark theme (and a dark one on a light theme), so that black and white both read as
squares.  ``Border = BorderStyle.LINE`` on a label gives a flat ring, but in the
theme's own colour: ``BorderColor`` is accepted and ignored (fact 78), and on this
dark theme that ring is ``#2B2E39`` - darker than the dialog behind it, so a dark
colour has no edge at all.

Three things have to be measured before that can be fixed, and none of them can be
asserted on:

1. the **real** ``com.sun.star.awt.BorderStyle`` constants.  ``LINE`` is assumed to be
   2 in the code, and if the enum is in fact ``NONE 0, RAISED 1, LOWERED 2, ...`` then
   the value that honours ``BorderColor`` is some other number that has never been
   tried here;
2. which of those values paints the requested ``BorderColor`` - one row per value, a
   colour that cannot be mistaken (red) round a colour that cannot be mistaken
   (``#1F4E79``), found in the screenshot *by its colour* because the window's peer
   answers ``0,0`` (fact 76);
3. what the office will say about the theme: the AWT toolkit's ``XStyleFacility``
   settings for the dialog, and the office's own configuration for a theme name.  A
   border has to be the *contrast* of the background, so there has to be a way to ask
   how dark that background is.

``scrot`` must run next door; the shot is taken synchronously (fact 74).
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

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/border")
COLOUR = 0x1F4E79                  # the swatch
RED = 0xFF0000                     # the border we ask for
W, H = 24, 14                      # dialog units
X0, Y0, STEP = 8, 8, 20
TOLERANCE = 14
STYLES = list(range(0, 7))         # every value the enum could conceivably have
STYLE_NAMES = ("NONE", "RAISED", "LOWERED", "BOLD_OUTLINE", "DASHED_OUTLINE",
               "LINE", "?")


def blocks(image, colour, expected):
    """The ``(x0, y0, x1, y1)`` of each square painted ``colour``, top to bottom."""
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
                         dtype=numpy.int16)
    arr = numpy.asarray(image).astype(numpy.int16)
    mask = numpy.abs(arr - wanted).max(axis=2) <= TOLERANCE
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 4)
    if not len(rows):
        return []
    groups, start, previous = [], rows[0], rows[0]
    for row in rows[1:]:
        if row > previous + 2:
            groups.append((start, previous))
            start = row
        previous = row
    groups.append((start, previous))
    out = []
    for top, bottom in groups:
        columns = numpy.flatnonzero(mask[top:bottom + 1].sum(axis=0) >= 2)
        out.append((int(columns.min()), int(top), int(columns.max()), int(bottom)))
    if len(out) != expected:
        print("found %d blocks of #%06X, expected %d" % (len(out), colour, expected))
    return out


def ring(image, block):
    """The colour of the pixels just outside the swatch, and whether it is one tone."""
    x0, y0, x1, y1 = block
    pixels = [image.getpixel((x, y0 - 1)) for x in range(x0, x1 + 1)]
    pixels += [image.getpixel((x, y1 + 1)) for x in range(x0, x1 + 1)]
    pixels += [image.getpixel((x0 - 1, y)) for y in range(y0, y1 + 1)]
    pixels += [image.getpixel((x1 + 1, y)) for y in range(y0, y1 + 1)]
    pixels = [p for p in pixels if p]
    if not pixels:
        return "n/a"
    darkest = min(pixels, key=sum)
    lightest = max(pixels, key=sum)
    tone = "one tone" if sum(lightest) - sum(darkest) <= 3 * TOLERANCE else "MIXED"
    return "#%02X%02X%02X..#%02X%02X%02X %s" % (darkest + lightest + (tone,))


def red_ring(image, block):
    """How much of the ring is the red we asked for: the only honest yes/no."""
    x0, y0, x1, y1 = block
    wanted = numpy.array([255, 0, 0], dtype=numpy.int16)
    count = total = 0
    for x, y in ([(x, y0 - 1) for x in range(x0, x1 + 1)]
                 + [(x, y1 + 1) for x in range(x0, x1 + 1)]
                 + [(x0 - 1, y) for y in range(y0, y1 + 1)]
                 + [(x1 + 1, y) for y in range(y0, y1 + 1)]):
        try:
            pixel = numpy.array(image.getpixel((x, y)), dtype=numpy.int16)
        except Exception:
            continue
        total += 1
        if numpy.abs(pixel - wanted).max() <= 40:
            count += 1
    return "%d/%d red" % (count, total)


def enum_values():
    """The ``BorderStyle`` constants, however pyuno will hand them over."""
    out = {}
    try:
        from com.sun.star.awt import BorderStyle  # noqa: F401
        for name in dir(BorderStyle):
            if name.isupper():
                try:
                    out[name] = int(getattr(BorderStyle, name).value)
                except Exception:
                    try:
                        out[name] = int(getattr(BorderStyle, name))
                    except Exception:
                        pass
        if out:
            print("imported BorderStyle: %s" % out)
    except Exception as error:
        print("import BorderStyle: %s" % error.__class__.__name__)
    return out


def type_repository_values(ctx):
    """Ask the type repository, if the import gave nothing."""
    try:
        description = ctx.getByName("com.sun.star.awt.BorderStyle")
    except Exception as error:
        print("ctx.getByName(BorderStyle): %s" % error.__class__.__name__)
        return {}
    out = {}
    try:
        for constant in description.EnumConstants:
            value = constant.Value
            out[str(constant.Name)] = int(value.Value if hasattr(value, "Value")
                                          else value)
    except Exception as error:
        print("EnumConstants: %s: %s" % (error.__class__.__name__, error))
    if out:
        print("type repository BorderStyle: %s" % out)
    return out


def style_facility(ctx):
    """What the toolkit says the dialog's own colours are - the theme question."""
    from com.sun.star.awt import XToolkit  # noqa: F401
    toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit",
                                                           ctx)
    print("toolkit services it answers to:")
    for name in ("com.sun.star.awt.XStyleFacility",
                 "com.sun.star.awt.XToolkitExperimental"):
        try:
            print("   %-42s %s" % (name, hasattr(toolkit, name.split(".")[-1])))
        except Exception as error:
            print("   %-42s %s" % (name, error.__class__.__name__))
    for method in ("getSettings", "getDefaultColor", "getStyleNames"):
        print("   has %-16s %s" % (method, hasattr(toolkit, method)))
    for module in ("Application",):
        for style in ("Dialog", "Window", "MessageBox", "PushButton", "CheckBox",
                      "MenuBar", "Docking", "ListBox", "GroupBox", "FixedLine"):
            try:
                settings = toolkit.getSettings(module, style)
            except Exception as error:
                print("getSettings(%s, %s): %s" % (module, style,
                                                   error.__class__.__name__))
                continue
            if settings is None:
                print("getSettings(%s, %s): None" % (module, style))
                continue
            try:
                names = [p.Name for p in settings.getPropertySetInfo()
                         .getProperties()]
            except Exception:
                names = []
            wanted = [n for n in names if "Color" in n or "Dark" in n or "Theme" in n]
            print("getSettings(%s, %s): %d properties, e.g. %s"
                  % (module, style, len(names), wanted[:8]))
            for property_name in wanted[:4]:
                try:
                    print("      %-22s #%06X" % (property_name, int(
                        settings.getPropertyValue(property_name)) & 0xFFFFFF))
                except Exception as error:
                    print("      %s: %s" % (property_name,
                                            error.__class__.__name__))
    return toolkit


def configuration(ctx):
    """The office's own answer to 'which theme is this'."""
    manager = ctx.ServiceManager
    try:
        provider = manager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", ctx)
    except Exception as error:
        print("ConfigurationProvider: %s" % error)
        return
    from com.sun.star.beans import PropertyValue
    argument = PropertyValue()
    argument.Name = "ReadOnly"
    argument.Value = True
    for node in ("/org.openoffice.Office.Common",
                 "/org.openoffice.Office.Common/Theme",
                 "/org.openoffice.Office.Common/VCL",
                 "/org.openoffice.Office.Common/VCL/Properties",
                 "/org.openoffice.Office.Common/Colors/General",
                 "/org.openoffice.Office.Common/Accessibility",
                 "/org.openoffice.Office.Common/View"):
        try:
            argument.Name = "Nodepath"
            argument.Value = node
            view = provider.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationAccess",
                (argument,))
            names = list(view.ElementNames)
        except Exception as error:
            print("%-46s %s" % (node, error.__class__.__name__))
            continue
        print("%-46s %s" % (node, names))
        for name in names:
            try:
                value = view.getByKeyName(name) if hasattr(view, "getByKeyName") \
                    else view.getByName(name)
            except Exception:
                continue
            if hasattr(value, "ElementNames"):
                print("      %-24s %s" % (name, list(value.ElementNames)))
            else:
                print("      %-24s %s" % (name, value))


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    enum_values()
    ctx = lo.connect()
    type_repository_values(ctx)
    manager = ctx.ServiceManager
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog",
                                               ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)
    rows = [(style, colour_name, border)
            for style in STYLES
            for colour_name, border in (("unset", None), ("red", RED))]
    for index, (style, colour_name, border) in enumerate(rows):
        control = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        name = "s%d-%s" % (style, colour_name)
        for property_name, value in (("Label", " "),
                                     ("BackgroundColor", COLOUR),
                                     ("PositionX", X0),
                                     ("PositionY", Y0 + index * STEP),
                                     ("Width", W), ("Height", H),
                                     ("Border", style)):
            try:
                control.setPropertyValue(property_name, value)
            except Exception as error:
                print("%s.%s: %s" % (name, property_name, error.__class__.__name__))
        if border is not None:
            try:
                control.setPropertyValue("BorderColor", border)
            except Exception as error:
                print("%s.BorderColor: %s" % (name, error.__class__.__name__))
        model.insertByName(name, control)
    height = Y0 * 2 + STEP * len(rows) + 4
    for property_name, value in (("Width", X0 * 2 + W + 30), ("Height", height),
                                 ("Title", "border colour probe")):
        try:
            model.setPropertyValue(property_name, value)
        except Exception as error:
            print("dialog %s: %s" % (property_name, error.__class__.__name__))
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.0)
    shot = os.path.join(SHOT, "border.png")
    time.sleep(0.4)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (shot, code))
    image = Image.open(shot).convert("RGB")
    found = blocks(image, COLOUR, 2 * len(STYLES))
    print("-- Border, BorderColor, and what the pixels say")
    pairs = [("s%d-unset" % style, style, False) for style in STYLES]
    pairs += [("s%d-red" % style, style, True) for style in STYLES]
    for (name, style, red), block in zip(sorted(pairs, key=lambda p: (p[1], p[2])),
                                         found):
        print("   %-12s Border=%d %-16s %-22s %s"
              % (name, style, STYLE_NAMES[min(style, len(STYLE_NAMES) - 1)],
                 red_ring(image, block), ring(image, block)))
    dialog.dispose()

    print("-- the theme")
    style_facility(ctx)
    configuration(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
