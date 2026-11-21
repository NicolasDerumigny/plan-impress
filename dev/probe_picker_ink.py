#!/usr/bin/env python3
"""What the chooser paints: the name, the page number, the squares, the hex field.

Four reports about the chooser are about pixels and no property can see any of them -
"the dropdown says *In this presenta*", "(1/1) is still too close to < and >", "the
color sample must be exact squares, not rectangles" and "the field to set the hex
value is a bit too narrow".  So the row is painted for real - the controls
``picker.header_specs``, ``picker.cell_specs`` and ``picker.bottom_specs`` describe,
at the rectangles they give, with the bitmap ``swatch`` draws for each colour - and
photographed, and the answer comes out of the pixels:

* the selector's words, against the same words in a ``FixedText`` of the same font
  that nothing can cut;
* the ink of ``<``, of the page number and of ``>``, and the clear air between the
  *glyphs*, which is *not* the gap between the boxes: a ``FixedText`` paints its words
  at the left of its box (no ``TextAlign``, fact 72) and the theme centres a button's
  label inside its own bevel;
* each square's control box, the block of its own colour inside it and the ring of
  contrast colour round that block - a square is the same number of pixels both ways,
  which a dialog unit is not (2.53 x 2.39, fact 28), and how far apart two squares
  are is what "a few px between colors" asks for;
* the value in the hex field against the same characters in the reference.

The client area is anchored on a square painted a colour the theme never uses, because
the window's peer answers ``0,0`` whatever the window manager decided (fact 76) and the
desktop here is the same grey as the dialog.  The reference labels and the calibration
candidates are painted *below* the window, where no row of squares can be mistaken for
digits.

    DISPLAY=:98 python3 dev/probe_picker_ink.py [pages] [widest_pages]
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

from plan_impress import dialog, palettes, picker, swatch  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/ink")
ANCHOR = 0x7FFF00
DIALOG_GREY = 0x383C4A
CALIBRATE = 0x00FF7F                 # only the candidate squares wear this
INK = 170
UNIT_X, UNIT_Y = swatch.PX_PER_UNIT_X, swatch.PX_PER_UNIT_Y
NAME = "In this presentation"
CURRENT = 0x1F4E79
#: What the field shows (the picker writes the colour into it) and what a user can type
#: into it - ``config.hex_to_color`` accepts the leading ``#``, so the field has to be
#: wide enough for the seven characters, not the six it paints.
HEX_TEXT = "1F4E79"
HEX_TYPED = "#1F4E79"
#: Candidate sizes for a colour square, in units.  One unit is 2.53 x 2.39 px, so equal
#: units do not paint equal pixels and the pair that does has to come out of the
#: screenshot - this is how ``swatch.square_units`` got its 13 x 14.
CANDIDATES = [(9, 7), (9, 10), (11, 12), (13, 14), (14, 14), (16, 17)]
#: Widths for the hex field, in units, all painting the same value: the one that first
#: stops growing is the width the value needs.  26 is the button's width, which is what
#: the field used before it had one of its own.
HEX_WIDTHS = (20, 23, 26, 29)


def add(model, name, service, props):
    """One control, at the rectangle the specs give it.

    ``service`` is the full model service name the specs carry
    (``com.sun.star.awt.UnoControlListBoxModel``): the model comes from the dialog
    model's own ``createInstance``, which is the only way it keeps its geometry
    (fact 25), and the *model* object is what ``insertByName`` takes (fact 26).
    """
    if "." not in service:                      # a short name, for the probe's own
        service = "com.sun.star.awt.UnoControl%sModel" % service
    control = model.createInstance(service)
    for property_name, value in props:
        try:
            control.setPropertyValue(property_name,
                                     dialog._coerce(property_name, value))
        except Exception as error:
            print("%s.%s: %s" % (name, property_name, error.__class__.__name__))
    model.insertByName(name, control)
    return control


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


def ink(image, origin, rect, threshold=INK):
    """``(x0, x1)`` of the bright pixels inside a peer rectangle, screen pixels."""
    x0, y0 = origin
    band = numpy.asarray(image)[y0 + rect[1]: y0 + rect[1] + rect[3],
                                x0 + rect[0]: x0 + rect[0] + rect[2]]
    if not band.size:
        return None
    bright = band.astype(numpy.int16).max(axis=2) > threshold
    columns = numpy.flatnonzero(bright.sum(axis=0) > 0)
    if not len(columns):
        return None
    return int(columns[0] + x0 + rect[0]), int(columns[-1] + x0 + rect[0])


def block(image, origin, rect, colour):
    """``(x0, y0, w, h)`` of the pixels of one colour inside a peer rectangle."""
    wanted = numpy.array([(colour >> 16) & 255, (colour >> 8) & 255, colour & 255],
                         dtype=numpy.int16)
    x0, y0 = origin
    arr = numpy.asarray(image).astype(numpy.int16)
    top, left = y0 + rect[1], x0 + rect[0]
    band = arr[top:top + rect[3], left:left + rect[2]]
    if not band.size:
        return None
    mask = numpy.abs(band - wanted).max(axis=2) <= 10
    rows = numpy.flatnonzero(mask.sum(axis=1) >= 2)
    columns = numpy.flatnonzero(mask.sum(axis=0) >= 2)
    if not len(rows) or not len(columns):
        return None
    return (int(columns[0] + left), int(rows[0] + top),
            int(columns[-1] - columns[0] + 1), int(rows[-1] - rows[0] + 1))


def main():
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    widest = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ctx = lo.connect()
    manager = ctx.ServiceManager
    dialog_control = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    dialog_control.setModel(model)

    names = [name for name, _colours in palettes.load_palettes()]
    if NAME not in names:
        names.insert(0, NAME)
    width = picker.content_width(names, widest)
    recent = [("#112233", 0x112233)]
    bands = picker.full_bands(recent, NAME)
    bottom = picker.bottom_of(bands)
    entries = picker.recent_colours(recent) + \
        [("Blue %d" % index, 0x2A57D7 + 0x100 * index)
         for index in range(picker.page_size(recent))]
    specs = picker.header_specs(names, pages, 0, 0, widest, width)
    specs += picker.caption_specs(bands, picker.grid_x(width))
    specs += picker.cell_specs(bands, CURRENT, entries, picker.grid_x(width))
    specs += picker.bottom_specs(bottom, CURRENT, HEX_TEXT, picker.grid_x(width))
    rows = dict((name, dict(props)) for name, _service, props in specs)
    colour_of = dict((cell, entry[1])
                     for cell, entry in zip([picker.cell_name(i)
                                             for i in range(len(entries))], entries))
    colour_of["preview"] = CURRENT
    dark = swatch.theme_is_dark(ctx)

    add(model, "anchor", "FixedText", [
        ("Label", ""), ("PositionX", 2), ("PositionY", 2), ("Width", 4),
        ("Height", 3), ("BackgroundColor", ANCHOR)])
    # the same words and the same digits, where nothing can cut them
    references = ((NAME, "reference0"), (picker.page_label(0, pages), "reference1"),
                  (HEX_TEXT, "reference2"))
    for index, (label, name) in enumerate(references):
        add(model, name, "FixedText", [
            ("Label", label), ("PositionX", 4),
            ("PositionY", picker.dialog_height(bottom) + 4 + index * 12),
            ("Width", 80), ("Height", 9), ("FontHeight", picker.font_height())])
    for index, (units_w, units_h) in enumerate(CANDIDATES):
        add(model, "c%d" % index, "FixedText", [
            ("Label", ""), ("PositionX", 4 + (index % 3) * 26),
            ("PositionY", picker.dialog_height(bottom) + 44 + (index // 3) * 24),
            ("Width", units_w), ("Height", units_h),
            ("BackgroundColor", CALIBRATE)])
    # Three copies of the hex field at three widths: the only way to tell a field that
    # paints its whole value from one that clips it is to give it more room and see
    # whether the ink grows.  If it does, the value was cut at the smaller width.
    for index, units in enumerate(HEX_WIDTHS):
        add(model, "h%d" % index, "Edit", [
            ("Text", HEX_TYPED), ("PositionX", 88),
            ("PositionY", picker.dialog_height(bottom) + 44 + index * 22),
            ("Width", units), ("Height", picker._BUTTON_H),
            ("FontHeight", picker.font_height())])
    for name, service, props in specs:
        add(model, name, service, props)
    for property_name, value in (("Width", width),
                                 ("Height", picker.dialog_height(bottom) + 140),
                                 ("Title", "chooser ink"),
                                 ("BackgroundColor", DIALOG_GREY)):
        try:
            model.setPropertyValue(property_name, value)
        except Exception as error:
            print("dialog %s: %s" % (property_name, error.__class__.__name__))
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog_control.createPeer(toolkit, None)
    dialog_control.setVisible(True)

    # the bitmaps, the way ColourPicker._set_graphic hands them out: after the peer
    def peer(name):
        rect = dialog_control.getControl(name).getPeer().getPosSize()
        return (rect.X, rect.Y, rect.Width, rect.Height)

    for name in list(colour_of):
        try:
            control_model = model.getByName(name)
        except Exception:
            continue
        made = swatch.graphic(ctx, colour_of[name], *swatch.bitmap_size(
            rows[name]["Width"], rows[name]["Height"]),
            ring=swatch.ring_colour(colour_of[name], dark))
        if made is not None:
            control_model.setPropertyValue("Graphic", made)
    time.sleep(1.2)

    shot = os.path.join(SHOT, "ink.png")
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, os.path.join(SHOT, "scrot.log"))])
    print("shot %s -> %d   (%d names, %d pages, window %d units = %d px, "
          "%d units tall, theme %s)"
          % (shot, code, len(names), pages, width, width * UNIT_X,
             picker.dialog_height(bottom),
             "dark" if dark else "light" if dark is not None else "unknown"))
    image = Image.open(shot).convert("RGB")
    origin = origin_of(image, dialog_control.getControl("anchor").getPeer()
                       .getPosSize())
    print("client area begins at %s" % (origin,))
    if not origin:
        dialog_control.dispose()
        return 1

    def reference(index):
        return ink(image, origin, peer("reference%d" % index))

    words = reference(0)
    box = ink(image, origin, peer("palettes"))
    if words and box:
        print("%-22s words %d px in the reference, %d px in the selector (its box is "
              "%d px) -> %s" % (NAME, words[1] - words[0], box[1] - box[0],
                                peer("palettes")[2],
                                "CUT" if box[1] - box[0] < words[1] - words[0] - 2
                                else "whole"))
    digits = reference(1)
    label = ink(image, origin, peer("page"))
    if digits and label:
        # The page indicator's box is sized by arithmetic (a ``FixedText`` can neither
        # centre nor wrap, fact 72), so these two numbers - how much of the box the
        # words do not use on either side - are the whole answer to "the 2/2 is
        # slightly cut on the right (not enough padding?)": a right margin of 0 or 1 px
        # means the last digit is being painted past the edge of its own control.
        box = peer("page")
        ink_w = label[1] - label[0] + 1
        left_pad = label[0] - box[0]
        right_pad = box[0] + box[2] - 1 - label[1]
        print("%-10s %d px in the reference, %d px in the indicator (its box is %d px "
              "= %d units): %d px of air before it and %d px after -> %s"
              % (picker.page_label(0, pages), digits[1] - digits[0], ink_w, box[2],
                 rows["page"]["Width"], left_pad, right_pad,
                 "CUT" if (ink_w < digits[1] - digits[0] - 2 or right_pad <= 1)
                 else "whole"))
    spans = dict((name, ink(image, origin, peer(name)))
                 for name in ("previous", "page", "next"))
    print("ink: %s" % spans)
    if spans.get("previous") and spans.get("page") and spans.get("next"):
        left_air = spans["page"][0] - spans["previous"][1]
        right_air = spans["next"][0] - spans["page"][1]
        centre = (spans["page"][0] + spans["page"][1]) / 2.0
        midway = ((spans["previous"][0] + spans["previous"][1]) / 2.0
                  + (spans["next"][0] + spans["next"][1]) / 2.0) / 2.0
        print("air between the glyphs: %d px = %.1f units left, %d px = %.1f units "
              "right; the number is %+.1f px off the midway between the arrows; "
              "_PAGER_AIR is %d units"
              % (left_air, left_air / UNIT_X, right_air, right_air / UNIT_X,
                 centre - midway, picker._PAGER_AIR))

    # the squares: the same number of pixels wide and tall, a line of the contrast
    # colour inside them, and clear air between one and the next
    print("squares (control box, the block of its colour inside it, the line round "
          "that block):")
    for name in ("cell0", "cell1", "cell10", "preview"):
        if name not in rows:
            continue
        rect = peer(name)
        painted = block(image, origin, rect, colour_of[name])
        ring = swatch.ring_colour(colour_of[name], dark)
        inside = block(image, origin, rect, ring) if ring is not None else None
        print("  %-8s control %dx%d px, colour %s, line %s  (model %dx%d units)"
              % (name, rect[2], rect[3],
                 "%dx%d px" % painted[2:] if painted else "nothing",
                 "%dx%d px" % inside[2:] if inside else "nothing",
                 rows[name]["Width"], rows[name]["Height"]))
    for pair, axis in ((("cell10", "cell11"), "x"), (("cell10", "cell20"), "y")):
        first = block(image, origin, peer(pair[0]), colour_of[pair[0]])
        second = block(image, origin, peer(pair[1]), colour_of[pair[1]])
        if not first or not second:
            continue
        if axis == "x":
            gap, unit = second[0] - (first[0] + first[2]), UNIT_X
        else:
            gap, unit = second[1] - (first[1] + first[3]), UNIT_Y
        print("  %s to %s: %d px of clear air (%.1f units)"
              % (pair[0], pair[1], gap, gap / unit))
    field = ink(image, origin, peer("hex"))
    digits = reference(2)
    if field and digits:
        print("%-10s %d px in the reference, %d px in the field (its box is %d px = "
              "%d units) -> %s"
              % (HEX_TEXT, digits[1] - digits[0], field[1] - field[0],
                 peer("hex")[2], rows["hex"]["Width"],
                 "CUT" if field[1] - field[0] < digits[1] - digits[0] - 2 else "whole"))
    print("painted px per candidate (w, h) in units:")
    for index, (units_w, units_h) in enumerate(CANDIDATES):
        painted = block(image, origin, peer("c%d" % index), CALIBRATE)
        print("   %2dx%-2d units -> %s" % (units_w, units_h,
                                           "%dx%d px" % painted[2:]
                                           if painted else "none"))
    print("the value in a field of each width (the width where the ink stops growing "
          "is the width it needs):")
    for index, units in enumerate(HEX_WIDTHS):
        rect = peer("h%d" % index)
        painted = ink(image, origin, rect)
        print("   %2d units = %3d px of box -> %s"
              % (units, rect[2],
                 "%d px of digits" % (painted[1] - painted[0] + 1) if painted
                 else "nothing"))
    dialog_control.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
