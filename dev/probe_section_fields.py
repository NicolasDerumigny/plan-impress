"""Photograph the settings dialog and print the ink of the *Section Titles* rows.

    DISPLAY=:98 python3 dev/probe_section_fields.py

The section rows are new controls in an existing form, and every one of the
reports about this dialog has been about pixels no property assertion can see:
whether the labels paint at all, whether they are as tall as the menu's letters,
whether one control is drawn on top of another, and whether the font dropdown has
anything in it.  So this shows the dialog, screenshots it synchronously (fact 74)
and measures the *bright* rows inside each control's peer rectangle - the office
runs a dark theme, so words are the light pixels (fact 46).

The peer geometry is asked of each control (`fact 70`), the window's own position
is added because a top-level peer answers 0,0 under no window manager (fact 76),
and the font list is printed because the dropdown can only be filled once the peer
exists (:func:`plan_impress.dialog.SettingsDialog._fill_fonts`).
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PIL import Image  # noqa: E402
import lo  # noqa: E402

from plan_impress import config, dialog  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
THRESHOLD = 165
MIN_PIXELS = 3

#: Every control the section rows add, in the order they are painted.
CONTROLS = ("labelSectionColor", "SectionColor", "swatchSectionColor",
            "labelSectionFont", "SectionFont", "labelSectionSize", "SectionSize",
            "labelSectionX", "captionSectionX", "SectionX", "captionSectionY",
            "SectionY", "captionSectionWidth", "SectionWidth",
            "SectionFollowFirst", "ok", "cancel")


def say(text):
    print(text, flush=True)


#: The peer reports ``Y=0`` at the top of the *client* area, but the office answers
#: the *frame's* position, so the title bar the window manager drew is not accounted
#: for and a crop taken straight from the peer geometry lands ~34 px too high: every
#: label read "nothing painted" and every field read 3 px of the label above it.
#: ``xwininfo`` is no help either - under a window manager it answers the frame too
#: (fact 76).  So the offset is *measured*, the way ``dev/probe_picker_ink.py`` does
#: it: one control is painted a colour nothing else on screen has, and where that
#: colour turns up in the screenshot says where the client area really begins.
_MARKER = 0x7FFF00


def bright_rows(image, box):
    """How many rows of the box hold letters, and how tall the tallest run is.

    ``MIN_PIXELS`` keeps the dialog's own borders and focus rings out of the count,
    but a caption that is one letter wide ("X", "Y") cannot light three pixels in a
    row, so a narrow box is judged by its own width - otherwise a painted caption
    reads as barely there.
    """
    crop = image.crop(box)
    width, height = crop.size
    least = max(1, min(MIN_PIXELS, width // 8))
    pixels = crop.tobytes()                       # mode "L": one byte per pixel
    rows, runs, run = [], [], 0
    for row in range(height):
        line = pixels[row * width:(row + 1) * width]
        lit = sum(1 for value in line if value > THRESHOLD) >= least
        if lit:
            rows.append(row)
            run += 1
        else:
            runs.append(run)
            run = 0
    runs.append(run)
    return len(rows), max(runs or [0])


def marker_origin(image, peer):
    """Where the client area really is, from the dialog painted one odd colour.

    Returns ``(left, top)`` in screen pixels.  The controls paint over the middle of
    it, but the strip round them is the dialog's own background, so the bounding box
    of the marker colour *is* the client rectangle.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    target = (127, 255, 0)
    pixels = rgb.tobytes()                        # mode "RGB": three bytes per pixel
    top = left = None
    bottom = right = -1
    for index in range(width * height):
        offset = index * 3
        if max(abs(pixels[offset] - target[0]),
               abs(pixels[offset + 1] - target[1]),
               abs(pixels[offset + 2] - target[2])) > 24:
            continue
        row, column = divmod(index, width)
        if top is None:
            top, left = row, column
        bottom, right = max(bottom, row), max(right, column)
    if top is None:
        raise AssertionError("the dialog painted no marker colour at all")
    say("marker painted %dx%d at %d,%d (peer asks %dx%d at %d,%d)"
        % (right - left + 1, bottom - top + 1, left, top,
           peer.Width, peer.Height, peer.X, peer.Y))
    return left, top


def main():
    out = os.path.join(ROOT, "out", "section-fields.png")
    marker_shot = os.path.join(ROOT, "out", "section-fields-marker.png")
    say("connecting...")
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    say("opening %s..." % FIXTURE)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    window = dialog.SettingsDialog(
        ctx,
        dict(config.DEFAULTS, section_font="Liberation Serif", section_size=18,
             section_x=1400, section_y=300, section_width=25200,
             section_follow_first=True),
        ["Master 1"])
    window.build()
    try:
        window._peer()
        window.dialog.setTitle("Plan Impress - Settings")
        window.dialog.setVisible(True)
        size = window.dialog.getPosSize()
        model = window.model
        try:
            plain = model.getPropertyValue("BackgroundColor")
        except Exception:
            plain = None
        time.sleep(1.0)
        # synchronous: scrot has to have written the file before it is measured.
        # The plain shot comes *first*: a peer is not told when its model changes
        # (fact 75), so after the marker the transparent controls - the labels and
        # the check box - keep the green behind them and every row of their box then
        # reads as ink.
        subprocess.call(["scrot", "-o", out])
        model.setPropertyValue("BackgroundColor", _MARKER)
        window.dialog.getPeer().invalidate(3)
        time.sleep(0.6)
        subprocess.call(["scrot", "-o", marker_shot])
        origin = marker_origin(Image.open(marker_shot), size)
        if plain is not None:
            model.setPropertyValue("BackgroundColor", plain)
        window.dialog.getPeer().invalidate(3)
        time.sleep(0.6)
        image = Image.open(out).convert("L")
        say("dialog peer %dx%d at %d,%d, client at %d,%d   shot %s"
            % (size.Width, size.Height, size.X, size.Y,
               origin[0], origin[1], image.size))
        heights = []
        for name in CONTROLS:
            try:
                place = window.control(name).getPosSize()
            except Exception as error:
                say("  %-20s -> %s: %s" % (name, type(error).__name__, error))
                continue
            box = (origin[0] + place.X, origin[1] + place.Y,
                   origin[0] + place.X + place.Width,
                   origin[1] + place.Y + place.Height)
            rows, tallest = bright_rows(image, box)
            if name.startswith(("label", "Section", "caption")) and not name.startswith(
                    "swatch"):
                heights.append(tallest)
            say("  %-20s %3dx%-3d at %-9s rows %2d  tallest %2d px%s"
                % (name, place.Width, place.Height,
                   "%d,%d" % (place.X, place.Y), rows, tallest,
                   "" if rows else "   <-- NOTHING PAINTED"))
        say("  section rows text %s px  (the menu's letters measure 14 px, "
            "fact 44)" % sorted(set(heights)))
        say("font dropdown: %d names, e.g. %s" % (len(window.fonts),
                                                 window.fonts[:4]))
        saved = window.result()
        say("result(): %s" % dict((key, value) for key, value in saved.items()
                                  if key.startswith("section_")))
    finally:
        window.dispose()
        lo.close(doc)
    say("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
