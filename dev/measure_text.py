#!/usr/bin/env python3
"""Compare the settings dialog's text against the Plan menu's text, in pixels.

    DISPLAY=:98 python3 dev/measure_text.py

Opens the fixture deck in the development office, opens the Plan menu, opens the
settings dialog, screenshots both and prints the height of the letters in each.
The report this exists for was "text on the setting pane is smaller than the
menu text", and neither the control models nor their peers say what font they
render with (`dev/debug_font.py` finds no ``FontDescriptor`` on any of them), so
the only honest measurement is of the pixels.

Both numbers are ink heights: the office runs a dark theme, so the letters are
the *bright* pixels and a threshold the other way round would measure the
background and call every row text.  In the menu bands the two tallest entries
are the rows under the mouse, which also paint their highlight and their icon.
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

FIXTURE = os.path.join(ROOT, "tests/fixtures/sections.odp")
MENU_CLICK = (422, 39)                     # "Plan" in the menu bar
BRIGHT = 165
MIN_PIXELS = 3                             # ignore stray antialiased pixels


def say(*args):
    print(*args, flush=True)


def screenshot(path):
    subprocess.run(["scrot", "-o", path], check=True, timeout=30)


def xdo(*args):
    """xdotool, but never waiting forever for a window that is not there."""
    try:
        subprocess.run(["xdotool"] + list(args), check=False, timeout=10)
    except Exception:
        pass


def bright_bands(image, box, threshold=BRIGHT):
    """The bright-pixel bands of a region, as ``(top, bottom, height)``."""
    crop = image.crop(box)
    pixels, stride, height = list(crop.get_flattened_data()), crop.size[0], crop.size[1]
    bands, start = [], None
    for row in range(height):
        lit = sum(1 for p in pixels[row * stride:(row + 1) * stride]
                  if p > threshold) >= MIN_PIXELS
        if lit and start is None:
            start = row
        elif not lit and start is not None:
            bands.append((box[1] + start, box[1] + row - 1, row - start))
            start = None
    if start is not None:
        bands.append((box[1] + start, box[1] + height - 1, height - start))
    return bands


def tallest(image, box):
    """Height of the tallest run of letters in a region.

    The region is searched taller than the control's own rectangle: the dialog's
    peer reports ``Y=0`` at the top of the client area, so the title bar is not
    accounted for and a crop taken straight from the peer geometry lands high.
    """
    bands = bright_bands(image, (box[0], max(box[1] - 40, 0),
                                 box[0] + box[2], box[1] + box[3] + 40))
    return max([height for _top, _bottom, height in bands], default=0)


def main():
    out = os.path.join(ROOT, "out", "compare.png")
    menu_shot = os.path.join(ROOT, "out", "menu-only.png")

    say("connecting...")
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    say("opening %s..." % FIXTURE)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    xdo("search", "--name", "sections.odp", "windowmove", "0", "30")
    xdo("search", "--name", "sections.odp", "windowsize", "1440", "870")
    time.sleep(2.0)

    say("opening the Plan menu...")
    xdo("mousemove", str(MENU_CLICK[0]), str(MENU_CLICK[1]), "click", "1")
    time.sleep(1.2)
    screenshot(menu_shot)
    # a popup left on screen holds the pointer grab and the next dialog then
    # blocks in X, so dismiss it properly: Escape twice and a click on the canvas
    xdo("key", "Escape")
    xdo("key", "Escape")
    xdo("mousemove", "700", "700", "click", "1")
    time.sleep(0.8)

    say("building the settings dialog...")
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x1F6EC8,
                     "title": "Plan du jour", "master": "Master 1"})
    box = dialog.SettingsDialog(ctx, settings, ["Master 1", "Master 2"])
    box.build()
    box._peer()
    box.dialog.setTitle("Plan Impress - Settings")
    box.dialog.setVisible(True)
    time.sleep(1.5)
    screenshot(out)

    dialog_image = Image.open(out).convert("L")
    size = box.dialog.getPosSize()
    print("dialog peer %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
    heights = []
    for name in ("labelMutedColor", "labelTextColor", "labelTitle", "labelMaster",
                 "ok", "cancel"):
        peer = box.control(name).getPosSize()
        height = tallest(dialog_image, (size.X + peer.X, size.Y + peer.Y,
                                       peer.Width, peer.Height))
        heights.append(height)
        print("  %-16s %2dpx ink   at %d,%d %dx%d"
              % (name, height, size.X + peer.X, size.Y + peer.Y,
                 peer.Width, peer.Height))
    menu_image = Image.open(menu_shot).convert("L")
    # 470: past the icon column of the popup; 58: below the menu bar
    menu_heights = [height for _top, _bottom, height
                    in bright_bands(menu_image, (470, 58, 720, 230))]
    print("  dialog text %s px  vs  menu text %s px"
          % (sorted(set(heights)), sorted(set(menu_heights))))
    box.dispose()
    lo.close(doc)
    print("wrote %s and %s" % (out, menu_shot))


if __name__ == "__main__":
    main()
