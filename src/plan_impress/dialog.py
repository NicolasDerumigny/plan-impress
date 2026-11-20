"""Small UI layer: message boxes and the settings dialog.

Three LibreOffice quirks shaped this module; all of them are measured, not
guessed (``dev/debug_dialog*.py`` reproduces each one):

``com.sun.star.awt.UnoControl``'s ``Model`` property is *read-only*
    You cannot do ``dialog.Model = dialogModel`` (``UnknownPropertyException:
    ... property is readonly``).  Use ``dialog.setModel(dialogModel)``.

Control models must come from the *dialog model's* own ``createInstance``
    A model from the service manager exposes no ``PositionX``/``Width``/``Height``
    (``UnknownPropertyException``) and ``insertByName`` refuses a
    ``sequence<PropertyValue>`` carrying a ``Servicename``, so with that route
    every control lands at 0,0 with its natural size - the form is a pile in the
    corner.  ``self.model.createInstance(service)`` returns a model that does keep
    its geometry, which is how ``wizards/ui/UnoDialog.py`` builds its dialogs.
    Sequence properties such as ``StringItemList`` still need an explicit
    ``uno.Any("[]string", ...)``; a plain tuple is refused.

The dialog's *window* size is a model property too
    ``XControl::setPosSize`` moves the dialog and silently ignores the size, so
    ``Width``/``Height`` are set on the dialog model; the position is set with
    ``setPosSize`` afterwards.  See ``dev/debug_dialog_windowsize.py``.

``com.sun.star.*`` is imported lazily inside the functions: during extension
registration LibreOffice imports this module from a context where those modules
are not importable, and a top-level ``from com.sun.star... import`` would make
registration fail with ``ImportError: No module named 'com'``.
"""

import uno

from plan_impress import config

TITLE = "Plan Impress"

# com.sun.star.awt.MessageBoxType
_MSGBOX = 0
_WARNINGBOX = 3
_ERRORBOX = 4
# com.sun.star.awt.MessageBoxButtons
_OK = 1
_YES_NO = 5
# com.sun.star.awt.MessageBoxResults
_RESULT_YES = 6


def _toolkit(ctx):
    return ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)


def _parent_window(ctx):
    try:
        desktop = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx)
        frame = desktop.getCurrentFrame()
        if frame is not None:
            return frame.ContainerWindow
    except Exception:
        pass
    return None


def message(ctx, text, kind="info", buttons=_OK):
    """Show a modal message box; returns the button code (1 = OK, 6 = Yes)."""
    box_type = {"info": _MSGBOX, "warning": _WARNINGBOX, "error": _ERRORBOX}[kind]
    try:
        box = _toolkit(ctx).createMessageBox(_parent_window(ctx), box_type, buttons, text)
        try:
            return box.execute()
        finally:
            box.dispose()
    except Exception:
        # Never let a reporting problem swallow the real error.
        return 0


def confirm(ctx, text):
    return message(ctx, text, "warning", _YES_NO) == _RESULT_YES


# --------------------------------------------------------------------------- #
# settings dialog
# --------------------------------------------------------------------------- #

#: ``(control name, label)`` for the label/field rows, top to bottom.
_ROWS = (
    ("MutedColor", "Muted colour (hex):"),
    ("TextColor", "Highlight colour (hex):"),
    ("Title", "Plan slide title:"),
    ("Master", "Master slide:"),
)

# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
#
# ``PositionX``/``PositionY``/``Width``/``Height``, on the dialog model and on
# every control model, are in the AWT dialog coordinate system - not pixels and
# not 1/100 mm.  One unit is about 2.5 px of peer geometry (``Width=140`` gives
# a 354 wide window, ``dev/debug_dialog_windowsize.py``), which puts this form at
# roughly 360 x 240 px, the same magnitude the shipped wizards use
# (``wizards/ui/PathSelection.py`` gives a label ``Height=8``).
_MARGIN = 8
_LABEL_X = _MARGIN
_LABEL_W = 62
_FIELD_X = _LABEL_X + _LABEL_W + 2
_FIELD_W = 42
_SWATCH_X = _FIELD_X + _FIELD_W + 3
_SWATCH_W = 18
_FIRST_ROW_Y = 12
_ROW_STEP = 14
_LABEL_H = 8
_FIELD_H = 12
_BUTTON_W = 28
_BUTTON_H = 14
_BUTTON_GAP = 3
_ROW_GAP = 6
DIALOG_WIDTH = _SWATCH_X + _SWATCH_W + _MARGIN
_BUTTON_Y = _FIRST_ROW_Y + len(_ROWS) * _ROW_STEP + _ROW_GAP
DIALOG_HEIGHT = _BUTTON_Y + _BUTTON_H + _MARGIN
_OK_X = DIALOG_WIDTH - 2 * _BUTTON_W - _BUTTON_GAP - _MARGIN
_CANCEL_X = _OK_X + _BUTTON_W + _BUTTON_GAP
_FONT = 10
_COLOUR_FIELDS = ("MutedColor", "TextColor")
_POS = 1                     # com.sun.star.awt.PosSize.POS

_FIXED_TEXT = "com.sun.star.awt.UnoControlFixedTextModel"
_EDIT = "com.sun.star.awt.UnoControlEditModel"
_LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"
_BUTTON = "com.sun.star.awt.UnoControlButtonModel"


def _master_index(values, masters):
    """Which entry of the master list to show: the saved one, else the first."""
    wanted = str(values.get("master") or "")
    return masters.index(wanted) if wanted in masters else 0


def _field_specs(values, masters):
    """The control description as ``(name, model service, properties)`` triples.

    Kept separate from UNO object creation so the tests can assert on the
    layout - every control's rectangle, and therefore the absence of overlap -
    without a display.
    """
    specs = []
    for index, (name, label) in enumerate(_ROWS):
        y = _FIRST_ROW_Y + index * _ROW_STEP
        specs.append(("label" + name, _FIXED_TEXT, [
            ("Label", label), ("PositionX", _LABEL_X), ("PositionY", y + 2),
            ("Width", _LABEL_W), ("Height", _LABEL_H), ("FontHeight", _FONT),
        ]))
        if name == "Master":
            service = _LISTBOX
            props = [("StringItemList", tuple(masters)), ("Dropdown", True),
                     # SelectedItems has to be on the model *before* it is
                     # inserted: a selection put on the inserted child never
                     # reaches the peer, and the box stays empty
                     # (dev/debug_dialog_masters.py).
                     ("SelectedItems", (_master_index(values, masters),))]
        else:
            service = _EDIT
            # No MaxLen: the container's own model service has none, so a hex
            # field is not capped here - result() validates instead.
            props = [("Text", values[name])]
        specs.append((name, service, props + [
            ("PositionX", _FIELD_X), ("PositionY", y), ("Width", _FIELD_W),
            ("Height", _FIELD_H), ("FontHeight", _FONT),
        ]))
        if name in _COLOUR_FIELDS:
            specs.append(("swatch" + name, _FIXED_TEXT, [
                ("Label", " "), ("PositionX", _SWATCH_X), ("PositionY", y),
                ("Width", _SWATCH_W), ("Height", _FIELD_H),
                ("BackgroundColor", config.hex_to_color(values[name], 0)),
                ("BorderColor", 0x808080),
            ]))
    specs.append(("ok", _BUTTON, [
        ("Label", "OK"), ("PositionX", _OK_X), ("PositionY", _BUTTON_Y),
        ("Width", _BUTTON_W), ("Height", _BUTTON_H), ("FontHeight", _FONT),
        ("DefaultButton", True),
    ]))
    specs.append(("cancel", _BUTTON, [
        ("Label", "Cancel"), ("PositionX", _CANCEL_X), ("PositionY", _BUTTON_Y),
        ("Width", _BUTTON_W), ("Height", _BUTTON_H), ("FontHeight", _FONT),
    ]))
    return specs


def _coerce(name, value):
    """UNO needs explicit types for sequences; a plain tuple is refused."""
    if name == "StringItemList":
        return uno.Any("[]string", tuple(str(item) for item in value))
    if name == "SelectedItems":
        return uno.Any("[]short", tuple(int(item) for item in value))
    return value


def _apply(control_model, props, warnings, name):
    """Set all properties at once, the way the wizards do; fall back to one by one."""
    names = tuple(property_name for property_name, _value in props)
    values = tuple(_coerce(property_name, value) for property_name, value in props)
    try:
        uno.invoke(control_model, "setPropertyValues", (names, values))
        return
    except Exception:
        pass                      # one unsupported property must not lose them all
    for property_name, value in props:
        try:
            control_model.setPropertyValue(property_name, _coerce(property_name, value))
        except Exception as error:
            warnings.append("%s.%s: %s" % (name, property_name, error))


class SettingsDialog(object):
    """Modal settings editor: hex colours, heading text, master slide."""

    def __init__(self, ctx, settings, masters):
        self.ctx = ctx
        self.settings = dict(settings)
        self.masters = [str(m) for m in masters] or [""]
        self.values = {
            "MutedColor": config.color_to_hex(settings["muted_color"]),
            "TextColor": config.color_to_hex(settings["text_color"]),
            "Title": settings["title"],
            "master": settings["master"],
        }
        self.dialog = None
        self.model = None
        self.window = None
        self.accepted = False
        self.rejected = False
        self._listeners = []
        self._warnings = []

    @property
    def warnings(self):
        """Properties the control models refused; useful when debugging."""
        return list(self._warnings)

    # -- construction ------------------------------------------------------ #
    def _new_control_model(self, service):
        """A control model that keeps the geometry it is given.

        It has to come from the **dialog model's own factory**.  A model created
        from the service manager has no ``PositionX``/``Width``/``Height``
        properties at all (``UnknownPropertyException``), so every control lands
        at 0,0 with its natural size and the form is an unreadable pile in the
        corner - the bug this function exists for.  Measured in
        ``dev/debug_dialog_wizard.py``, and it is what
        ``/usr/lib/libreoffice/program/wizards/ui/UnoDialog.py`` does.
        """
        try:
            return self.model.createInstance(service)
        except Exception:
            return self.ctx.ServiceManager.createInstanceWithContext(service, self.ctx)

    def build(self):
        """Create the dialog, its window size and all of its controls."""
        manager = self.ctx.ServiceManager
        self.dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", self.ctx)
        self.model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self.ctx)
        # dialog.Model = self.model would raise: the property is read-only.
        self.dialog.setModel(self.model)
        # The window's size comes from the model: XControl::setPosSize moves the
        # dialog but throws the size away (dev/debug_dialog_windowsize.py).
        for property_name, value in (("Width", DIALOG_WIDTH), ("Height", DIALOG_HEIGHT)):
            try:
                self.model.setPropertyValue(property_name, value)
            except Exception as error:
                self._warnings.append("dialog.%s: %s" % (property_name, error))
        for name, service, props in _field_specs(self.values, self.masters):
            control_model = self._new_control_model(service)
            _apply(control_model, props, self._warnings, name)
            self.model.insertByName(name, control_model)
        return self.dialog

    def control(self, name):
        return self.dialog.getControl(name)

    def control_model(self, name):
        return self.model.getByName(name)

    def _peer(self):
        """Attach a native peer; ``None`` parent makes the dialog top-level."""
        toolkit = _toolkit(self.ctx)
        try:
            self.dialog.createPeer(toolkit, None)
        except Exception:
            self.dialog.createPeer(toolkit, _parent_window(self.ctx))
        self._centre()

    def _centre(self):
        """Put the dialog in the middle of the frame it belongs to.

        ``setPosSize`` does move the window, it only does nothing about its size,
        so the position is set here in the peer's own coordinate system - the same
        one ``wizards/ui/UnoDialog.py`` centres its dialogs in.
        """
        area = None
        parent = _parent_window(self.ctx)
        if parent is not None:
            try:
                area = parent.getPosSize()
            except Exception:
                area = None
        if area is None:
            return
        size = self.dialog.getPosSize()
        x = max(0, area.X + (area.Width - size.Width) // 2)
        y = max(0, area.Y + (area.Height - size.Height) // 2)
        try:
            self.dialog.setPosSize(x, y, size.Width, size.Height, _POS)
        except Exception:
            pass

    def _preselect_master(self):
        """Deprecated shim: the selection is part of the model now.

        ``SelectedItems`` set on an *inserted* child never reaches the peer, so it
        has to travel with the control model - see ``_field_specs`` and
        ``dev/debug_dialog_masters.py``.  Kept so older callers are harmless.
        """
        return _master_index(self.values, self.masters)

    # -- interaction ------------------------------------------------------- #
    def _press(self, name):
        self.accepted = name == "ok"
        self.rejected = not self.accepted
        try:
            self.dialog.endExecute()
        except Exception:
            pass

    def _refresh_swatch(self, name):
        try:
            color = config.hex_to_color(self.control(name).getText(), 0)
            self.control_model("swatch" + name).setPropertyValue("BackgroundColor", color)
        except Exception:
            pass

    def _install_listeners(self):
        """Attach the button and colour listeners to the peers.

        Separate from ``run()`` so a test can fire a button event without having
        to enter the modal loop.
        """
        import unohelper
        from com.sun.star.awt import XActionListener, XTextListener

        outer = self

        class Buttons(unohelper.Base, XActionListener):
            """One instance per button.  Deciding from ``event.Source.Model.Name``
            has been seen to fail, which silently turned an OK into a cancel, so
            each listener already knows which button it belongs to."""

            def __init__(self, name):
                self.name = name

            def actionPerformed(self, event):
                outer._press(self.name)

            def disposing(self, event):
                pass

        class ColourWatcher(unohelper.Base, XTextListener):
            def __init__(self, field):
                self.field = field

            def textChanged(self, event):
                outer._refresh_swatch(self.field)

            def textInserted(self, event):
                outer._refresh_swatch(self.field)

            def textRemoved(self, event):
                outer._refresh_swatch(self.field)

            def disposing(self, event):
                pass

        if self.dialog is None:
            self.build()
        self._peer()
        try:
            self.dialog.setTitle(TITLE)
        except Exception:
            pass
        for name in ("ok", "cancel"):
            control = self.control(name)
            listener = Buttons(name)
            control.addActionListener(listener)
            self._listeners.append((control, listener))
        for field in _COLOUR_FIELDS:
            control = self.control(field)
            watcher = ColourWatcher(field)
            control.addTextListener(watcher)
            self._listeners.append((control, watcher))

    def run(self):
        """Show the dialog modally; return the new settings, or ``None``."""
        if self.dialog is None:
            self.build()
        self._peer()
        try:
            self.dialog.setTitle(TITLE)
        except Exception:
            pass
        self._install_listeners()
        config.log(self.ctx, "settings dialog: %d controls, %dx%d units"
                   % (len(self.model.ElementNames), *self._asked_size()))
        try:
            self.dialog.execute()
            config.log(self.ctx, "settings dialog closed: accepted=%s" % self.accepted)
            return self.result() if self.accepted else None
        finally:
            self.dispose()

    def _asked_size(self):
        return (self.model.getPropertyValue("Width"), self.model.getPropertyValue("Height"))

    def _text(self, name):
        """Text of an edit control, with the model as fallback."""
        try:
            return self.control(name).getText()
        except Exception:
            return str(self.control_model(name).getPropertyValue("Text"))

    def result(self):
        """Read the control values back into a settings dict."""
        if self.dialog is None:
            return None
        master = self.values.get("master", "")
        try:
            selected = list(self.control("Master").getSelectedItems())
            if selected:
                master = selected[0]
        except Exception:
            pass
        return {
            "muted_color": config.hex_to_color(self._text("MutedColor"),
                                               self.settings["muted_color"]),
            "text_color": config.hex_to_color(self._text("TextColor"),
                                              self.settings["text_color"]),
            "title": self._text("Title").strip() or "Plan",
            "master": master,
        }

    def dispose(self):
        for control, listener in self._listeners:
            try:
                if hasattr(control, "removeActionListener"):
                    control.removeActionListener(listener)
            except Exception:
                pass
        self._listeners = []
        for part in ("dialog", "window"):
            obj = getattr(self, part, None)
            if obj is not None:
                try:
                    obj.dispose()
                except Exception:
                    pass
        self.dialog = self.model = self.window = None


def open_settings(ctx, settings, masters):
    """Modal settings editor; returns a settings dict, or ``None`` on cancel."""
    return SettingsDialog(ctx, settings, masters).run()
