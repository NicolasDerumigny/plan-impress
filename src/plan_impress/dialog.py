"""Small UI layer: message boxes and the settings dialog.

Two LibreOffice quirks shaped this module; both are measured, not guessed (see
``dev/debug_dialog.py``):

``com.sun.star.awt.UnoControl``'s ``Model`` property is *read-only*
    You cannot do ``dialog.Model = dialogModel`` (``UnknownPropertyException:
    ... property is readonly``).  Use ``dialog.setModel(dialogModel)``.

``XNameContainer.insertByName`` on a dialog model rejects a
``sequence<PropertyValue>`` with a ``Servicename`` entry
    (``IllegalArgumentException``).  Create each control's own model service
    (``com.sun.star.awt.UnoControlEditModel`` and friends), set its properties,
    and insert *that*.  Sequence properties such as ``StringItemList`` also need
    an explicit ``uno.Any("[]string", ...)``; a plain tuple is refused.

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

#: (control name, label, x, y, label width) for the label/field rows.  Units
#: are 1/100 mm, the AWT control coordinate system.
_ROWS = (
    ("MutedColor", "Muted text colour (hex):", 15, 15, 130),
    ("TextColor", "Current section colour (hex):", 15, 42, 130),
    ("Title", "Slide heading:", 15, 69, 130),
    ("Master", "Master slide:", 15, 96, 130),
)
_EDIT_X, _EDIT_W = 155, 70
_SWATCH_X, _SWATCH_W = 235, 45
DIALOG_WIDTH, DIALOG_HEIGHT = 320, 190
_FONT = 10
_COLOUR_FIELDS = ("MutedColor", "TextColor")

_FIXED_TEXT = "com.sun.star.awt.UnoControlFixedTextModel"
_EDIT = "com.sun.star.awt.UnoControlEditModel"
_LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"
_BUTTON = "com.sun.star.awt.UnoControlButtonModel"


def _field_specs(values, masters):
    """The control description as ``(name, model service, properties)`` triples.

    Kept separate from UNO object creation so the tests can assert on the
    layout without a display.
    """
    specs = []
    for name, label, x, y, width in _ROWS:
        specs.append(("label" + name, _FIXED_TEXT, [
            ("Label", label), ("PositionX", x), ("PositionY", y),
            ("Width", width), ("Height", 14), ("FontHeight", _FONT),
        ]))
        props = [("PositionX", _EDIT_X), ("PositionY", y - 2), ("Width", _EDIT_W),
                 ("Height", 20), ("FontHeight", _FONT), ("TabStop", True)]
        if name == "Master":
            service = _LISTBOX
            props = [("StringItemList", tuple(masters)),
                     ("Dropdown", True), ("Multiple", False)] + props
        else:
            service = _EDIT
            props = [("Text", values[name]), ("MaxLen", 7)] + props
        specs.append((name, service, props))
        if name in _COLOUR_FIELDS:
            specs.append(("swatch" + name, _FIXED_TEXT, [
                ("Label", " "), ("PositionX", _SWATCH_X), ("PositionY", y - 2),
                ("Width", _SWATCH_W), ("Height", 20),
                ("BackgroundColor", config.hex_to_color(values[name], 0)),
                ("BorderColor", 0x808080),
            ]))
    specs.append(("ok", _BUTTON, [
        ("Label", "OK"), ("PositionX", 105), ("PositionY", 150),
        ("Width", 90), ("Height", 26), ("FontHeight", _FONT),
        ("DefaultButton", True), ("TabStop", True), ("TabPosition", 1),
    ]))
    specs.append(("cancel", _BUTTON, [
        ("Label", "Cancel"), ("PositionX", 205), ("PositionY", 150),
        ("Width", 90), ("Height", 26), ("FontHeight", _FONT),
        ("TabStop", True), ("TabPosition", 2),
    ]))
    return specs


def _coerce(name, value):
    """UNO needs explicit types for sequences; a plain tuple is refused."""
    if name == "StringItemList":
        return uno.Any("[]string", tuple(str(item) for item in value))
    return value


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
    def build(self):
        """Create the dialog and all of its controls (no peer yet)."""
        manager = self.ctx.ServiceManager
        self.dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", self.ctx)
        self.model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self.ctx)
        # dialog.Model = self.model would raise: the property is read-only.
        self.dialog.setModel(self.model)
        for name, service, props in _field_specs(self.values, self.masters):
            control_model = manager.createInstanceWithContext(service, self.ctx)
            for property_name, value in props:
                try:
                    control_model.setPropertyValue(property_name,
                                                   _coerce(property_name, value))
                except Exception as error:
                    self._warnings.append("%s.%s: %s" % (name, property_name, error))
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
            descriptor = uno.createUnoStruct("com.sun.star.awt.WindowDescriptor")
            descriptor.Type = 0  # com.sun.star.awt.WindowType.TOP
            descriptor.PosSize = 3  # POS | SIZE
            descriptor.X, descriptor.Y = 120, 120
            descriptor.Width, descriptor.Height = DIALOG_WIDTH, DIALOG_HEIGHT
            self.window = toolkit.createWindow(descriptor)
            self.dialog.createPeer(toolkit, self.window)

    def _preselect_master(self):
        wanted = self.values.get("master")
        if not wanted or wanted not in self.masters:
            return
        try:
            # SelectedItems is 0-based on the list box model.
            self.control_model("Master").setPropertyValue(
                "SelectedItems", uno.Any("[]short", (self.masters.index(wanted),)))
        except Exception as error:
            self._warnings.append("Master.SelectedItems: %s" % error)

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

    def run(self):
        """Show the dialog modally; return the new settings, or ``None``."""
        import unohelper
        from com.sun.star.awt import XActionListener, XTextListener

        outer = self

        class Buttons(unohelper.Base, XActionListener):
            def actionPerformed(self, event):
                name = "cancel"
                try:
                    name = str(event.Source.Model.Name)
                except Exception:
                    pass
                outer._press("ok" if name == "ok" else "cancel")

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
        buttons = Buttons()
        for name in ("ok", "cancel"):
            control = self.control(name)
            control.addActionListener(buttons)
            self._listeners.append((control, buttons))
        for field in _COLOUR_FIELDS:
            control = self.control(field)
            watcher = ColourWatcher(field)
            control.addTextListener(watcher)
            self._listeners.append((control, watcher))
        self._preselect_master()
        try:
            self.dialog.execute()
            return self.result() if self.accepted else None
        finally:
            self.dispose()

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
