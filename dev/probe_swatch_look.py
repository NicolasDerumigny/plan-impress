#!/usr/bin/env python3
"""Which control paints a colour as a *flat square with a solid line* around it.

    DISPLAY=:98 python3 dev/probe_swatch_look.py [seconds]

The report is that every colour the extension shows - the squares of the palette
and the swatch beside each colour field in the settings dialog - is drawn with a
"perspective-style border": the raised bevel a *button* gets from the theme.  A
button model has no ``Border``/``BorderColor`` (AGENTS.md fact 65), so the bevel
cannot be switched off; some other control has to paint the colour instead.

This puts one candidate per row in one dialog - a button for reference, then an
image control and a label with each border style, with and without an explicit
border colour - and prints for each of them

  * which border properties its model has at all,
  * what the pixels say.  The window's peer will not say where the window is
    (fact 76: it answers ``0,0`` whatever the window manager decided), so the
    squares are *found* in the screenshot by their colour and the ring of pixels
    just outside each one is what is read: a bevel is a dark ring on one pair of
    sides and a light one on the other, a solid line is one colour all round,
  * whether the ring is still there after the colour is changed at runtime, which
    is what a palette switch does,
  * whether a click reaches it at all, since a cell that cannot be clicked is no
    cell (the mouse listener is what works on this office, fact 64; neither the
    image control nor the label has an action source, so a click has to come from
    ``mousePressed``).

``scrot`` must run next door (see dev/probe_picker_look.py) and the shots are
synced for the same reason.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import unohelper  # noqa: E402
from com.sun.star.awt import XActionListener, XMouseListener  # noqa: E402
import numpy  # noqa: E402
from PIL import Image  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/swatch")
SERVICE = "com.sun.star.awt.UnoControl%sModel"
BORDER_PROPERTIES = ("Border", "BorderColor", "BorderDistance", "BorderLine2",
                     "HelpText", "BackgroundColor", "Label", "FontHeight")
#: the colour every candidate is asked to paint: far from the theme's greys
COLOUR = 0x1F4E79
#: and the one they are changed to after the peers exist: a palette switch
REPAINTED = 0x22AA44
LINE = 0xFF0000                   # a border colour that cannot be mistaken
W, H = 24, 14                     # dialog units: the size of a palette cell
X0, Y0, STEP = 8, 8, 20
TOLERANCE = 14


def variants():
    """``(name, service, [(property, value)])`` - one row each, same colour."""
    out = [("button", SERVICE % "Button", [])]
    for kind, short in (("ImageControl", "image"), ("FixedText", "text")):
        out.append(("%s-none" % short, SERVICE % kind, [("Border", 0)]))
        out.append(("%s-3d" % short, SERVICE % kind, [("Border", 1)]))
        out.append(("%s-line" % short, SERVICE % kind, [("Border", 2)]))
        out.append(("%s-line-red" % short, SERVICE % kind,
                    [("Border", 2), ("BorderColor", LINE)]))
    for index, (_name, _service, props) in enumerate(out):
        props.extend([("BackgroundColor", COLOUR), ("Width", W), ("Height", H),
                      ("PositionX", X0), ("PositionY", Y0 + index * STEP)])
    return out


def properties_of(model):
    """Whether the model has the four border properties at all (fact 65)."""
    try:
        names = set(p.Name for p in model.getPropertySetInfo().getProperties())
    except Exception:
        names = set()
    return dict((p, "yes" if p in names else "NO") for p in BORDER_PROPERTIES)


def blocks(image, colour, expected):
    """The ``(x0, y0, x1, y1)`` of each painted square of ``colour``, top to bottom.

    Found by colour rather than by asking the peer: the window's peer answers
    ``0,0`` for its position, so model rectangles plus peer rectangles do not add
    up to screen pixels.
    """
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255,
                          colour & 255], dtype=numpy.int16)
    arr = numpy.asarray(image).astype(numpy.int16)
    mask = (numpy.abs(arr - wanted).max(axis=2) <= TOLERANCE)
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
        print("found %d blocks of #%06X, expected %d: %s"
              % (len(out), colour, expected, out))
    return out


def ring(image, block):
    """The pixels just outside the colour: that is where a border has to be."""
    x0, y0, x1, y1 = block

    def at(x, y):
        try:
            return image.getpixel((x, y))
        except Exception:
            return None

    sides = {
        "above": [at(x, y0 - 1) for x in range(x0, x1 + 1)],
        "below": [at(x, y1 + 1) for x in range(x0, x1 + 1)],
        "left": [at(x0 - 1, y) for y in range(y0, y1 + 1)],
        "right": [at(x1 + 1, y) for y in range(y0, y1 + 1)],
    }

    def describe(pixels):
        values = [p for p in pixels if p]
        if not values:
            return "n/a"
        darkest = min(values, key=sum)
        lightest = max(values, key=sum)
        return "#%02X%02X%02X..#%02X%02X%02X" % (darkest + lightest)

    middle = at((x0 + x1) // 2, (y0 + y1) // 2) or (0, 0, 0)
    sides_text = " ".join("%s %s" % (side, describe(pixels))
                          for side, pixels in sorted(sides.items()))
    return "inner=#%02X%02X%02X %s" % (middle + (sides_text,))


def shoot(name):
    shot = os.path.join(SHOT, name)
    time.sleep(0.5)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d" % (name, code))
    return shot


def report(heading, wanted, shot, colour):
    image = Image.open(shot).convert("RGB")
    found = blocks(image, colour, len(wanted))
    print("-- %s" % heading)
    for (name, _service, _props), block in zip(wanted, found):
        print("   %-14s %-20s %s" % (name, block, ring(image, block)))
    return found


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    context = lo.connect()
    manager = context.ServiceManager
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog",
                                               context)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              context)
    dialog.setModel(model)
    wanted = variants()
    for name, value in (("Width", X0 * 2 + W + 30),
                        ("Height", Y0 * 2 + STEP * len(wanted)),
                        ("Title", "flat colour probe")):
        try:
            model.setPropertyValue(name, value)
        except Exception as error:
            print("dialog %s: %s" % (name, error.__class__.__name__))
    for name, service, props in wanted:
        control_model = model.createInstance(service)
        if control_model is None:
            print("%-14s %s: createInstance answers None" % (name, service))
            continue
        refused = []
        for property_name, value in props:
            try:
                control_model.setPropertyValue(property_name, value)
            except Exception as error:
                refused.append("%s/%s" % (property_name, error.__class__.__name__))
        model.insertByName(name, control_model)
        print("%-14s %-24s refused=%-16s %s"
              % (name, service.split(".")[-1], ",".join(refused) or "-",
                 properties_of(control_model)))

    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", context)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)

    events = []

    class Press(unohelper.Base, XActionListener, XMouseListener):
        def __init__(self, name):
            self.name = name

        def actionPerformed(self, event):
            events.append((self.name, "action"))

        def mousePressed(self, event):
            events.append((self.name, "pressed", event.X, event.Y))

        def mouseReleased(self, event):
            events.append((self.name, "released"))

        def mouseEntered(self, event):
            events.append((self.name, "entered"))

        def mouseExited(self, event):
            pass

        def disposing(self, event):
            pass

    for name, _service, _props in wanted:
        control = dialog.getControl(name)
        if control is None:
            print("%-14s no control" % name)
            continue
        listener = Press(name)
        for method in ("addMouseListener", "addActionListener"):
            try:
                getattr(control, method)(listener)
            except Exception as error:
                print("%-14s %s: %s" % (name, method, error.__class__.__name__))
    time.sleep(1.0)
    found = report("as built", wanted, shoot("swatch-variants.png"), COLOUR)

    # what a palette switch does: the colour changes, the border has to survive it
    for name, _service, _props in wanted:
        try:
            model.getByName(name).setPropertyValue("BackgroundColor", REPAINTED)
        except Exception as error:
            print("%-14s BackgroundColor: %s" % (name, error.__class__.__name__))
    for name, _service, _props in wanted:
        try:
            dialog.getControl(name).getPeer().invalidate(3)
        except Exception:
            pass
    report("after the colour was changed", wanted,
           shoot("swatch-repainted.png"), REPAINTED)

    # and a click on each: a colour one cannot pick is not a palette cell
    for (name, _service, _props), block in zip(wanted, found):
        centre = ((block[0] + block[2]) // 2, (block[1] + block[3]) // 2)
        for argv in (["mousemove", str(centre[0]), str(centre[1])], ["click", "1"]):
            subprocess.run(["xdotool"] + argv, check=False, timeout=10)
        time.sleep(0.2)
    print("events: %s" % (events,))
    if seconds > 0:
        time.sleep(seconds)
    dialog.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
