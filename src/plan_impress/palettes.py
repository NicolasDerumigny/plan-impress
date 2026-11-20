"""The colour palettes the picker offers.

LibreOffice keeps the palettes its colour dropdowns show as XML files in
``<installation>/share/palette/*.soc`` - ``standard.soc``, ``material.soc``,
``html.soc`` and the rest - and a user's own edits in the same-named files under
``<profile>/user/config/``.  Reading them is the only way an extension sees the
same list the office does: nothing in the UNO API exposes it.  There is no
colour picker service either (``ColorPicker``, ``ColorBox`` and
``ColorPickerDialog`` are absent from ``program/types/offapi.rdb``, and the
``ColorListBox`` string there is an Object Inspector enum literal, not a
control), so both the list and the widget are ours.

Colours are plain ``int`` RGB, the same convention the rest of the extension
uses; :mod:`plan_impress.config` converts to and from the hex strings the
settings file holds.
"""

import glob
import os
import re
import xml.etree.ElementTree as ElementTree

#: A palette with more entries than this is truncated: ``freecolour-hlc.soc``
#: has 1032 of them, which no one scrolls through to find a heading colour.
MAX_ENTRIES = 240

#: Palettes worth showing even when the office has more; the rest follow.
PREFERRED_ORDER = ("standard", "libreoffice", "material", "tonal", "html",
                   "chart-palettes", "compatibility")

_COLOR_ELEMENT = re.compile(r"<draw:color\b", re.IGNORECASE)
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def installation_root():
    """Where LibreOffice is installed, or None when it cannot be found.

    Inside the office, ``uno.getComponentContext().getEnvironment()`` names the
    program directory; outside it (tests, ``dev/`` scripts) the environment
    variable and the usual prefix have to do.
    """
    for candidate in (_from_uno(), os.environ.get("LIBREOFFICE_PROGRAM"),
                      "/usr/lib/libreoffice/program", "/usr/lib64/libreoffice/program"):
        if candidate and os.path.isdir(candidate):
            return os.path.dirname(os.path.normpath(candidate))
    return None


def _from_uno():
    try:
        import uno
        environment = uno.getComponentContext().getEnvironment()
    except Exception:
        return None
    for key in ("ure.bootscript.filename", "UNO_LC_PATH", "UserInstallation"):
        value = environment.get(key) if hasattr(environment, "get") else None
        if value:
            path = os.path.normpath(str(value))
            for _ in range(4):
                if os.path.isdir(os.path.join(path, "program")):
                    return path
                path = os.path.dirname(path)
    return None


def palette_directories(ctx=None):
    """Directories holding ``.soc`` colour tables, most significant first.

    The user's own ``<profile>/user/config`` comes first so an edited palette
    replaces the shipped one rather than appearing twice.
    """
    from plan_impress import config
    found = []
    user = config.user_profile(ctx) if ctx is not None else None
    if user:
        found.append(os.path.join(user, "config"))
    root = installation_root()
    if root:
        found.append(os.path.join(root, "share", "palette"))
    return [path for path in found if os.path.isdir(path)]


def _attribute(element, local_name):
    """The value of an attribute by local name, whatever namespace it is in.

    The shipped tables do not agree: ``standard.soc`` and ``tonal.soc`` use the
    old ``http://openoffice.org/2000/drawing`` namespace while ``libreoffice.soc``
    uses the OASIS one, so asking for a fixed ``{uri}color`` silently returns
    nothing for half the palettes - and a palette that "has no colours" simply
    never appears in the picker, which is the kind of bug only the user notices.
    """
    for key, value in element.attrib.items():
        if key.rsplit("}", 1)[-1] == local_name:
            return value
    return None


def parse_colour_table(text, fallback=""):
    """Read one ``.soc`` document: ``(palette name, [(colour name, rgb), ...])``.

    Deliberately tolerant: an unparseable colour is skipped rather than
    throwing away the palette, and both ``#rgb`` and ``#rrggbb`` spellings are
    accepted because both appear in the shipped files.
    """
    name = fallback
    colours = []
    try:
        tree = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return name, colours
    for element in tree.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "color-table":
            name = _attribute(element, "name") or name
        elif tag == "color":
            colour = hex_to_rgb((_attribute(element, "color") or "").strip())
            if colour is None:
                continue
            label = (_attribute(element, "name") or "").strip()
            colours.append((label or "%06X" % colour, colour))
    return name, colours


def hex_to_rgb(value):
    """``"#aabbcc"`` or ``"#abc"`` as an int, or None if it is not a colour."""
    if not _HEX.match(value or ""):
        return None
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return int(digits, 16)


def read_soc(path):
    """One ``.soc`` file from disk; ``(name, [])`` when it cannot be read."""
    fallback = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8", "replace")
    except (IOError, OSError):
        return fallback, []
    name, colours = parse_colour_table(text, fallback)
    return (name or fallback), colours[:MAX_ENTRIES]


def load_palettes(ctx=None, directories=None):
    """The available palettes as ``[(palette name, [(colour name, rgb), ...])]``.

    ``standard`` first, then the well-known ones in the order the office lists
    them, then anything else found, so the picker's dropdown is stable even when
    a user drops an extra table into their profile.
    """
    directories = directories if directories is not None else palette_directories(ctx)
    by_name = {}
    for directory in directories:
        for path in sorted(glob.glob(os.path.join(directory, "*.soc"))):
            name, colours = read_soc(path)
            # setdefault, not assignment: the first directory is the user's, and
            # an assignment here let the shipped file overwrite the palette the
            # user had edited - the opposite of what a user expects
            if colours:
                by_name.setdefault(name.lower(), (name, colours))
    ordered = []
    for name in PREFERRED_ORDER:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(by_name[key] for key in sorted(by_name))
    return ordered


def deck_palette(doc, limit=MAX_ENTRIES):
    """The colours this presentation paints with, most used first.

    A plan slide should look like the deck (the rest of the extension works
    that way), so the deck's own palette is offered first-class rather than
    asking the user to read hex values off a slide.
    """
    tally = {}
    for index in range(doc.DrawPages.Count):
        _collect(doc.DrawPages.getByIndex(index), tally)
    for index in range(doc.MasterPages.Count):
        _collect(doc.MasterPages.getByIndex(index), tally)
    ranked = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
    # the same (name, colour) shape the .soc palettes have: the picker
    # unpacks every entry, so a bare int here shows up as a TypeError in a
    # listener, where the office swallows it and the swatch looks dead
    return [("In this presentation",
             [("%06X" % colour, colour) for colour, _count in ranked[:limit]])]


#: The properties that say what a shape paints with.  ``CharHighlight`` is in
#: there because a deck can underline a heading with it instead of colouring it.
COLOUR_PROPERTIES = ("FillColor", "LineColor", "CharColor", "CharHighlight",
                     "BackColor", "ShadowColor")


def _collect(page, tally, depth=0):
    """Every colour on a page, counting repeats so the common ones sort first."""
    for index in range(page.Count):
        _collect_shape(page.getByIndex(index), tally, depth)


def _collect_shape(shape, tally, depth):
    if depth > 6:
        return
    try:
        grouped = shape.supportsService("com.sun.star.drawing.ShapeGroup")
    except Exception:
        grouped = False
    if grouped:
        for index in range(shape.Count):
            _collect_shape(shape.getByIndex(index), tally, depth + 1)
        return
    for property_name in COLOUR_PROPERTIES:
        try:
            value = shape.getPropertyValue(property_name)
        except Exception:
            continue
        if isinstance(value, int) and 0 <= value <= 0xFFFFFF:
            tally[value] = tally.get(value, 0) + 1


def recent_palette(settings, limit=14):
    """The colours picked recently, newest first, as a palette of its own."""
    recent = settings.get("recent_colors") or []
    colours = []
    seen = set()                       # the entries are pairs now, so compare ints
    for value in recent[:limit]:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        value &= 0xFFFFFF
        if value in seen:
            continue
        seen.add(value)
        colours.append(("%06X" % value, value))
    return [("Recently used", colours)] if colours else []
