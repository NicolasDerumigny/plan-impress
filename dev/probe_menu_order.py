"""Print the rows of the *Plan* menu as the office really draws them (debug).

    DISPLAY=:98 python3 dev/probe_menu_order.py

``Addons.xcu`` lists the submenu items in the order they are meant to appear - but the
office does not hand those children back in that order (fact 98), so the only witness
for "*Toggle Debug Log* is the last row and a separator is in front of it" is the popup
itself.  Two things had to be measured before the rows could be counted, and both are
why this probe looks the way it does:

* comparing a screenshot of the desktop with the menu closed against one with it open
  is **not** a way to find the popup.  Over the toolbar the popup's own background is
  the colour that was already there, so the difference breaks a run of items in the
  middle and merges two rows into one 95-pixel band (measured here, twice).  The popup
  is instead found as the *window* that appears between the two shots:
  ``xdotool search --maxdepth 1 --onlyvisible`` lists it as a top-level of its own
  (measured: 215x184 at 402,57 for six items), and inside it the background is uniform,
  which is what makes a row measurable at all.
* a separator cannot be found by its line, because in this theme it has none: every row
  of the gap between two entries is the popup's own ``#383C4A`` at the very bottom of
  this file's profile dump.  What a separator does leave behind is **air** - the pitch
  between two rows of letters jumps by about 5 px where one sits.  So the rows are
  counted, the pitch between them measured, and the positions with extra air compared
  with the separator positions ``Addons.xcu`` asks for.

The click takes a pointer grab (fact 97): the popup is dismissed again in a
``finally``, or every later client of the office hangs.
"""
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PIL import Image  # noqa: E402

import lo  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests/fixtures/sections.odp")
MENU_CLICK = (422, 39)          # "Plan" in the menu bar, as measure_text.py
OUT = os.path.join(ROOT, "out")
SHOTS = (os.path.join(OUT, "menu-closed.png"), os.path.join(OUT, "menu-open.png"))
DISTINCT = 24                   # how far a pixel must move to count as ink
LINE = 0.6                      # a run over this share of the width is a drawn line
AIR = 4                         # px of extra pitch that say a separator sits here
ICON_COLUMN = 26                # px at the left: an item with an icon has ink there


def say(text):
    print(text, flush=True)


def xdo(*args):
    """xdotool, but never waiting forever for a window that is not there."""
    try:
        done = subprocess.run(["xdotool"] + list(args), capture_output=True,
                              text=True, timeout=15)
        return (done.stdout or "") + (done.stderr or "")
    except Exception:
        return ""


def windows():
    """``{id: (x, y, width, height)}`` of every visible top-level window."""
    out = xdo("search", "--maxdepth", "1", "--onlyvisible", "",
              "getwindowgeometry", "%@")
    found, ident, position = {}, None, [0, 0]
    for line in out.splitlines():
        match = re.match(r"Window (\d+)", line.strip())
        if match:
            ident = match.group(1)
            continue
        match = re.search(r"Position: (-?\d+),(-?\d+)", line)
        if match and ident:
            position = [int(match.group(1)), int(match.group(2))]
        match = re.search(r"Geometry: (\d+)x(\d+)", line)
        if match and ident:
            found[ident] = tuple(position) + (int(match.group(1)), int(match.group(2)))
    return found


def dismiss():
    """Two escapes and a click on the canvas: a menu left open wedges the office."""
    for _ in range(2):
        xdo("key", "Escape")
        time.sleep(0.3)
    xdo("mousemove", "700", "600", "click", "1")
    time.sleep(0.3)


def shoot(name):
    """Synchronous: scrot has to have written the file before it is measured."""
    subprocess.call(["scrot", "-o", name])
    return Image.open(name).convert("RGB")


def background(pixels):
    """The colour the popup paints behind everything: the most common one."""
    seen = {}
    for colour in pixels:
        seen[colour] = seen.get(colour, 0) + 1
    return max(seen, key=seen.get)


def rows(image, box):
    """Per row: ``(ink, longest_run, first_inked_column)``, all at ``DISTINCT``."""
    crop = image.crop(box)
    width, height = crop.size
    pixels = list(crop.getdata())                # one (red, green, blue) per pixel
    base = background(pixels)
    profile = []
    for row in range(height):
        longest = run = ink = first = 0
        for column, colour in enumerate(pixels[row * width:(row + 1) * width]):
            differs = max(abs(colour[0] - base[0]), abs(colour[1] - base[1]),
                          abs(colour[2] - base[2])) > DISTINCT
            run = run + 1 if differs else 0
            longest = max(longest, run)
            if differs:
                ink += 1
                if not first:
                    first = column
        profile.append((ink, longest, first))
    return profile, base


def bands(profile):
    """Group the rows that carry ink into bands: ``[(first, last, ink, run, left)]``."""
    found, start = [], None
    for row, (ink, run, first) in enumerate(profile):
        if ink:
            if start is None:
                start = row
                found.append([start, row, ink, run, first])
            elif found[-1][1] == row - 1:
                found[-1][1] = row
                found[-1][2] += ink
                found[-1][3] = max(found[-1][3], run)
                found[-1][4] = min(found[-1][4], first)
            else:                                # dead air between two entries
                found.append([start, row, ink, run, first])
                start = row
        else:
            start = None
    return [tuple(band) for band in found]


def wanted_separator_rows():
    """Which rows the file asks a separator in front of, counted over the items.

    Read out of ``src/Addons.xcu`` itself, because comparing the pixels with nothing
    only says "there is air there"; the question is whether it is where the file asked.
    Only the items of the one ``Submenu`` count: the ``Images`` nodes carry the very
    same ``URL`` properties, and counting those called this deck 11 items.
    """
    import xml.etree.ElementTree as ET
    oor = "{http://openoffice.org/2001/registry}"
    tree = ET.parse(os.path.join(ROOT, "src", "Addons.xcu"))
    rows, items = [], 0
    for submenu in tree.iter("node"):
        if submenu.get(oor + "name") != "Submenu":
            continue
        for node in submenu:
            props = dict((prop.get(oor + "name"), prop.find("value"))
                         for prop in node.findall("prop"))
            value = props.get("URL")
            url = str(value.text) if value is not None else ""
            if url == "private:separator":
                rows.append(items + 1)           # in front of the next item
            elif url.startswith("service:org.devsys.planimpress."):
                items += 1
    return rows, items


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        doc.CurrentController.setCurrentPage(doc.DrawPages.getByIndex(0))
        # the menu bar is only where MENU_CLICK is when the deck's window sits where
        # measure_text.py put it; without this the click lands on nothing
        xdo("search", "--name", "sections.odp", "windowmove", "0", "30")
        xdo("search", "--name", "sections.odp", "windowsize", "1440", "870")
        time.sleep(2.0)
        before = windows()
        closed = shoot(SHOTS[0])                                   # noqa: F841
        xdo("mousemove", str(MENU_CLICK[0]), str(MENU_CLICK[1]), "click", "1")
        time.sleep(1.2)
        new = [window for window in windows().items() if window[0] not in before]
        try:
            opened = shoot(SHOTS[1])
        finally:
            dismiss()                            # fact 97
        if not new:
            raise AssertionError("no new window appeared: the click opened no menu")
        (ident, (left, top, width, height)), = new
        say("the popup is window %s: %dx%d at %d,%d" % (ident, width, height,
                                                        left, top))
        profile, base = rows(opened, (left, top, left + width, top + height))
        found = bands(profile)
        lines = [band for band in found if band[3] >= LINE * width]
        items = [band for band in found if band[3] < LINE * width]
        say("popup background #%02X%02X%02X   %d bands, %d of them a drawn line"
            % (base[0], base[1], base[2], len(found), len(lines)))
        pitches = [items[index][0] - items[index - 1][0]
                   for index in range(1, len(items))]
        tight = min(pitches) if pitches else 0
        say("%d rows of letters, %d px pitch -> %d rows' worth of air in %d px"
            % (len(items), tight, sum(p - tight for p in pitches) // max(AIR, 1),
               height))
        separators = []
        for number, (first, last, ink, longest, left) in enumerate(items):
            if number:
                pitch = first - items[number - 1][0]
                if pitch - tight >= AIR:
                    separators.append(number + 1)
            # the leftmost ink of a row: an icon would sit at x < ICON_COLUMN, and here
            # every row starts at x=30, which is where the words start - this office
            # draws no icons in a popup menu at all, so an icon cannot tell the rows
            # apart and the pitch has to carry the whole argument
            say("  %d  y %3d..%-3d  %2d px tall  ink %5d  longest run %4d  ink from "
                "x=%-3d %s"
                % (number + 1, first, last, last - first + 1, ink, longest, left,
                   "icon" if left < ICON_COLUMN else "text"))
        asked, count = wanted_separator_rows()
        say("the file asks for %d items and separators in front of rows %s; the "
            "office puts air in front of rows %s -> %s"
            % (count, asked, separators,
               "MATCHES" if separators == asked else "DOES NOT MATCH"))
        say("screenshots: %s and %s" % SHOTS)
    finally:
        lo.close(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
