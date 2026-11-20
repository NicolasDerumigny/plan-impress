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
