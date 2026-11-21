#!/usr/bin/env python3
"""What the colour chooser looks like in the states that matter.

The report is that the chooser is ugly.  The office has exactly one way of
showing colours - the *line color* dropdown in the drawing sidebar - so this
opens the chooser as the settings dialog opens it (palettes from disk, the
recently used colours in front of them) and screenshots it

  * open on the standard palette with the recent row,
  * switched to another palette, so the captions move with the list,
  * on the second page of a long palette,
  * with the information box and the confirmation box, which are ours too now.

``scrot`` must run next door (see dev/probe_message_box.py).
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(BASE, "loprofile", "user", "planimpress"))

import dev.lo as lo  # noqa: E402
from plan_impress import palettes, picker  # noqa: E402

SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode")
DEBUG = os.environ.get("PLAN_IMPRESS_DEBUG", "1") != "0"


def log(line):
    if not DEBUG:
        return
    directory = os.path.join(BASE, "out")
    if not os.path.isdir(directory):
        os.makedirs(directory)
    try:
        with open(os.path.join(directory, "probe.log"), "a") as handle:
            handle.write(line.rstrip() + "\n")
    except OSError:
        pass


def shoot(name):
    """Screenshot the whole screen and *wait* for it.

    Spawning scrot detached (the obvious thing to do) makes every shot below
    capture whatever is on the screen when the next action has already started,
    which is how one and the same repaint looked blue in one shot and black in the
    next.
    """
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    time.sleep(0.5)
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (os.path.join(SHOT, name),
                                             os.path.join(SHOT, "scrot.log"))])
    log("shot %s -> %d" % (name, code))


def describe(p):
    """Every control with its rectangle and what it is supposed to show."""
    for name in p.model.ElementNames:
        model = p.model.getByName(name)
        try:
            rect = tuple(int(getattr(model, k)) for k in
                         ("PositionX", "PositionY", "Width", "Height"))
        except Exception as exc:                     # pragma: no cover
            rect = str(exc)
        try:
            shown = model.getPropertyValue("Visible")
        except Exception:
            shown = "-"
        label = ""
        for key in ("Label", "Text"):
            try:
                label = str(getattr(model, key))
                if label:
                    break
            except Exception:
                continue
        try:
            background = "%06X" % int(getattr(model, "BackgroundColor"))
        except Exception:
            background = ""
        log("%-14s %-16s visible=%-5s %-28s %s"
            % (name, label[:16], shown, rect, background))


def swatch_pixels(p, image, title):
    """What the squares are actually painted with, from the screen.

    No property says what a peer rendered (fact 46), and ``BackgroundColor`` is only the
    colour *under* the bitmap, so the line is checked where it exists: the crop of each
    square, how much of it is the colour, how much is the contrast line, and whether
    that line closes on all four sides.  ``dev/probe_swatch_ring.py`` established the
    recipe; this applies it to the real chooser with the office's real palettes.
    """
    import subprocess
    import numpy
    from plan_impress import swatch
    try:
        found = subprocess.run(["xdotool", "search", "--name", title],
                               capture_output=True, text=True, timeout=10).stdout
        win = found.split()[0]
        shell = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win],
                               capture_output=True, text=True, timeout=10).stdout
        values = dict(line.split("=", 1) for line in shell.splitlines() if "=" in line)
        origin = (int(values["X"]), int(values["Y"]))
    except Exception as error:
        log("swatch pixels: no window (%s)" % error)
        return
    log("window %s at %s" % (title, origin))
    print("window %s at %s" % (title, origin))
    names = ["cell%d" % index for index in range(3)] + ["preview"]
    for name in names:
        try:
            model = p.model.getByName(name)
            rect = p.control(name).getPeer().getPosSize()
            colour = int(model.BackgroundColor) & 0xFFFFFF
        except Exception:
            continue
        box = (origin[0] + rect.X, origin[1] + rect.Y,
               origin[0] + rect.X + rect.Width, origin[1] + rect.Y + rect.Height)
        crop = numpy.asarray(image.crop(box)).astype(numpy.int16)
        wanted = {"colour": colour,
                  "line": swatch.ring_colour(colour, p.dark)}
        print("   %-8s %-12s peer %2dx%2d px, drawn at %s"
              % (name, "#%06X" % colour, rect.Width, rect.Height,
                 "its own size" if (colour, rect.Width, rect.Height,
                                    swatch.ring_colour(colour, p.dark),
                                    swatch.RING_WIDTH) in swatch._GRAPHICS
                 else "NOT its own size"))
        for label, value in wanted.items():
            target = numpy.array([(value >> 16) & 255, (value >> 8) & 255,
                                  value & 255], dtype=numpy.int16)
            hits = int((numpy.abs(crop - target).max(axis=2) <= 24).sum())
            print("      %-6s #%06X %4d px of %d" % (label, value, hits,
                                                     crop.shape[0] * crop.shape[1]))


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    log("")
    log("========== picker look ==========")
    recent = [("#112233", 0x112233), ("#2A57D7", 0x2A57D7), ("#00FF00", 0x00FF00)]
    names = palettes.load_palettes()
    if not names:
        print("no palettes on disk")
        return 1
    p = picker.ColourPicker(lo.connect(), names, current=0x1F4E79,
                            title="Heading colour", recent=recent)
    if not p.build():
        print("the chooser would not build")
        return 1
    p.show()                             # peers, listeners, the current page
    log("width %s height %s page size %s recent %s"
        % (picker.DIALOG_WIDTH, p.model.Height, picker.page_size(recent),
           len(p.recent)))
    describe(p)
    shoot("look-1-open.png")
    from PIL import Image
    swatch_pixels(p, Image.open(os.path.join(SHOT, "look-1-open.png")).convert("RGB"),
                  "Heading colour")
    # the twelfth square: 0..2 are the recent colours, 3..9 are the pad of that row
    # (hovering the pad changes nothing, which is worth seeing too), so 11 is the
    # second colour of the palette page
    p._hover(11)
    log("hover 11 -> current %06X, read-out %r"
        % (p.current, p.model.getByName("name").Label))
    time.sleep(0.4)
    shoot("look-2-hover.png")

    # another palette: the captions have to follow the list
    second = names[1][0] if len(names) > 1 else names[0][0]
    p._choose_palette(p.palette_names().index(second))
    time.sleep(0.4)
    log("palette %s cells %s" % (second, p.page_cells()))
    shoot("look-3-palette.png")

    # the second page of the longest palette
    longest = max(names, key=lambda entry: len(entry[1]))
    p._choose_palette(p.palette_names().index(longest[0]))
    p._turn_page(1)
    time.sleep(0.4)
    log("page %s of %s (%s colours)"
        % (p.page + 1, p.pages(), len(longest[1])))
    shoot("look-4-page2.png")
    p.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
