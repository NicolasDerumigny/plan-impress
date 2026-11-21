"""How a colour is painted so it still reads as a square on any theme.

The office's own line-colour dropdown draws every swatch as a flat colour with a
**thin line of the contrast colour** round it - light on a dark theme, dark on a light
one - so black and white both read as squares.  Neither of the two ways the AWT
toolkit offers can do that:

* ``BackgroundColor`` on a label paints the colour flat but the line it draws is the
  theme's own: every ``BorderStyle`` value from 0 to 6 paints ``#2B2E39`` on this dark
  theme and ``BorderColor`` is accepted and ignored in all of them, 0 red pixels out of
  180 (``dev/probe_border_colour.py``, fact 78).  A black square therefore has no edge
  at all;
* a button paints a bevel instead of a line - the "perspective-style border" that was
  reported (fact 77).

So the line is **drawn**: each swatch is an ``UnoControlImageControlModel`` carrying a
PNG built here - the colour inside a one-pixel ring of the contrast colour - which is
what ``dev/probe_swatch_ring.py`` and ``dev/probe_swatch_stream.py`` measured:
``Graphic`` takes an ``XGraphic``, it can be replaced after the peer exists (that is a
palette switch), the control answers ``mouseReleased`` and ``mouseEntered`` like a
label does, and ``ScaleMode`` 2 stretches the bitmap over the control so its pixel size
only decides how thick the ring ends up.

The PNG is written with ``zlib`` and ``struct`` because the extension runs inside
LibreOffice's own Python, which has no imaging library; the bytes go to the graphic
provider through a ``Pipe`` because the model has no ``ImageData``, and a ``bytes``
object or an unsigned tuple is refused there ("VALUE is out of range") while the signed
spelling of ``sequence<octet>`` is taken.
"""

import os
import struct
import zlib

from plan_impress import config

#: The line round a swatch, in pixels: as thin as the office's own.
RING_WIDTH = 1
#: The line's colour when the theme is dark, and when it is light.  The report was
#: "look how the default palette colours are drawn, with a thin white border on a dark
#: theme, and think dark border and a white theme".
RING_ON_DARK = 0xF2F2F2
RING_ON_LIGHT = 0x4D4D4D
#: The brightness at or under which a colour counts as dark, when the theme is unknown
#: and the line has to be chosen against the swatch itself (:func:`ring_colour`).
DARK_CUT = 0x80

#: A dialog unit is 2.53 px across and 2.39 px down (AGENTS.md facts 28 and 64), which
#: is what turns a cell's rectangle into the pixel size to draw its bitmap at - the
#: ring is one pixel of the bitmap, so the bitmap wants to be the size it is shown at.
PX_PER_UNIT_X = 2.53
PX_PER_UNIT_Y = 2.39


def square_units(width):
    """The height, in dialog units, that paints a ``width``-unit square *square*.

    A unit is 2.53 px across and 2.39 px down, so equal units are not equal pixels and
    a control that is a square in the model is a rectangle on the screen: 9 x 7 units,
    the cell this used, comes back 23 x 17 px ("the color sample must be exact squares,
    not rectangles").  ``dev/probe_picker_ink.py`` paints candidate pairs and
    photographs them - 13 x 14 units is 33 x 33 px, the smallest pair that is the same
    both ways and still the size of the office's own swatches.

    Every colour this extension shows - a square of the chooser's grid, the chip under
    it, the swatch beside a hex field in the settings dialog - is sized with this, so
    they are all the same square and none of them is a strip.
    """
    return int(round(int(width) * PX_PER_UNIT_X / PX_PER_UNIT_Y))

#: ``ScaleMode`` that stretches the bitmap over the whole control.  Measured on a 4 x 3
#: bitmap in a 28 x 19 px control: 0 draws it at its natural size with the control's
#: background round it, 1 keeps the aspect ratio and leaves the sides empty, 2 fills
#: the control, 3 and 4 paint nothing at all (``dev/probe_swatch_ring3.py``).
SCALE_MODE_FILL = 2

#: The environment's way of saying what the office will not: ``dark`` or ``light``.
#: The ``dev/`` scripts need it, and so does a test.
THEME_VARIABLE = "PLAN_IMPRESS_THEME"

#: Substrings a theme's name has to contain to count as dark: the theme names people
#: actually have (``Arc-Dark``, ``Adwaita-dark``, ``Breeze Dark``) and the ones the
#: environment variables carry.
_DARK_WORDS = ("dark", "night", "highcontrast")
_TRUE_WORDS = ("true", "1", "yes")

#: Where a desktop tells the office how dark it is.  These are the files LibreOffice
#: itself reads when ``ApplicationAppearance`` says *follow the system*, and they are
#: what decides on this machine: ``dev/probe_theme.py`` prints them next to the colour
#: the dialogs are actually painted in - ``#383C4A`` here, with
#: ``gtk-application-prefer-dark-theme=1`` and ``gtk-theme-name=Arc-Dark``.
_THEME_FILES = (
    os.path.join(".config", "gtk-3.0", "settings.ini"),
    ".gtkrc-2.0",
    os.path.join(".config", "kdeglobals"),
)

#: The graphics already built, by what they look like: a palette switch asks for the
#: same 60 squares again, and a ``freecolour-hlc`` has 240 colours to draw.
_GRAPHICS = {}
_GRAPHICS_LIMIT = 900


def png_bytes(width, height, fill, ring=None, ring_width=RING_WIDTH):
    """The bytes of a ``width`` x ``height`` PNG: ``fill`` inside a ``ring``.

    ``ring`` is drawn ``ring_width`` pixels deep on all four sides, and ``None`` paints
    a flat square.  Only ``zlib`` and ``struct``, for the reason in the module
    docstring: this runs inside LibreOffice's Python.
    """
    width, height = max(1, int(width)), max(1, int(height))
    depth = max(0, int(ring_width)) if ring is not None else 0

    def pixel(x, y):
        if ring is None:
            return fill
        if (depth <= x < width - depth and depth <= y < height - depth):
            return fill
        return ring

    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    def rgb(value):
        return bytes(((value >> 16) & 255, (value >> 8) & 255, value & 255))

    # one filter byte per *row*, then three bytes per pixel: the format is strict
    # enough that a row started wrong is a picture of nothing
    raw = b"".join(b"\x00" + b"".join(rgb(pixel(x, y)) for x in range(width))
                   for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def swatch_props(colour):
    """The properties that make a control paint ``colour`` as a flat square.

    A square of the picker's grid, the chip under it and the swatch beside a hex field
    in the settings dialog are all ``UnoControlImageControlModel`` carrying a bitmap
    :func:`graphic` draws - not a button, which the office paints with its theme's
    raised bevel (the "perspective-style border" that was reported, AGENTS.md fact 77),
    and not a coloured label, which can be given a line only in the theme's own colour:
    ``BorderColor`` is ignored in every ``BorderStyle`` there is, so a dark colour on a
    dark dialog had no edge at all (``dev/probe_border_colour.py``, fact 78).

    What belongs here, rather than in the bitmap, is that the bitmap covers the whole
    square - ``ScaleMode``, where 0 leaves the control's own colour round it and 3
    paints nothing at all (``dev/probe_swatch_ring3.py``); that there is no office
    border to fight the drawn one with; that a swatch cannot be tabbed to, which is how
    the grid stayed out of the keyboard route; and that the hex value travels with the
    control in ``Tag``, because nothing on a peer says what it painted (fact 46) and a
    test, a tooltip and a log line all want to know which colour a square stands for.

    ``BackgroundColor`` is the colour as well: it is what shows if the bitmap cannot be
    made at all, and an old-fashioned flat square is a better failure than a hole.
    """
    return [
        ("BackgroundColor", int(colour) & 0xFFFFFF),
        ("Border", 0),
        ("ScaleMode", SCALE_MODE_FILL),
        ("Tabstop", False),
        ("Tag", config.color_to_hex(colour)),
    ]


def luminance(colour):
    """How light ``colour`` looks, 0..255 (the Rec. 601 weights, as integers)."""
    return (77 * ((colour >> 16) & 255) + 150 * ((colour >> 8) & 255)
            + 29 * (colour & 255)) >> 8


def ring_colour(colour, dark=None):
    """The colour of the line to draw round ``colour``.

    ``dark`` is what :func:`theme_is_dark` answers.  On a known theme every swatch gets
    the same line, which is how the office's own dropdown looks.  When nothing says
    which theme it is the line is chosen against the **swatch**: a dark colour gets the
    light line and a light colour the dark one.  That is the case the report was about -
    a black square on a dark dialog had no edge at all - and it cannot make things
    worse, because a colour that already stands out from its background keeps doing so.
    """
    if dark is None:
        dark = luminance(colour) < DARK_CUT
    return RING_ON_DARK if dark else RING_ON_LIGHT


def theme_is_dark(ctx=None, environ=None, home=None):
    """``True`` on a dark theme, ``False`` on a light one, ``None`` when nothing says.

    Nothing in the API answers the question, which is the first thing to know: the
    toolkit proxy has no ``getSettings`` and does not answer ``XStyleFacility``
    (nothing about a peer ever says how it renders - fact 46), and of the
    configuration nodes ``/org.openoffice.Office.Common/Theme`` and ``/VCL/Properties``
    raise ``RuntimeException`` while ``/Appearance`` only holds
    ``ApplicationAppearance = 0`` and ``LibreOfficeTheme = 0`` on this **dark** office
    - both are its "follow the system" value, and no enum in
    ``program/types/offapi.rdb`` says which number is the dark one
    (``dev/probe_border_colour.py``, ``dev/probe_theme.py``).  So the system is asked,
    exactly as the office itself does when it is told to follow it.

    ``environ`` and ``home`` are there for the tests: the environment to read and the
    home directory to look in.  ``ctx`` is unused for now and kept because every other
    entry point in the extension takes one.
    """
    environ = os.environ if environ is None else environ
    said = (environ.get(THEME_VARIABLE) or "").strip().lower()
    if said == "dark":
        return True
    if said == "light":
        return False
    for name in ("GTK_THEME", "QT_QPA_PLATFORMTHEME", "XDG_CURRENT_DESKTOP"):
        value = (environ.get(name) or "").lower()
        if any(word in value for word in _DARK_WORDS):
            return True
    home = os.path.expanduser("~") if home is None else home
    answers = []
    for relative in _THEME_FILES:
        verdict = _file_says_dark(os.path.join(home, relative))
        if verdict is not None:
            answers.append(verdict)
    if not answers:
        return None
    return True in answers


def _file_says_dark(path):
    """Whether one desktop settings file asks for a dark theme, ``None`` if unreadable."""
    try:
        with open(path) as handle:
            lines = handle.read().splitlines()
    except (IOError, OSError):
        return None
    for line in lines:
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower().replace("-", "").replace("_", "")
        value = value.strip().strip("'\"").lower()
        if key == "gtkapplicationpreferdarktheme" and value in _TRUE_WORDS:
            return True
        if key in ("gtkthemename", "kthemename", "colorscheme", "widgetstyle") \
                and any(word in value for word in _DARK_WORDS):
            return True
        if key == "contrast" and "high" in value:
            return True
    return False


def bitmap_size(width, height):
    """The pixel size to draw a ``width`` x ``height`` dialog-unit swatch at.

    The ring is one pixel *of the bitmap*, so the bitmap wants the size the control is
    painted at; :func:`graphic` callers pass the control's own peer size when they know
    it and this otherwise, which is right for the normal 96 dpi and a little thick
    everywhere else - ``ScaleMode`` 2 stretches whatever is given over the control, so
    the worst case is a two-pixel line, never an empty square.
    """
    return (max(3, int(round(int(width) * PX_PER_UNIT_X))),
            max(3, int(round(int(height) * PX_PER_UNIT_Y))))


def graphic(ctx, colour, width, height, ring=None, ring_width=RING_WIDTH):
    """An ``XGraphic`` of ``colour`` inside a ``ring``, or ``None`` if it cannot be made.

    Cached by what it looks like: a palette switch asks for the same squares again, and
    60 cells x two groups over a dozen pages of a 240-colour palette is a lot of
    identical PNGs.  ``None`` is returned rather than raised - the caller paints the
    colour as a plain background instead, which is the old look, and a picker that
    cannot draw a ring must still be a picker.
    """
    colour = int(colour) & 0xFFFFFF
    ring = None if ring is None else int(ring) & 0xFFFFFF
    key = (colour, int(width), int(height), ring, int(ring_width))
    made = _GRAPHICS.get(key)
    if made is not None:
        return made
    try:
        from com.sun.star.beans import PropertyValue
        manager = ctx.ServiceManager
        provider = manager.createInstanceWithContext(
            "com.sun.star.graphic.GraphicProvider", ctx)
        pipe = manager.createInstanceWithContext("com.sun.star.io.Pipe", ctx)
        payload = png_bytes(width, height, colour, ring, ring_width)
        # sequence<octet> is signed: the unsigned spelling is refused with
        # "VALUE is out of range" (dev/probe_swatch_stream.py)
        pipe.writeBytes(tuple(byte - 256 if byte > 127 else byte
                              for byte in payload))
        pipe.closeOutput()
        argument = PropertyValue()
        argument.Name = "InputStream"
        argument.Value = pipe
        made = provider.queryGraphic((argument,))
    except Exception:
        return None
    if made is None:
        return None
    if len(_GRAPHICS) > _GRAPHICS_LIMIT:
        _GRAPHICS.clear()
    _GRAPHICS[key] = made
    return made
