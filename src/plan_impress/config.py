"""Persistent settings for Plan Impress.

Stored as plain JSON in the user profile (``<profile>/user/planimpress/
settings.json``).  A file was chosen over the LibreOffice configuration
registry because an extension cannot declare writable configuration items
without shipping a schema, and the JSON file is trivial to inspect and edit
by hand when debugging.
"""

import json
import os

#: Muted (greyed-out) colour for the sections that are not the current one.
DEFAULT_MUTED_COLOR = 0xB0B0B0
#: Colour of the section that *is* the current one.
DEFAULT_TEXT_COLOR = 0x000000
#: Heading of the generated slides.
DEFAULT_TITLE = "Plan"
#: Name of the master slide to base the plan slides on; "" = first master.
DEFAULT_MASTER = ""
#: How many colours the picker remembers as "Recently used".
RECENT_LIMIT = 14

# --------------------------------------------------------------------------- #
# the section-name box (the *Section Titles* command)
# --------------------------------------------------------------------------- #
#
# The box is drawn on slides the user made, so everything about it is a matter of
# taste and everything here can be left alone: the font, the size and the position
# each have an "ask the deck" value, which is what a deck that has not been touched
# gets.  The position is stored in 1/100 mm - the unit every geometry property in
# ``core`` uses, and never derived from a point size (fact 20) - and the settings
# dialog shows it in centimetres, the unit Impress's own Position and Size dialog
# uses.

#: The six fields are a **default**, not an order.  *Insert Section Titles* copies the
#: position and the look of the first section slide's own box - "copy the position and
#: formatting of the first section title textbox you see when inserting / updating section
#: title" - so what these describe is a box there is nothing to copy from: a deck nobody
#: has styled, or one whose boxes were just removed.  The dialog says so beside each of
#: them, which is why they are called *Default …* and why there is no toggle for the
#: choice: one box per deck would be two answers to the same question.

#: Font of the box; "" = the font the deck paints its body text with.
DEFAULT_SECTION_FONT = ""
#: Colour of the box: the deck's own muted grey to begin with, because a section
#: label is secondary information.
DEFAULT_SECTION_COLOR = DEFAULT_MUTED_COLOR
#: Point size of the box; 0 = the size the deck's body text uses.
DEFAULT_SECTION_SIZE = 0.0
#: Where the box goes in 1/100 mm; ``None`` = where the deck's own content box is.
DEFAULT_SECTION_X = None
DEFAULT_SECTION_Y = None
DEFAULT_SECTION_WIDTH = None

DEFAULTS = {
    "muted_color": DEFAULT_MUTED_COLOR,
    "text_color": DEFAULT_TEXT_COLOR,
    "title": DEFAULT_TITLE,
    "master": DEFAULT_MASTER,
    # newest first, so the picker can offer them as a palette of their own the
    # way LibreOffice's colour dropdown does
    "recent_colors": [],
    "section_font": DEFAULT_SECTION_FONT,
    "section_color": DEFAULT_SECTION_COLOR,
    "section_size": DEFAULT_SECTION_SIZE,
    "section_x": DEFAULT_SECTION_X,
    "section_y": DEFAULT_SECTION_Y,
    "section_width": DEFAULT_SECTION_WIDTH,
}


def _profile_from_path(path):
    """``<profile>/user`` taken from a deployed extension's own path, or None.

    An extension installed for the user lives in
    ``<profile>/user/uno_packages/cache/...``, so its own module path says which
    profile the running office uses - including a non-default one from
    ``-env:UserInstallation``, which no amount of asking the office through pyuno
    revealed (``PathSettings.User`` and ``PathSubstitution`` are both unreachable
    there, ``AttributeError``).
    """
    parts = os.path.abspath(path).split(os.sep)
    for index in range(len(parts) - 1):
        if parts[index] == "user" and parts[index + 1] == "uno_packages":
            return os.sep.join(parts[:index + 1]) or os.sep
    return None


def _profile_from_package():
    return _profile_from_path(__file__)


def _user_profile(ctx):
    """The user profile of the office this code runs in, as a system path.

    Getting this wrong is not cosmetic: with the hard-coded fallback the
    extension reads and writes its settings in *some other* LibreOffice's
    profile, so saving appears to do nothing.
    """
    import uno
    candidates = [_profile_from_package()]
    try:
        candidates.append(ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.util.PathSettings", ctx).User)
    except Exception:
        pass
    try:
        substitution = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.util.PathSubstitution", ctx)
        candidates.append(substitution.getSubstitutedValue("$(user)"))
    except Exception:
        pass
    for base in candidates:
        if not base:
            continue
        path = uno.fileUrlToSystemPath(base) if "://" in base else base
        if os.path.isabs(path):
            return path
    return os.path.join(os.path.expanduser("~"), ".config", "libreoffice", "4", "user")


def _profile_dir(ctx):
    """Directory holding the extension's own data, created on demand.

    ``PLAN_IMPRESS_DATA_DIR`` overrides it, which matters for the scripts in
    ``dev/``: they run *outside* the office, where the deployment path that
    normally identifies the profile does not exist.
    """
    override = os.environ.get("PLAN_IMPRESS_DATA_DIR")
    folder = (override if override and os.path.isabs(override)
              else os.path.join(_user_profile(ctx), "planimpress"))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def settings_path(ctx):
    return os.path.join(_profile_dir(ctx), "settings.json")


def debug_log_path(ctx):
    return os.path.join(_profile_dir(ctx), "debug.log")


def debug_enabled(ctx):
    """Diagnostics are on when a ``debug`` marker file exists next to the
    settings, or when PLAN_IMPRESS_DEBUG is set in the environment."""
    if os.environ.get("PLAN_IMPRESS_DEBUG"):
        return True
    return os.path.exists(os.path.join(_profile_dir(ctx), "debug"))


def log(ctx, message):
    try:
        if not debug_enabled(ctx):
            return
        with open(debug_log_path(ctx), "a", encoding="utf-8") as handle:
            import time
            handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), message))
    except Exception:
        pass


def error_log_path(ctx):
    return os.path.join(_profile_dir(ctx), "error.log")


def log_error(ctx, message):
    """Append a failure to ``error.log``.

    Always written, unlike :func:`log`: a command that fails silently would be
    impossible to diagnose otherwise, and failures are rare enough that a
    growing error log is always meaningful.
    """
    try:
        with open(error_log_path(ctx), "a", encoding="utf-8") as handle:
            import time
            handle.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def load(ctx):
    """Return the settings merged over the defaults; never raises."""
    settings = dict(DEFAULTS)
    try:
        with open(settings_path(ctx), encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    settings[key] = stored[key]
    except Exception:
        pass
    settings["muted_color"] = _as_color(settings["muted_color"], DEFAULT_MUTED_COLOR)
    settings["text_color"] = _as_color(settings["text_color"], DEFAULT_TEXT_COLOR)
    settings["title"] = str(settings["title"] or DEFAULT_TITLE)
    settings["master"] = str(settings["master"] or "")
    settings["recent_colors"] = _as_colors(settings["recent_colors"])
    settings["section_font"] = str(settings["section_font"] or "").strip()
    settings["section_color"] = _as_color(settings["section_color"],
                                          DEFAULT_SECTION_COLOR)
    settings["section_size"] = _as_point(settings["section_size"])
    settings["section_x"] = _as_length(settings["section_x"])
    settings["section_y"] = _as_length(settings["section_y"])
    settings["section_width"] = _as_length(settings["section_width"])
    return settings


def _as_point(value):
    """A point size, or ``0`` for "the deck's own"; rubbish is the same as empty.

    ``CharHeight`` is a point size and nothing else in this code derives one from a
    length (fact 20), and a hand-edited settings file has been seen to carry a string
    here - which used to reach ``core`` and fail a whole run halfway through.
    """
    try:
        size = float(value)
    except (TypeError, ValueError):
        return 0.0
    if size != size or size < 0:      # NaN or a negative size
        return 0.0
    return min(size, 400.0)


def _as_length(value):
    """A length in 1/100 mm as ``core`` wants it, or ``None`` for "the deck's own"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    try:
        length = float(value)
    except (TypeError, ValueError):
        return None
    if length != length or length < 0:
        return None
    return int(round(length))


def _as_colors(value):
    """A list of sane RGB ints; anything else in the file is dropped."""
    if not isinstance(value, (list, tuple)):
        return []
    colours = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        colour = item & 0xFFFFFF
        if colour not in colours:
            colours.append(colour)
    return colours[:RECENT_LIMIT]


def remember_colour(settings, colour):
    """Record a colour the user just picked, newest first, without duplicates."""
    recent = [int(colour) & 0xFFFFFF] + list(settings.get("recent_colors") or [])
    settings["recent_colors"] = _as_colors(recent)   # sanitises, dedupes, truncates
    return settings["recent_colors"]


def user_profile(ctx):
    """The user profile of the running office; public because the palette loader
    needs it to find ``<profile>/user/config/*.soc``."""
    return _user_profile(ctx)


def _as_color(value, fallback):
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value & 0xFFFFFF
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        try:
            return int(text, 16) & 0xFFFFFF
        except ValueError:
            return fallback
    return fallback


def save(ctx, settings):
    """Persist the known settings; returns the path written to."""
    payload = {key: settings.get(key, DEFAULTS[key]) for key in DEFAULTS}
    path = settings_path(ctx)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def color_to_hex(color):
    return "%06X" % (int(color) & 0xFFFFFF)


def hex_to_color(text, fallback=0):
    try:
        return int(str(text).strip().lstrip("#"), 16) & 0xFFFFFF
    except (TypeError, ValueError):
        return fallback
