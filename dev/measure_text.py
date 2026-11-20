#!/usr/bin/env python3
"""Compare the settings dialog's text against the Plan menu's text, in pixels.

    DISPLAY=:98 python3 dev/measure_text.py compare

Opens the fixture deck in the development office, opens the Plan menu, opens the
settings dialog, screenshots both, and prints the ink height (bright pixels on
this dark theme) of a menu item and of a dialog label.  Those two numbers being
unequal is the report being fixed; the script is how the fix is checked.
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
BRIGHT = 165


def ink(image, x, y, w, h, threshold=BRIGHT):
    """Height of the band of bright pixels inside a rectangle."""
    crop = image.crop((x, y, x + w, y + h))
    pixels, stride, height = list(crop.get_flattened_data()), crop.size[0], crop.size[1]
    rows = [r for r in range(height)
            if sum(1 for p in pixels[r * stride:(r + 1) * stride] if p > threshold) >= 3]
    return (rows[-1] - rows[0] + 1, rows[0] + y, rows[-1] + y) if rows else (0, 0, 0)


def click(x, y):
    subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"],
                   check=True, timeout=15)
    time.sleep(1.2)


def xdo(*args):
    """xdotool, but never waiting forever for a window that is not there."""
    try:
        subprocess.run(["xdotool"] + list(args), check=False, timeout=10)
    except Exception:
        pass


def main():
    out = os.path.join(ROOT, "out", "compare.png")
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    xdo("search", "--name", "sections.odp", "windowmove", "0", "30")
    xdo("search", "--name", "sections.odp", "windowsize", "1440", "870")
    time.sleep(2.0)

    click(422, 39)                       # the Plan menu
    subprocess.run(["scrot", "-o", os.path.join(ROOT, "out", "menu-only.png")], check=True)
    subprocess.run(["xdotool", "key", "Escape"], check=False)
    time.sleep(0.6)

    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x1F6EC8,
                     "title": "Plan du jour", "master": "Master 1"})
    box = dialog.SettingsDialog(ctx, settings, ["Master 1", "Master 2"])
    box.build()
    box._peer()
    box.dialog.setTitle("Plan Impress - Settings")
    box.dialog.setVisible(True)
    time.sleep(1.5)
    subprocess.run(["scrot", "-o", out], check=True)

    image = Image.open(out).convert("L")
    size = box.dialog.getPosSize()
    print("dialog peer %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
    for label, box_name in (("label 1", "labelMutedColor"), ("label 2", "labelTextColor"),
                            ("label 3", "labelTitle"), ("label 4", "labelMaster")):
        peer = box.control(box_name).getPosSize()
        print("  %-8s %s  model %d,%d %dx%d"
              % (label, ink(image, size.X + peer.X, size.Y + peer.Y,
                            max(peer.Width, 150), max(peer.Height, 30)),
                 peer.X, peer.Y, peer.Width, peer.Height))
    menu = Image.open(os.path.join(ROOT, "out", "menu-only.png")).convert("L")
    crop = menu.crop((400, 50, 640, 230))
    pixels, stride, height = list(crop.get_flattened_data()), crop.size[0], crop.size[1]
    bright = [any(p > BRIGHT for p in pixels[r * stride:(r + 1) * stride])
              for r in range(height)]
    bands, start = [], None
    for row in range(height):
        if bright[row] and start is None:
            start = row
        elif not bright[row] and start is not None:
            bands.append((50 + start, 50 + row - 1, row - start))
            start = None
    print("  menu text bands (top, bottom, height): %s" % bands)
    box.dispose()
    lo.close(doc)
    print("wrote %s" % out)


if __name__ == "__main__":
    main()
