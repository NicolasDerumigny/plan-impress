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
import subprocess
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


def dev_office_pid():
    """The pid of the development office, or ``None`` when none is running.

    The profile path is in its own command line (``-env:UserInstallation=...``), so
    this finds the instance these scripts started and never a soffice of the user's.
    """
    try:
        pids = os.listdir("/proc")
    except OSError:                      # not Linux: fall back to the socket alone
        return -1
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as handle:
                command = handle.read().decode("utf-8", "replace")
        except OSError:
            continue
        if "soffice.bin" in command and PROFILE in command:
            return int(pid)
    return None


def is_alive():
    """True when the development office still answers on its UNO socket.

    The socket alone is not enough: an office that is aborting keeps its listening
    socket for a moment, so the test that died with it looks like one that merely
    failed.  Both have to be true.
    """
    pid = dev_office_pid()
    if pid is None:
        return False
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex(("127.0.0.1", PORT)) == 0
    except OSError:
        return False
    finally:
        probe.close()


def died(within=2.0):
    """True when the development office goes away within ``within`` seconds.

    An office that aborts does not stop listening the instant it dies, so a caller
    that has just seen a test fail cannot trust a single look: this watches for the
    process to disappear instead of reading the socket once.
    """
    deadline = time.time() + within
    while True:
        if not is_alive():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def restart():
    """Start the development office again and return a context for it.

    ``dev/start_ui.sh`` stops whatever is running first, so this works both after a
    crash and on a healthy office.  A long UI session does take the office down now
    and then - ``free(): invalid pointer`` in ``cppu::OWeakAggObject::release``
    inside ``libeditenglo`` while pyuno lets go of a text object whose document is
    already gone (``out/soffice.log`` keeps the stack) - and it happens on documents
    the extension has never seen, so a caller that plans to keep working asks for a
    new office rather than reporting the death of every later test.
    """
    subprocess.call([os.path.join(ROOT, "dev", "start_ui.sh")],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return connect()


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


def _load(desk, url, args, retries=40, delay=0.5):
    """``loadComponentFromURL`` with the moment after a start waited out.

    A freshly started office answers its socket before the desktop can create a
    document, and the load then answers with a *null* component instead of raising;
    the caller's first property read is the unhelpful "cannot get value DrawPages".
    """
    for _attempt in range(retries):
        try:
            doc = desk.loadComponentFromURL(url, "_blank", 0, tuple(args))
            doc.getURL()                     # a null proxy raises here
            return doc
        except Exception:
            time.sleep(delay)
    raise RuntimeError("the office would not open %s" % url)


def open_doc(desk, path, hidden=True):
    """Load a document; ``hidden=False`` gives it a controller (needed for dispatch)."""
    clear_lock(path)
    args = [pv("Hidden", True)] if hidden else []
    doc = _load(desk, uno.systemPathToFileUrl(str(path)), args)
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
    return _load(desk, factory, args)


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
