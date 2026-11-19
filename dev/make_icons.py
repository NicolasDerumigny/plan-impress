#!/usr/bin/env python3
"""Regenerate the menu icons (dev/make_icons.py).

Kept as a script so the committed PNGs are reproducible:

    python3 dev/make_icons.py
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "icons")

INK = (60, 60, 60, 255)
MUTED = (176, 176, 176, 255)
ACCENT = (30, 110, 200, 255)
WHITE = (255, 255, 255, 255)


def _canvas(size):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _slide(draw, size, margin=None):
    """White slide with a dark border, the shared frame of every icon."""
    margin = margin if margin is not None else max(1, size // 16)
    box = [margin, margin, size - margin - 1, size - margin - 1]
    draw.rounded_rectangle(box, radius=max(1, size // 12), fill=WHITE, outline=INK,
                           width=max(1, size // 16))
    return box


def _lines(draw, box, highlight, size):
    """Three list rows inside the slide, one of them in the accent colour."""
    left = box[0] + max(2, (box[2] - box[0]) // 6)
    right = box[2] - max(2, (box[2] - box[0]) // 6)
    top = box[1] + max(2, (box[3] - box[1]) // 5)
    bottom = box[3] - max(1, (box[3] - box[1]) // 6)
    rows = 3
    step = (bottom - top) / rows
    thickness = max(1, size // 8)
    for row in range(rows):
        y = int(top + step * row + step / 2)
        colour = ACCENT if row == highlight else MUTED
        draw.line([(left, y), (right, y)], fill=colour, width=thickness)


def plan_icon(size, highlight=1):
    image, draw = _canvas(size)
    box = _slide(draw, size)
    _lines(draw, box, highlight, size)
    return image


def overview_icon(size):
    image, draw = _canvas(size)
    box = _slide(draw, size)
    _lines(draw, box, -1, size)  # nothing highlighted: the overview
    return image


def remove_icon(size):
    image, draw = _canvas(size)
    box = _slide(draw, size)
    _lines(draw, box, -1, size)
    pad = max(2, size // 5)
    draw.line([(pad, pad), (size - pad - 1, size - pad - 1)], fill=(200, 40, 40, 255),
              width=max(2, size // 8))
    draw.line([(size - pad - 1, pad), (pad, size - pad - 1)],
              fill=(200, 40, 40, 255), width=max(2, size // 8))
    return image


def settings_icon(size):
    image, draw = _canvas(size)
    box = _slide(draw, size)
    _lines(draw, box, 0, size)
    knob = max(2, size // 5)
    draw.ellipse([box[2] - knob - 1, box[3] - knob - 1, box[2] - 1, box[3] - 1],
                 fill=ACCENT, outline=INK)
    return image


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (16, 26):
        for name, factory in (("plan", plan_icon), ("overview", overview_icon),
                              ("remove", remove_icon), ("settings", settings_icon)):
            path = os.path.join(OUT, "%s_%d.png" % (name, size))
            factory(size).save(path)
            print("wrote", path)


if __name__ == "__main__":
    main()
