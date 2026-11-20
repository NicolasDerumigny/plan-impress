"""Helpers to drive a LibreOffice instance from the command line during development.

Usage (from the repository root)::

    import sys; sys.path.insert(0, "dev")
    import lo
    ctx = lo.connect()
    doc = lo.open_doc(lo.desktop(ctx), "tests/fixtures/sections.odp", hidden=False)

The scripts never touch your normal LibreOffice configuration: they use a
profile inside the checkout (``loprofile/``, override with
``PLAN_IMPRESS_PROFILE``) and a private UNO socket port (``2009``, override with
``PLAN_IMPRESS_PORT``), so a running office of yours is left alone.
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.environ.get("PLAN_IMPRESS_PROFILE", os.path.join(ROOT, "loprofile"))
PORT = int(os.environ.get("PLAN_IMPRESS_PORT", "2009"))
RESOLVE_URL = (
    "uno:socket,host=127.0.0.1,port=%d;urp;StarOffice.ComponentContext" % PORT)

for _program in (os.environ.get("LIBREOFFICE_PROGRAM"), "/usr/lib/libreoffice/program",
                 "/usr/lib64/libreoffice/program"):
    if _program and os.path.isdir(_program):
        if _program not in sys.path:
            sys.path.insert(0, _program)
        break

import uno  # noqa: E402
from com.sun.star.beans import PropertyValue  # noqa: E402


def pv(name, value):
    """A ``com.sun.star.beans.PropertyValue``."""
    prop = PropertyValue()
    prop.Name = name
    prop.Value = value
    return prop


def connect(retries=40, delay=0.5):
    """Component context of the running instance; waits for the socket."""
    for _attempt in range(retries):
        try:
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", local)
            return resolver.resolve(RESOLVE_URL)
        except Exception:
            time.sleep(delay)
    raise RuntimeError("cannot connect to soffice on port %d (is dev/start_ui.sh running?)"
                       % PORT)


def desktop(ctx):
    return ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx)


def clear_lock(path):
    """Remove the ``.~lock.<name>#`` a killed office leaves in front of a document.

    ``dev/stop_lo.sh`` kills soffice, and a killed office cannot clean up after
    itself; the next ``loadComponentFromURL`` then waits on a modal "the document is
    in use" dialog and the calling script hangs without a word.
    """
    directory, name = os.path.split(str(path))
    lock = os.path.join(directory, ".~lock.%s#" % name)
    if os.path.exists(lock):
        os.remove(lock)
    return lock


def open_doc(desk, path, hidden=True):
    """Load a document; ``hidden=False`` gives it a controller (needed for dispatch)."""
    clear_lock(path)
    args = [pv("Hidden", True)] if hidden else []
    doc = desk.loadComponentFromURL(uno.systemPathToFileUrl(str(path)), "_blank", 0,
                                    tuple(args))
    if not hidden:
        for _attempt in range(60):  # the controller attaches asynchronously
            if doc.CurrentController is not None:
                break
            time.sleep(0.1)
    return doc


def new_doc(desk, kind="simpress", hidden=True):
    factory = {"simpress": "private:factory/simpress",
               "draw": "private:factory/sdraw"}[kind]
    args = [pv("Hidden", True)] if hidden else []
    return desk.loadComponentFromURL(factory, "_blank", 0, tuple(args))


def close(doc):
    try:
        doc.setModified(False)
    except Exception:
        pass
    try:
        doc.close(False)
    except Exception:
        pass


_CONTEXT = None


def _shared_context():
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = connect()
    return _CONTEXT


def dispatch(doc, command, args=()):
    """Run a ``.uno:`` / ``service:`` command against the document's frame.

    This is the same path a menu click takes, so it is how the menu items of
    the extension are tested.
    """
    ctx = _shared_context()
    helper = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", ctx)
    helper.executeDispatch(doc.CurrentController.Frame, command, "", 0, tuple(args))


def wait_until(predicate, timeout=15.0, delay=0.25):
    """Poll ``predicate`` until it is true; returns whether it became true."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False
