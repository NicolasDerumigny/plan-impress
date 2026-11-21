#!/usr/bin/env python3
"""How many characters of a log path fit on one line of a message box.

"The *debug log enable/disable* window message has not enough width, the message is
cut (incomplete path)."  ``dialog.box_lines`` wraps at ``_BOX_CHARS`` characters and
each line is a ``FixedText`` as wide as ``box_size`` says - and a ``FixedText`` wraps
nothing and aligns nothing (fact 72), so a line that is one character too long is
simply painted past the edge of its box and the tail of the path never appears.

Nothing on the label says how wide its words are (fact 46), so the lines are painted
for real and photographed.  Each candidate is one label of the text in question, in the
box's own font and at the box's own label width, with a **reference** label of the same
text in a box four times as wide beside it: the reference shows what the whole line
would measure, the narrow one shows what survives.  A line is therefore ``CUT`` by the
difference, in pixels, and not by an arithmetic nobody on this office can check.

Two phases, because the two lines of the debug box are not the same problem:

* the path, one long word the wrapping has to break by length - the ladder runs over
  prefixes of it, so the largest ``n`` that still fits is visible;
* the sentence in front of it, ``Debug log enabled, writing to``, which is mostly
  lower case but carries capitals and spaces, and capitals are the reason a per-glyph
  width measured on a path alone is not a safe constant.

    DISPLAY=:98 python3 dev/probe_message_width.py [path|message|both]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Outside the office there is no deployment path to read the profile out of (fact 33),
#: and the *length* of that path is the whole question here: the box the user sees names
#: the development profile, which is longer than ``~/.config/libreoffice/4/user``.
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(ROOT, "loprofile", "user", "planimpress"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import numpy  # noqa: E402
from PIL import Image  # noqa: E402

from plan_impress import config, dialog  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/message")
ANCHOR = 0x7FFF00
DIALOG_GREY = 0x383C4A
INK = 170
UNIT_X = 2.53
#: A path of the kind the debug box prints, and the only kind that matters here: no
#: spaces, so ``box_lines`` breaks it by length and never at a nicer place.
PATH = ("/home/derumigny/.config/libreoffice/4/user/planimpress/debug.log")
#: What the *Toggle Debug Log* command actually shows (``handler.do_debug``), with the
#: path this profile really has - the length of that path is what the report was about.
PREFIX = "Debug log enabled, writing to"


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


def text_width():
    """What the box gives a line of the debug message, in units and in pixels.

    The box is as wide as the words it has to show, so this is the width the labels of
    ``main`` are built with: what the reference label beside them measures is the truth
    the narrow one is compared against.
    """
    units = dialog.box_text_width(dialog.box_lines(PREFIX + "\n" + PATH))
    return units, units * UNIT_X


def ladder(model, lines, base, first_row, width):
    """One narrow label and one wide reference per line, named from ``base``.

    The names run on from the previous group, because one dialog holds them all.
    ``{index: (line, y)}`` is what :func:`report` walks.
    """
    rows = {}
    for index, line in enumerate(lines):
        y = first_row + index * (2 * dialog._BOX_LINE_H + 6)
        add(model, "n%d" % (base + index), "com.sun.star.awt.UnoControlFixedTextModel",
            [("Label", line), ("PositionX", 4), ("PositionY", y), ("Width", width),
             ("Height", dialog._BOX_LINE_H), ("FontHeight", dialog._FONT)])
        add(model, "r%d" % (base + index), "com.sun.star.awt.UnoControlFixedTextModel",
            [("Label", line), ("PositionX", 4), ("PositionY", y + dialog._BOX_LINE_H + 2),
             ("Width", 4 * width), ("Height", dialog._BOX_LINE_H),
             ("FontHeight", dialog._FONT)])
        rows[base + index] = (line, y)
    return rows


def report(image, origin, peer, rows, what):
    """Per line: the ink that survives the box, next to the ink of the whole line."""
    lost = 0
    for index in sorted(rows):
        line, _y = rows[index]
        narrow = ink(image, origin, peer("n%d" % index))
        reference = ink(image, origin, peer("r%d" % index))
        if not narrow or not reference:
            print("  %s %-40r nothing painted" % (what, line))
            continue
        box_w = peer("n%d" % index)[2]
        painted = narrow[1] - narrow[0] + 1
        wanted = reference[1] - reference[0] + 1
        if painted >= wanted - 2:
            verdict = "whole, %d px of the box left over" % (box_w - (narrow[1]
                                                                       - narrow[0] + 1))
        else:
            lost += wanted - painted
            verdict = "** CUT by %d px **" % (wanted - painted)
        print("  %s %2d chars: %3d px of ink in a %3d px box, %3d px for the whole "
              "line (%4.2f px a character) -> %s"
              % (what, len(line), painted, box_w, wanted,
                 wanted / max(len(line.strip()) or 1, 1), verdict))
    return lost


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    mode = "both"
    for argument in sys.argv[1:]:
        if argument in ("path", "message", "both"):
            mode = argument
    ctx = lo.connect()
    manager = ctx.ServiceManager
    box = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    box.setModel(model)

    path_lines = [PATH[:count] for count in (30, 32, 34, 36, 38, 40, len(PATH))]
    #: The classes of glyph a message is made of, thirty of each.  A per-glyph width is
    #: only a safe bound if it is the *widest* class, and the widest is not the one a
    #: path is made of - which is how a box sized on a path alone came to cut one.
    classes = ["a" * 30, "M" * 30, "0" * 30, "/" * 30, " " * 30,
               "MWI@" * 7 + "MW", "Éèùçàï" * 5, "Debug log enabled, writing to:"]
    message = "%s:\n%s" % (PREFIX, config.debug_log_path(ctx))
    real_lines = dialog.box_lines(message)
    print("the debug box says: %r" % message)
    print("box_lines wraps that to %d lines: %s"
          % (len(real_lines), [len(line) for line in real_lines]))
    width_units, width_px = text_width()
    print("a line of the box is %d units = %d px, the font is %s pt"
          % (width_units, width_px, dialog._FONT))

    pitch = 2 * dialog._BOX_LINE_H + 6      # the two labels of a row and clear air
    groups, row, row_index = [], 10, 0
    if mode in ("path", "both"):
        groups.append(("path ", ladder(model, path_lines, row_index, row, width_units)))
        row += len(path_lines) * pitch
        row_index += len(path_lines)
        groups.append(("class", ladder(model, classes, row_index, row, width_units)))
        row += len(classes) * pitch
        row_index += len(classes)
    if mode in ("message", "both"):
        groups.append(("line ", ladder(model, real_lines, row_index, row, width_units)))
        row += len(real_lines) * pitch
        row_index += len(real_lines)
    add(model, "anchor", "com.sun.star.awt.UnoControlFixedTextModel", [
        ("Label", ""), ("PositionX", 2), ("PositionY", 2), ("Width", 4),
        ("Height", 3), ("BackgroundColor", ANCHOR)])
    for property_name, value in (("Width", 6 * width_units), ("Height", row + 10),
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
    print("shot %s -> %d" % (shot, code))
    image = Image.open(shot).convert("RGB")
    origin = origin_of(image, box.getControl("anchor").getPeer().getPosSize())
    print("client area begins at %s" % (origin,))
    if not origin:
        box.dispose()
        return 1

    def peer(name):
        rect = box.getControl(name).getPeer().getPosSize()
        return (rect.X, rect.Y, rect.Width, rect.Height)

    headers = {"path ": "the path ladder", "class": "one class of glyph, thirty of them",
               "line ": "the real message"}
    lost = 0
    for what, rows in groups:
        print("%s:" % headers.get(what, what))
        lost += report(image, origin, peer, rows, what)
    print("_BOX_CHARS is %d, _BOX_MARGIN %d units, the window is %d units wide"
          % (dialog._BOX_CHARS, dialog._BOX_MARGIN,
             dialog.box_size(message)[0]))
    box.dispose()
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
