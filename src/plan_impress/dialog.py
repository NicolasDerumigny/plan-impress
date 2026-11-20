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

import traceback

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


#: Our own message box, in dialog units (fact 28: one unit is about 2.5 px).
_BOX_MARGIN = 10
_BOX_TEXT_W = 110                  # ~275 px of text before a line is wrapped
_BOX_LINE_H = 9                    # one line of _FONT text, with air
_BOX_BUTTON_W = 26
_BOX_BUTTON_H = 18
_BOX_BUTTON_GAP = 4
_BOX_GAP = 10                      # between the text and the buttons
_BOX_CHARS = 44                    # characters per line at _FONT

#: com.sun.star.awt.KeyCodes, spelled out because importing ``KeyCodes`` at the top
#: of the module is what makes extension registration fail (fact 3).
_KEY_ESCAPE = 27
_KEY_RETURN = 1

#: What :func:`message` answers.  ``createMessageBox`` is gone (see its docstring)
#: and this box decides its own codes, but ``YES`` stays at the 6 the office used to
#: answer for it (fact 32) because :func:`confirm` and the tests read that value.
RESULT_CANCELLED = 0
RESULT_OK = 1
RESULT_YES = 6
RESULT_NO = 2


def box_lines(text, width=_BOX_CHARS):
    """The text as the lines the box shows, one label per line.

    ``UnoControlFixedTextModel`` has ``MultiLine`` and nothing else that helps: no
    ``WordWrap``, no ``TextAlign`` (and no ``Mnemonic``, no ``Decorative``, no
    ``MaxLen`` - each one ``UnknownPropertyException``, ``dev/probe_mnemonic.py``), so
    a label cannot be asked to wrap or to align - the wrapping happens here instead
    and each line gets a control of its own, which is also what fixes the height of
    the window.  ``break_long_words`` matters: the log path the debug box prints is
    one long word.  ``break_on_hyphens`` is off for the same reason: splitting a path
    at a hyphen makes it look like two paths.
    """
    import textwrap
    lines = []
    for paragraph in str(text).split("\n"):
        lines += textwrap.wrap(paragraph, width, break_long_words=True,
                               break_on_hyphens=False) or [""]
    return lines


def box_size(text):
    """``(width, height)`` of the box for ``text``, in dialog units."""
    lines = box_lines(text)
    return (2 * _BOX_MARGIN + _BOX_TEXT_W,
            2 * _BOX_MARGIN + len(lines) * _BOX_LINE_H + _BOX_GAP + _BOX_BUTTON_H)


def box_specs(text, kind, buttons, title):
    """The box's controls as ``(name, service, [(property, value)])``.

    Split out from the UNO calls so the geometry can be tested without a display,
    the way ``dialog._field_specs`` and ``picker._field_specs`` are.
    """
    width, height = box_size(text)
    service = "com.sun.star.awt.UnoControlButtonModel"
    specs = []
    for index, line in enumerate(box_lines(text)):
        specs.append(("text%d" % index, _FIXED_TEXT, [
            ("Label", line), ("PositionX", _BOX_MARGIN),
            ("PositionY", _BOX_MARGIN + index * _BOX_LINE_H),
            ("Width", _BOX_TEXT_W), ("Height", _BOX_LINE_H),
            ("FontHeight", _FONT),
        ]))
    buttons_y = height - _BOX_MARGIN - _BOX_BUTTON_H
    labels = [("ok", "OK", RESULT_OK), ("cancel", "Cancel", RESULT_CANCELLED)] \
        if buttons == _OK else \
        [("yes", "Yes", RESULT_YES), ("no", "No", RESULT_NO)]
    right = width - _BOX_MARGIN
    primary = labels[0][0]
    for position, (name, label, _result) in enumerate(reversed(labels)):
        specs.append((name, service, [
            ("Label", label),
            ("PositionX", right - _BOX_BUTTON_W - position * (_BOX_BUTTON_W + _BOX_BUTTON_GAP)),
            ("PositionY", buttons_y), ("Width", _BOX_BUTTON_W),
            ("Height", _BOX_BUTTON_H), ("FontHeight", _FONT),
            # Enter answers the *primary* button, as in the office's own boxes.  It
            # is the last one placed, not the first: ``reversed`` puts the secondary
            # on the right, and marking position 0 made Enter mean Cancel - which is
            # how a box that looked perfect answered "no" to everything.
            ("DefaultButton", name == primary),
        ]))
    return specs, (width, height)


def message(ctx, text, kind="info", buttons=_OK, title=TITLE):
    """Show a modal message box; returns RESULT_OK / RESULT_YES / RESULT_NO / 0.

    ``Toolkit.createMessageBox`` cannot be used: on this office it is
    ``XToolkit2::createMessageBox`` with **five** parameters
    ``(XWindowPeer, MessageBoxType, long, string text, string title)``, and the
    four-argument call ``XToolkit`` had up to LibreOffice 7.x raises
    ``IllegalArgumentException: incorrect number of parameters passed invoking
    function createMessageBox: expected 5, got 4`` before a window exists.  With the
    fifth argument supplied a window *does* appear - and paints nothing but its OK
    button, whatever the text is (``dev/probe_message_box.py``: 400 characters of it
    produce the same empty strip), so the report "Toggle Debug Log does nothing" was
    a command that ran, flipped the state, and showed a box with no message in it.

    The box is therefore built the way the settings dialog is: a titled top-level
    ``UnoControlDialog``, one label per line of the (wrapped) text, and buttons that
    each carry their own listener (fact 31).
    """
    box = None
    try:
        box = _build_box(ctx, text, kind, buttons, title)
        _show_box(box["dialog"], ctx, title)
        _listen_for_keys(box, ctx)          # the peer exists only now
        box["dialog"].execute()
        box["dialog"].setVisible(False)
    except Exception:
        # Never let a reporting problem swallow the real error - but say so.
        config.log(ctx, "message box failed: %s" % traceback.format_exc())
        return RESULT_CANCELLED
    finally:
        if box is not None:
            try:
                box["dialog"].dispose()
            except Exception:
                pass
    return box["state"]["result"]


def _build_box(ctx, text, kind, buttons, title):
    """The box with its controls and listeners, without the modal loop.

    Split out of :func:`message` because a modal box cannot be looked at from the
    inside: ``execute()`` blocks until somebody answers it, so which code each
    button answers with was invisible to the suite - and that is exactly where a
    ``DefaultButton`` sitting on Cancel instead of OK turns a box that looks perfect
    into one that says "no" to Enter.  ``press(name)`` is what a button's listener
    calls; a test can call the same thing.

    Returns ``{"dialog", "model", "state", "press", "press_key", "key", "kept",
    "size"}``.
    """
    # com.sun.star is imported here, not at the top: the extension manager
    # imports this module while registering it, where those imports fail (fact 3)
    import unohelper
    from com.sun.star.awt import XActionListener, XKeyListener
    manager = ctx.ServiceManager
    dialog = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    dialog.setModel(model)
    specs, (width, height) = box_specs(text, kind, buttons, title)
    for property_name, value in (("Width", width), ("Height", height)):
        try:
            model.setPropertyValue(property_name, value)
        except Exception:
            pass
    for name, service, props in specs:
        # the model has to come from the dialog model itself (fact 25)
        control_model = model.createInstance(service)
        _apply(control_model, props, [], name)
        model.insertByName(name, control_model)

    state = {"result": RESULT_CANCELLED}
    results = {"ok": RESULT_OK, "cancel": RESULT_CANCELLED,
               "yes": RESULT_YES, "no": RESULT_NO}
    primary = RESULT_OK if buttons == _OK else RESULT_YES
    secondary = RESULT_CANCELLED if buttons == _OK else RESULT_NO
    kept = []

    def answer(result):
        config.log(ctx, "box answered %d" % result)
        state["result"] = result
        try:
            dialog.endExecute()
        except Exception:
            pass

    class Press(unohelper.Base, XActionListener):
        """One listener per button (fact 31): deciding from
        ``event.Source.Model.Name`` has been seen to fail silently."""

        def __init__(self, result):
            self.result = result

        def actionPerformed(self, event):
            answer(self.result)

        def disposing(self, event):
            pass

    class Key(unohelper.Base, XKeyListener):
        """Return answers the primary button, Escape the secondary one.

        ``UnoControlDialog`` highlights its default button but does not act on it,
        so without this the only way out of a message the extension showed was to
        find OK with the mouse - and a box the user cannot close looks exactly like
        an office that has stopped answering.
        """

        def keyReleased(self, event):
            if event.KeyCode == _KEY_RETURN:
                answer(primary)
            elif event.KeyCode == _KEY_ESCAPE:
                answer(secondary)

        def keyPressed(self, event):
            pass

        def disposing(self, event):
            pass

    for name, result in results.items():
        try:
            control = dialog.getControl(name)
        except Exception:
            continue
        if control is None:
            continue
        listener = Press(result)
        control.addActionListener(listener)
        kept.append((control, listener))
    return {"dialog": dialog, "model": model, "state": state,
            "press": lambda name: answer(results[name]),
            "press_key": lambda code: answer(primary if code == _KEY_RETURN
                                             else secondary),
            "key": Key(), "kept": kept, "size": (width, height)}


def _listen_for_keys(box, ctx):
    """Attach the Return/Escape listener - after ``_show_box``, not before.

    Asking for the peer before ``createPeer`` answers None, so a listener attached
    at build time went nowhere and the box answered Enter only because the office
    acts on ``DefaultButton`` itself.
    """
    try:
        peer = box["dialog"].getPeer()
    except Exception:
        return
    if peer is None:
        return
    try:
        peer.addKeyListener(box["key"])
        box["kept"].append((peer, box["key"]))
    except Exception:
        config.log(ctx, "message box keys: %s" % traceback.format_exc())


def _show_box(dialog, ctx, title):
    """Attach the peer, the title and the position; the box is then ready to run."""
    try:
        dialog.createPeer(_toolkit(ctx), None)     # its own top-level window
    except Exception:
        dialog.createPeer(_toolkit(ctx), _parent_window(ctx))
    try:
        dialog.setTitle(title)
    except Exception:
        pass                     # fact 32: setTitle, never setPropertyValue("Title")
    centre(dialog, ctx)


def confirm(ctx, text):
    return message(ctx, text, "warning", _YES_NO) == RESULT_YES


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
# roughly 450 x 370 px, the same magnitude the shipped wizards use
# (``wizards/ui/PathSelection.py`` gives a label ``Height=8``).
_MARGIN = 10
_LABEL_X = _MARGIN
_LABEL_W = 80
_FIELD_X = _LABEL_X + _LABEL_W + 4
_FIELD_W = 46
_SWATCH_X = _FIELD_X + _FIELD_W + 4
_SWATCH_W = 22
_FIRST_ROW_Y = 12
_ROW_GAP = 9                     # clear space between one row and the next
_LABEL_H = 10
_FIELD_H = 15
_ROW_STEP = _FIELD_H + _ROW_GAP  # a row is its field plus the gap under it
_LABEL_OFFSET = 2                # label sits slightly below the field's top
_BUTTON_W = 34
_BUTTON_H = 18
_BUTTON_GAP = 4
DIALOG_WIDTH = _SWATCH_X + _SWATCH_W + _MARGIN
_BUTTON_Y = _FIRST_ROW_Y + len(_ROWS) * _ROW_STEP + _ROW_GAP
DIALOG_HEIGHT = _BUTTON_Y + _BUTTON_H + _MARGIN
_OK_X = DIALOG_WIDTH - 2 * _BUTTON_W - _BUTTON_GAP - _MARGIN
_CANCEL_X = _OK_X + _BUTTON_W + _BUTTON_GAP
_FONT = 12
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
            ("Label", label), ("PositionX", _LABEL_X),
            ("PositionY", y + _LABEL_OFFSET),
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
            # a button, not a label: clicking the swatch is what opens the
            # palette picker, the way the arrow opens the font-colour dropdown
            specs.append(("swatch" + name, _BUTTON, [
                ("Label", " "), ("PositionX", _SWATCH_X), ("PositionY", y),
                ("Width", _SWATCH_W), ("Height", _FIELD_H),
                ("BackgroundColor", config.hex_to_color(values[name], 0)),
                ("HelpText", "Pick a colour from a palette"),
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


def centre(dialog, ctx):
    """Put ``dialog`` in the middle of the frame it belongs to.

    ``setPosSize`` does move the window, it only does nothing about its size, so
    the position is set here in the peer's own coordinate system - the same one
    ``wizards/ui/UnoDialog.py`` centres its dialogs in.  The colour picker needs it
    as much as the settings dialog does: a popup nobody positioned lands at 0,0,
    which puts its palette selector above the top of the screen.
    """
    area = None
    parent = _parent_window(ctx)
    if parent is not None:
        try:
            area = parent.getPosSize()
        except Exception:
            area = None
    if area is None:
        return
    size = dialog.getPosSize()
    x = max(0, area.X + (area.Width - size.Width) // 2)
    y = max(0, area.Y + (area.Height - size.Height) // 2)
    try:
        dialog.setPosSize(x, y, size.Width, size.Height, _POS)
    except Exception:
        pass


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
        centre(self.dialog, self.ctx)

    def _preselect_master(self):
        """Deprecated shim: the selection is part of the model now.

        ``SelectedItems`` set on an *inserted* child never reaches the peer, so it
        has to travel with the control model - see ``_field_specs`` and
        ``dev/debug_dialog_masters.py``.  Kept so older callers are harmless.
        """
        return _master_index(self.values, self.masters)

    # -- interaction ------------------------------------------------------- #
    def _press(self, name):
        if name.startswith("swatch:"):
            self._pick_colour(name.split(":", 1)[1])
            return                      # the dialog stays open, of course
        self.accepted = name == "ok"
        self.rejected = not self.accepted
        try:
            self.dialog.endExecute()
        except Exception:
            pass

    def _pick_colour(self, name):
        """Open the palette picker for one of the two colour rows.

        The deck's own colours come first, then the recently picked ones, then
        the palettes of the installation: the order is the order in which a
        colour is likely to be wanted, and it is why the picker is ours rather
        than a plain hex box.
        """
        # An exception here would otherwise vanish: it is raised inside a
        # listener, and the office does not carry a Python traceback across
        # that boundary, so a broken picker looks exactly like a dead swatch.
        from plan_impress import palettes, picker
        # the field is named after the setting it edits, minus the underscore
        setting = {"MutedColor": "muted_color", "TextColor": "text_color"}[name]
        try:
            current = config.hex_to_color(self._text(name),
                                          self.settings.get(setting, 0))
            # the deck's colours then the installation's palettes: the order is the
            # order in which a colour is likely to be wanted.  The recent colours
            # are *not* another palette - the office's own dropdown shows them as a
            # captioned group above the grid, and that is what ``recent`` is for.
            entries = []
            document = _current_document(self.ctx)
            if document is not None:
                entries += palettes.deck_palette(document)
            recent = palettes.recent_palette(self.settings)
            entries += palettes.load_palettes(self.ctx)
            config.log(self.ctx, "pick %s: %06X from %s (+%d recent)"
                       % (name, current, [n for n, _c in entries],
                          len(recent[0][1]) if recent else 0))
            chosen = picker.pick(self.ctx, entries, current,
                                 title="Pick a Colour", recent=recent)
        except Exception:
            config.log(self.ctx, "pick failed:\n%s" % traceback.format_exc())
            config.log_error(self.ctx, "pick %s failed" % name)
            return
        config.log(self.ctx, "pick answer: %s" % (chosen,))
        if chosen is None:
            return
        self.values[name] = config.color_to_hex(chosen)
        try:
            self.control(name).setText(self.values[name])
        except Exception:
            self.control_model(name).setPropertyValue("Text", self.values[name])
        self._refresh_swatch(name)
        config.remember_colour(self.settings, chosen)

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
            swatch = self.control("swatch" + field)
            listener = Buttons("swatch:" + field)
            swatch.addActionListener(listener)
            self._listeners.append((swatch, listener))

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
            # config.save() writes every known key, so anything not carried here
            # is silently reset: the colours picked during this session live in
            # self.settings and have to travel back with the rest
            "recent_colors": list(self.settings.get("recent_colors") or []),
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


def _current_document(ctx):
    """The presentation the picker should borrow colours from, or None.

    The settings are per profile and do not need a document, so this may well
    answer None; the picker then simply has fewer palettes to offer.
    """
    try:
        component = ctx.getByName("/singletons/com.sun.star.frame.theDesktop")\
            .getCurrentComponent()
        component.DrawPages                 # only a presentation answers this
    except Exception:
        return None
    return component


def open_settings(ctx, settings, masters):
    """Modal settings editor; returns a settings dict, or ``None`` on cancel."""
    return SettingsDialog(ctx, settings, masters).run()
