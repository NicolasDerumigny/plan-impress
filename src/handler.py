"""Menu entry points for Plan Impress.

Each menu item points at a ``com.sun.star.task.Job`` service (see
``Addons.xcu``): a URL like ``service:org.devsys.planimpress.InsertPlan`` makes
LibreOffice instantiate the matching implementation registered below and call
``XJobExecutor.trigger()``.

Why Jobs and not ``vnd.sun.star.script:...`` URLs?  A script URL for an
extension-bundled Python file has to spell out the installed ``.oxt`` file name
and ``location=user:uno_packages``, which breaks as soon as the extension is
renamed, updated or installed for all users.  Implementation names are stable.

All ``com.sun.star.*`` and ``plan_impress.*`` imports are deferred into the
methods: the extension manager imports this module while registering it, and a
top-level ``from com.sun.star... import`` fails there with
``ImportError: No module named 'com'``.
"""

import os
import sys
import traceback

import unohelper

_REGISTRATION_ONLY = False
try:  # available in-process, may be absent while the extension is registered
    from com.sun.star.task import XJobExecutor
except ImportError:  # pragma: no cover - registration-time fallback
    XJobExecutor = object
    _REGISTRATION_ONLY = True

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _log(ctx, message):
    try:
        from plan_impress import config
        config.log(ctx, message)
    except Exception:
        pass


def _report(ctx, error):
    """Tell the user something went wrong, with the traceback in the log."""
    try:
        from plan_impress import config
        config.log_error(ctx, "ERROR %s\n%s" % (error, traceback.format_exc()))
    except Exception:
        pass
    try:
        from plan_impress import dialog
        dialog.message(ctx, "%s\n\n(See the Plan Impress log for details.)" % error,
                       "error")
    except Exception:
        pass


def _active_presentation(ctx):
    """The Impress document in front, or a PlanError explaining why not."""
    from plan_impress import core
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx)
    component = None
    try:
        component = desktop.getCurrentComponent()
    except Exception:
        pass
    if component is None:
        raise core.PlanError("Open an Impress presentation first.")
    if not hasattr(component, "DrawPages") or not hasattr(component, "MasterPages"):
        raise core.PlanError("This command works in an Impress presentation only.")
    return component


def _master_names(doc):
    try:
        masters = doc.MasterPages
        return [masters.getByIndex(i).Name for i in range(masters.Count)]
    except Exception:
        return []


_PENDING = []  # keeps a deferred timer and its listener alive until it fires


def _defer_to_main_loop(ctx, runner):
    """Run ``runner()`` from the office event loop instead of inside a dispatch.

    ``com.sun.star.awt.Timer`` fires on the main loop; that is the safe place to
    run work that itself dispatches commands, should it ever be needed.  The
    commands here run inline (see :class:`PlanJob`), so this is only used when
    ``PLAN_IMPRESS_DEFER=1`` is set in the environment - it exists to reproduce
    and debug dispatch ordering problems.  Returns False if the timer service is
    not available.
    """
    try:
        import unohelper
        from com.sun.star.awt import XTimerListener
        timer = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.Timer", ctx)
    except Exception:
        return False
    try:

        class Tick(unohelper.Base, XTimerListener):
            fired = False

            def timer(self, event):
                if self.fired:
                    return
                self.fired = True
                try:
                    timer.stop()
                except Exception:
                    pass
                try:
                    _PENDING.remove(holder)
                except ValueError:
                    pass
                runner()

        listener = Tick()
        holder = (timer, listener)
        _PENDING.append(holder)
        timer.addListener(listener)
        timer.start(50)  # milliseconds
        return True
    except Exception:
        try:
            timer.dispose()
        except Exception:
            pass
        return False


class PlanJob(unohelper.Base, XJobExecutor):
    """Base class: one Job per command, the command is the implementation name.

    Commands run inline.  ``insert`` moves slides with ``.uno:MovePageUp`` /
    ``.uno:MovePageDown``, which are asynchronous, so :func:`core.insert_page_at`
    polls until the page really moved - doing that from the office main loop
    works, whereas running the same code from a Python worker thread crashed the
    office (``free(): invalid pointer``).  ``PLAN_IMPRESS_DEFER=1`` runs the
    command from a main-loop timer instead, which is useful when debugging
    dispatch ordering.
    """

    command = ""
    DEFERRED = ("insert", "remove")

    def __init__(self, ctx):
        self.ctx = ctx

    # XJobExecutor ------------------------------------------------------- #
    def trigger(self, args):
        _log(self.ctx, "trigger command=%s args=%r" % (self.command, args))
        handler = getattr(self, "do_" + self.command, None)
        if handler is None:
            _report(self.ctx, RuntimeError("Unknown Plan Impress command %r"
                                           % self.command))
            return
        if (self.command in self.DEFERRED
                and os.environ.get("PLAN_IMPRESS_DEFER") == "1"
                and _defer_to_main_loop(self.ctx, lambda: self._run(handler))):
            return
        self._run(handler)

    def _run(self, handler):
        try:
            handler()
        except Exception as error:
            from plan_impress import config, core
            try:
                config.log_error(self.ctx, "%s: %s\n%s" % (self.command, error,
                                                            traceback.format_exc()))
            except Exception:
                pass
            if isinstance(error, core.PlanError):
                from plan_impress import dialog
                dialog.message(self.ctx, str(error), "warning")
            else:
                _report(self.ctx, error)

    def dispose(self):
        pass

    # commands ----------------------------------------------------------- #
    def do_insert(self):
        from plan_impress import config, core
        doc = _active_presentation(self.ctx)
        settings = config.load(self.ctx)
        report = core.insert_plan(doc, settings, self.ctx)
        _log(self.ctx, "insert_plan -> %s" % report)

    def do_remove(self):
        from plan_impress import core
        doc = _active_presentation(self.ctx)
        removed = core.remove_plan(doc)
        _log(self.ctx, "remove_plan -> %d slides" % removed)

    def do_settings(self):
        from plan_impress import config, dialog
        doc = None
        try:
            doc = _active_presentation(self.ctx)
        except Exception:
            pass  # settings are per profile, so they do not require a document
        masters = _master_names(doc) if doc is not None else []
        current = config.load(self.ctx)
        updated = dialog.open_settings(self.ctx, current, masters)
        if updated is None:
            _log(self.ctx, "settings cancelled")
            return
        path = config.save(self.ctx, updated)
        _log(self.ctx, "settings saved to %s: %s" % (path, updated))

    def do_debug(self):
        """Toggle the debug log, handy while diagnosing the extension itself."""
        from plan_impress import config, dialog
        path = config.debug_log_path(self.ctx)
        marker = os.path.join(os.path.dirname(path), "debug")
        enabled = not os.path.exists(marker)
        try:
            if enabled:
                with open(marker, "w") as handle:
                    handle.write("1\n")
            else:
                os.remove(marker)
        except Exception:
            pass
        dialog.message(self.ctx, "Debug log %s:\n%s" %
                       ("enabled, writing to" if enabled else "disabled", path), "info")


class InsertPlan(PlanJob):
    command = "insert"


class RemovePlan(PlanJob):
    command = "remove"


class Settings(PlanJob):
    command = "settings"


class Debug(PlanJob):
    command = "debug"


if not _REGISTRATION_ONLY:
    _JOB = ("com.sun.star.task.Job",)
    _HELPER = unohelper.ImplementationHelper()
    _HELPER.addImplementation(
        InsertPlan, "org.devsys.planimpress.InsertPlan", _JOB)
    _HELPER.addImplementation(
        RemovePlan, "org.devsys.planimpress.RemovePlan", _JOB)
    _HELPER.addImplementation(
        Settings, "org.devsys.planimpress.Settings", _JOB)
    _HELPER.addImplementation(
        Debug, "org.devsys.planimpress.Debug", _JOB)
    g_ImplementationHelper = _HELPER
else:  # pragma: no cover
    # Registered without the real interface: drop the module from the cache so
    # the next import (inside a running office) builds proper UNO classes.
    sys.modules.pop(__name__, None)
