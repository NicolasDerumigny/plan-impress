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

DEFAULTS = {
    "muted_color": DEFAULT_MUTED_COLOR,
    "text_color": DEFAULT_TEXT_COLOR,
    "title": DEFAULT_TITLE,
    "master": DEFAULT_MASTER,
}


def _profile_dir(ctx):
    """Directory holding the extension's own data, created on demand."""
    base = None
    try:
        sub = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.util.PathSubstitution", ctx)
        base = sub.getSubstitutedValue("$(user)")
    except Exception:
        base = None
    if not base:
        base = os.path.expanduser("~/.config/libreoffice/4/user")
    import uno
    if base.startswith("file://"):
        path = uno.fileUrlToSystemPath(base)
    else:
        path = base
    folder = os.path.join(path, "planimpress")
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
    return settings


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
