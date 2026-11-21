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

from plan_impress import config, core, swatch

TITLE = "Plan Impress"

#: The two shapes a message box comes in, in the tokens the office's own
#: ``MessageBoxButtons`` uses: 1 for OK, 5 for Yes/No (fact 32).  ``message`` no
#: longer calls ``createMessageBox`` at all (fact 71), so these are only how a
#: caller says how many buttons it wants.
_OK = 1
_YES_NO = 5


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
_BOX_MARGIN = 14                   # air all round: above and left of the text, and
                                   # below and right of the buttons
_BOX_LINE_H = 9                    # one line of _FONT text, with air
_BOX_BUTTON_W = 26
_BOX_BUTTON_H = 18
_BOX_BUTTON_GAP = 4
_BOX_GAP = 12                      # between the last line of text and the buttons
_BOX_CHARS = 36                    # the most characters to put on one line
_BOX_TEXT_MIN_W = 60               # the narrowest box worth opening, whatever it says
_BOX_TEXT_MAX_W = 200              # the widest: past that it stops looking like a
                                   # message and starts looking like a form
_BOX_TEXT_PAD = 6                  # air between the last glyph and the edge of the box

#: What one character of the box's font costs, in px, **per class of character** -
#: ``dev/probe_message_width.py`` photographs thirty of each at ``_FONT``: 8.93 px a
#: lower case ``a``, 9.93 px a digit, 13.90 px an ``M``, 12.33 px across ``MWI@``, 8.30
#: px an accented letter, 5.93 px a slash and 7.9 px the log path itself.  They are
#: rounded *up* by about 5 %: a ``FixedText`` wraps nothing (fact 72), so a line one
#: pixel too long is not wrapped, it is painted past the edge of its label and the tail
#: of the path never appears - the report "the debug log enable/disable window message
#: has not enough width, the message is cut (incomplete path)".  One number for every
#: character is what made that report come back a second time: the box had been sized on
#: a path, the narrowest thing a message contains, and the line it cut
#: (``/home/derumigny/Documents/plan-impre``) is 311 px of ink because of one capital -
#: 8.64 px a character, where the constant said 7.8.  Nothing on a peer has text metrics
#: to ask (fact 46), so these are the measurement.
_BOX_LOWER_W = 9.2
_BOX_DIGIT_W = 10.5
_BOX_CAP_W = 14.5

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


def text_px(line):
    """What ``line`` costs of ink, in px, at ``_FONT``.

    Three classes of character and no more, because those are the three the probe can
    photograph thirty of at a time (``dev/probe_message_width.py``); a space counting as
    a lower case letter is the same width, and being wrong about it by a pixel a
    character costs nothing but a slightly wider box, which is the safe direction.
    """
    return sum(_BOX_CAP_W if character.isupper()
               else _BOX_DIGIT_W if character.isdigit()
               else _BOX_LOWER_W for character in line)


def _break_long(line):
    """Split a line whose ink is wider than the widest box worth opening.

    ``_BOX_CHARS`` bounds a line in *characters*, which is the readable measure, and
    ``_BOX_TEXT_MAX_W`` bounds the box in *px*, which is the honest one: 36 characters of
    a path are 280 px and 36 capitals are 520 px.  A line that cannot be given a box is
    broken here rather than painted past its edge (fact 72), which is where the tail of a
    log path went the first time this was reported.

    The pieces are cut even rather than filled greedily: a greedy split leaves a
    two-character crumb on the last line, and a name or a path broken into ``XX`` says
    nothing to anybody.
    """
    budget = _BOX_TEXT_MAX_W * swatch.PX_PER_UNIT_X
    ink = text_px(line)
    if ink <= budget:
        return [line]
    pieces = -(-int(ink) // int(budget))                 # ceil, without importing math
    size = -(-len(line) // pieces)
    return [line[start:start + size] for start in range(0, len(line), size)]


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
        for line in textwrap.wrap(paragraph, width, break_long_words=True,
                                  break_on_hyphens=False) or [""]:
            lines += _break_long(line)
    return lines


def box_text_width(lines):
    """How wide the labels have to be for the widest of ``lines``, in dialog units.

    The box is as wide as the words it has to show, between ``_BOX_TEXT_MIN_W`` (so a
    three-word confirmation still looks like a window) and ``_BOX_TEXT_MAX_W`` (so a long
    one still looks like a message).  Making this a constant is what cut the log path:
    one width for every message is one width measured on the wrong string.
    """
    widest = max([text_px(line) for line in lines] or [0])
    units = (widest + 2) / swatch.PX_PER_UNIT_X + _BOX_TEXT_PAD
    return int(max(_BOX_TEXT_MIN_W, min(_BOX_TEXT_MAX_W, units)))


def box_size(text):
    """``(width, height)`` of the box for ``text``, in dialog units."""
    lines = box_lines(text)
    return (2 * _BOX_MARGIN + box_text_width(lines),
            2 * _BOX_MARGIN + len(lines) * _BOX_LINE_H + _BOX_GAP + _BOX_BUTTON_H)


def box_specs(text, buttons):
    """The box's controls as ``(name, service, [(property, value)])``.

    Split out from the UNO calls so the geometry can be tested without a display,
    the way ``dialog._field_specs`` and ``picker._field_specs`` are.  There is no
    *kind* of box any more: the office's ``MessageBoxType`` went with
    ``createMessageBox`` (fact 71), and a warning is an information box with the
    same words in it.
    """
    width, height = box_size(text)
    lines = box_lines(text)
    text_w = box_text_width(lines)
    service = "com.sun.star.awt.UnoControlButtonModel"
    specs = []
    for index, line in enumerate(lines):
        specs.append(("text%d" % index, _FIXED_TEXT, [
            ("Label", line), ("PositionX", _BOX_MARGIN),
            ("PositionY", _BOX_MARGIN + index * _BOX_LINE_H),
            ("Width", text_w), ("Height", _BOX_LINE_H),
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


def message(ctx, text, buttons=_OK, title=TITLE):
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
        box = _build_box(ctx, text, buttons, title)
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


def _build_box(ctx, text, buttons, title):
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
    specs, (width, height) = box_specs(text, buttons)
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
    return message(ctx, text, _YES_NO) == RESULT_YES


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

#: The rows the section label adds, in the same ``(name, label, kind)`` shape as
#: :data:`_ROWS`.  Everything here is optional in the same sense as the master slide
#: setting: an empty field means "ask the deck", which is what a deck nobody has styled
#: gets.
#:
#: They are called *Default …* because that is what they are: *Insert Section Titles*
#: copies the position and the look of the first section slide's own box, so a value here
#: is used only when there is nothing to copy - a deck nobody has styled, or one whose
#: boxes were just removed.  Saying so in the label is what replaced the toggle: a field
#: that silently does nothing is the sort of thing that reads as "the option does not
#: work".  The wording has to fit the 202 px the label box paints - a `FixedText` wraps
#: nothing (fact 72) - so it is no longer than the wording it replaced, and the unit each
#: field holds is part of its name because the file keeps 1/100 mm while the fields speak
#: centimetres (fact 93).
#:
#: ``position`` is one row with three fields - X, Y and the width - because that is how
#: Impress's own *Position and Size* dialog shows them; one line of conversion
#: (`cm_to_units`) joins the two units.
_SECTION_ROWS = (
    ("SectionColor", "Default colour (hex):", "colour"),
    ("SectionFont", "Default font:", "font"),
    ("SectionSize", "Default size (pt):", "text"),
    ("SectionPosition", "Default X, Y, W (cm):", "position"),
)

#: What the four fields are for, said where a user will read it.
_DEFAULT_HELP = ("The command copies the position and the look of the first section "
                 "slide's own box.  This is what a box is drawn with when there is "
                 "nothing to copy: no box on any section slide yet.")

#: The three fields of the position row: ``(setting, what it is called on screen)``.
_POSITION_FIELDS = (("SectionX", "X"), ("SectionY", "Y"), ("SectionWidth", "W"))

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
#: The colour beside a hex field is **the same square** as one of the chooser's grid,
#: sized by the same rule: a dialog unit is 2.53 x 2.39 px (fact 28), so a control is
#: square on the screen only at ``w`` x :func:`swatch.square_units` (this used to be
#: 22 x 12 units - 56 x 29 px, a strip rather than the swatch the comment promised:
#: "the color sample must be exact squares, not rectangles").
_SWATCH_W = 13
_SWATCH_H = swatch.square_units(_SWATCH_W)
_FIRST_ROW_Y = 12
_ROW_GAP = 9                     # clear space between one row and the next
_LABEL_H = 10
_FIELD_H = 15
_ROW_STEP = _FIELD_H + _ROW_GAP  # a row is its field plus the gap under it
_LABEL_OFFSET = 2                # label sits slightly below the field's top
_BUTTON_W = 34
_BUTTON_H = 18
_BUTTON_GAP = 4
#: The position row's three fields (X, Y and the width, in centimetres) and the
#: letter in front of each.  They share one row because they are one decision -
#: where the box goes - and because the alternative is three more rows in a dialog
#: that is already nine rows tall.
_NUM_W = 20
_NUM_LABEL_W = 7
_NUM_GAP = 3
_POSITION_END = (_FIELD_X + len(_POSITION_FIELDS) * (_NUM_LABEL_W + _NUM_W)
                 + (len(_POSITION_FIELDS) - 1) * _NUM_GAP)
DIALOG_WIDTH = max(_SWATCH_X + _SWATCH_W, _POSITION_END) + _MARGIN
_BUTTON_Y = _FIRST_ROW_Y + (len(_ROWS) + len(_SECTION_ROWS)) * _ROW_STEP + _ROW_GAP
DIALOG_HEIGHT = _BUTTON_Y + _BUTTON_H + _MARGIN
_OK_X = DIALOG_WIDTH - 2 * _BUTTON_W - _BUTTON_GAP - _MARGIN
_CANCEL_X = _OK_X + _BUTTON_W + _BUTTON_GAP
_FONT = 12
_COLOUR_FIELDS = ("MutedColor", "TextColor", "SectionColor")
#: Which setting each colour field edits - the picker needs it to remember the
#: colour and to know what to show when it opens.
_COLOUR_SETTINGS = {"MutedColor": "muted_color", "TextColor": "text_color",
                    "SectionColor": "section_color"}
_POS = 1                     # com.sun.star.awt.PosSize.POS

#: What a colour is painted **on**.  It used to be a button - the obvious control for a
#: colour one clicks - and the office then paints the button with its theme's raised
#: bevel, dark above and to the left and light below and to the right: the
#: "perspective-style border around the color" that was reported, in the palette and in
#: this dialog alike.  A button model has no ``Border``/``BorderColor`` at all to switch
#: it off with (fact 65).  A label paints a colour flat and can be given a line, but
#: only the theme's own: every ``BorderStyle`` from 0 to 6 paints ``#2B2E39`` on this
#: dark theme and ``BorderColor`` is accepted and ignored in all of them
#: (``dev/probe_border_colour.py``), so a dark colour had no edge to see.  What is
#: painted is therefore an image control carrying a bitmap :mod:`plan_impress.swatch`
#: draws - the colour inside a one-pixel line of the contrast colour, as the office's own
#: line-colour dropdown draws its swatches - and the line is *ours* because it is drawn,
#: not asked for.  Neither kind has an action source, so a click on a colour arrives as
#: ``mouseReleased`` (fact 79).
_IMAGE = "com.sun.star.awt.UnoControlImageControlModel"

_FIXED_TEXT = "com.sun.star.awt.UnoControlFixedTextModel"
_EDIT = "com.sun.star.awt.UnoControlEditModel"
_LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"
_BUTTON = "com.sun.star.awt.UnoControlButtonModel"
#: The font field is an **editable** combo, not a list: the user has to be able to
#: type a name the list does not carry, and the field is empty for "the deck's own".
#: Both of these model services come out of the dialog model's own factory, unlike
#: the panel and the message box (fact 65) - ``dev/probe_fonts.py`` prints which
#: properties each has.
_COMBOBOX = "com.sun.star.awt.UnoControlComboBoxModel"


def font_names(descriptors):
    """The family names of ``awt.FontDescriptor`` structs, sorted, no duplicates.

    The office reports one descriptor **per face**, so 4701 of them here come down to
    2835 families; a dropdown of styles would be unreadable.
    """
    names, seen = [], set()
    for descriptor in descriptors or ():
        try:
            name = str(descriptor.Name)
        except Exception:
            continue
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    names.sort(key=str.lower)
    return names


def installed_fonts(ctx):
    """The font families the office can paint with, or ``[]``.

    There is no font-list *service* to ask - ``com.sun.star.awt.Toolkit`` has no
    ``getDeviceFontEnumeration`` and a frame's container window has no peer at all
    (``dev/probe_fonts.py`` prints what each of the plausible routes answers) - but
    **a window peer** answers ``getFontDescriptors()`` with one
    ``com.sun.star.awt.FontDescriptor`` per face.  The settings dialog reads them
    from its *own* peer (:meth:`SettingsDialog._fill_fonts`); this is the route for
    a caller that has no window, and it is the one that must not be used while a
    menu popup is on screen - a second top-level peer then wedges the client.
    """
    dialog = None
    try:
        toolkit = _toolkit(ctx)
        manager = ctx.ServiceManager
        dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", ctx)
        model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", ctx)
        dialog.setModel(model)
        dialog.createPeer(toolkit, None)
        descriptors = dialog.getPeer().getFontDescriptors()
    except Exception:
        return []
    finally:
        if dialog is not None:
            try:
                dialog.dispose()
            except Exception:
                pass
    return font_names(descriptors)


def _master_index(values, masters):
    """Which entry of the master list to show: the saved one, else the first."""
    wanted = str(values.get("master") or "")
    return masters.index(wanted) if wanted in masters else 0


def cm_to_units(text):
    """What the field says in centimetres, as the 1/100 mm ``core`` works in.

    ``None`` for empty, rubbish and a negative number, all of which mean "ask the
    deck" - the same thing an empty master-slide field means, and the reason a
    half-typed value must not put the box at 0,0.
    """
    text = str(text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value < 0:       # NaN or a negative length
        return None
    return int(round(value * 1000.0))


def units_to_cm(value):
    """One of those lengths, back into the field.  ``""`` = the deck's own."""
    length = core.config_length(value)
    if length is None:
        return ""
    return ("%.2f" % (length / 1000.0)).rstrip("0").rstrip(".")


def point_text(value):
    """A point size for its field; ``""`` means "the size the deck paints with"."""
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    if size != size or size <= 0:
        return ""
    return ("%.1f" % size).rstrip("0").rstrip(".")


def _hex_value(value, fallback):
    """A colour for a hex field, with the default standing in for a missing one.

    ``config.load`` guarantees a number, but the dialog is also built by the tests
    from a hand-made dict, and a section box whose colour is unset is a normal case.
    """
    if value is None:
        value = fallback
    try:
        return config.color_to_hex(int(value))
    except (TypeError, ValueError):
        return config.color_to_hex(fallback)


def _field_specs(values, masters, fonts=None):
    """The control description as ``(name, model service, properties)`` triples.

    Kept separate from UNO object creation so the tests can assert on the
    layout - every control's rectangle, and therefore the absence of overlap -
    without a display.
    """
    specs = []

    def label(name, text, y):
        specs.append(("label" + name, _FIXED_TEXT, [
            ("Label", text), ("PositionX", _LABEL_X),
            ("PositionY", y + _LABEL_OFFSET),
            ("Width", _LABEL_W), ("Height", _LABEL_H), ("FontHeight", _FONT),
        ]))

    def field(name, service, props, y, width=_FIELD_W):
        specs.append((name, service, props + [
            ("PositionX", _FIELD_X), ("PositionY", y), ("Width", width),
            ("Height", _FIELD_H), ("FontHeight", _FONT),
        ]))

    def swatch_of(name, y, colour):
        # the same square as one of the picker's grid, drawn the same way: the
        # colour inside a line of the contrast colour, which is what the report
        # asked for ("see the office's own palette"), and clicking it opens the
        # palette picker either way - the way the arrow opens the font-colour
        # dropdown.  The bitmap itself is given by _refresh_swatch, which is the
        # half that needs the office; this half stays a description.
        specs.append(("swatch" + name, _IMAGE, [
            ("PositionX", _SWATCH_X), ("PositionY", y - (_SWATCH_H - _FIELD_H) // 2),
            ("Width", _SWATCH_W), ("Height", _SWATCH_H),
            ("HelpText", "Pick a colour from a palette"),
        ] + swatch.swatch_props(colour)))

    for index, (name, text) in enumerate(_ROWS):
        y = _FIRST_ROW_Y + index * _ROW_STEP
        label(name, text, y)
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
        field(name, service, props, y)
        if name in _COLOUR_FIELDS:
            swatch_of(name, y, config.hex_to_color(values[name], 0))

    for index, (name, text, kind) in enumerate(_SECTION_ROWS):
        y = _FIRST_ROW_Y + (len(_ROWS) + index) * _ROW_STEP
        if kind != "position":
            label(name, text, y)
        if kind == "colour":
            field(name, _EDIT, [("Text", values.get(name, "")),
                                ("HelpText", _DEFAULT_HELP)], y)
            swatch_of(name, y, config.hex_to_color(values.get(name, ""), 0))
        elif kind == "font":
            # an editable combo: the office's own font list when the office will
            # say it (``installed_fonts``, fact 62's "the API is not there to be
            # asked" applies to a *font picker*, not to the list), and any name
            # typed into the box otherwise - which is what an empty setting means
            field(name, _COMBOBOX, [
                ("StringItemList", tuple(fonts or ())), ("Dropdown", True),
                ("Text", str(values.get(name) or "")),
                ("HelpText", "Leave empty for the font the deck's body text uses. "
                             + _DEFAULT_HELP),
            ], y)
        elif kind == "text":
            field(name, _EDIT, [
                ("Text", str(values.get(name, ""))),
                ("HelpText", "Leave empty for the size the deck's body text uses. "
                             + _DEFAULT_HELP),
            ], y)
        else:                                        # the three position fields
            # the row's caption is named after the *first* of its three fields, so
            # the rule "every label has a field beside it" stays checkable
            label(_POSITION_FIELDS[0][0], text, y)
            x = _FIELD_X
            for which, caption in _POSITION_FIELDS:
                specs.append(("caption" + which, _FIXED_TEXT, [
                    ("Label", caption), ("PositionX", x),
                    ("PositionY", y + _LABEL_OFFSET), ("Width", _NUM_LABEL_W),
                    ("Height", _LABEL_H), ("FontHeight", _FONT),
                ]))
                specs.append((which, _EDIT, [
                    ("Text", str(values.get(which, ""))),
                    ("HelpText", "In centimetres; empty = where the deck's own "
                                 "content box is. " + _DEFAULT_HELP),
                    ("PositionX", x + _NUM_LABEL_W), ("PositionY", y),
                    ("Width", _NUM_W), ("Height", _FIELD_H), ("FontHeight", _FONT),
                ]))
                x += _NUM_LABEL_W + _NUM_W + _NUM_GAP

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

    def __init__(self, ctx, settings, masters, fonts=None):
        self.ctx = ctx
        self.settings = dict(settings)
        self.masters = [str(m) for m in masters] or [""]
        self.values = {
            "MutedColor": config.color_to_hex(settings["muted_color"]),
            "TextColor": config.color_to_hex(settings["text_color"]),
            "Title": settings["title"],
            "master": settings["master"],
            # the section box: every one of these may be empty, and empty means
            # "the deck's own", which is what keeps a generated box looking like
            # the deck it was generated into
            "SectionColor": _hex_value(settings.get("section_color"),
                                       config.DEFAULT_SECTION_COLOR),
            "SectionFont": settings.get("section_font") or "",
            "SectionSize": point_text(settings.get("section_size")),
            "SectionX": units_to_cm(settings.get("section_x")),
            "SectionY": units_to_cm(settings.get("section_y")),
            "SectionWidth": units_to_cm(settings.get("section_width")),
        }
        self.dialog = None
        self.model = None
        self.window = None
        self.accepted = False
        self.rejected = False
        self._listeners = []
        self._warnings = []
        #: The names for the font combo, read from the office the first time the
        #: dialog is built (:func:`installed_fonts`); a caller may hand its own list.
        self._fonts = list(fonts) if fonts is not None else None
        #: Whether the office's theme is dark, which decides the colour of the line
        #: drawn round the two swatches (:func:`plan_impress.swatch.ring_colour`).
        self._dark = swatch.theme_is_dark(ctx)

    @property
    def fonts(self):
        """The names the font dropdown offers; empty until the peers exist."""
        return list(self._fonts or [])

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
        for name, service, props in _field_specs(self.values, self.masters,
                                                 self._fonts):
            control_model = self._new_control_model(service)
            _apply(control_model, props, self._warnings, name)
            self.model.insertByName(name, control_model)
        # the swatches are *drawn*, not coloured, so they want their bitmap as soon as
        # they exist: the specs describe the control, and the office makes the picture
        for field in _COLOUR_FIELDS:
            self._refresh_swatch(field)
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
        self._fill_fonts()

    def _fill_fonts(self):
        """Give the font dropdown the office's own list, from **this** dialog's peer.

        The names can only be asked of a window peer (:func:`installed_fonts` says
        what the other routes answer), and a control's geometry is frozen once its
        peer exists (fact 70) - but its *words* are not: writing ``StringItemList``
        afterwards reaches the control and the value typed into the box survives,
        which ``dev/probe_font_items.py`` measures as itemCount 0 → 3.

        Creating a peer of one's own to ask is the wrong answer here: while a menu
        popup holds the pointer grab, a second top-level window wedges the client
        and nothing at all comes back - which is how the settings dialog came to
        hang before it was ever shown.
        """
        if self._fonts is not None:
            return                      # the caller said what to offer
        try:
            descriptors = self.dialog.getPeer().getFontDescriptors()
        except Exception:
            self._fonts = []
            return
        self._fonts = font_names(descriptors)
        if not self._fonts:
            return
        try:
            self.control_model("SectionFont").setPropertyValue(
                "StringItemList", uno.Any("[]string", tuple(self._fonts)))
        except Exception:
            return
        self._repaint("SectionFont")

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
        setting = _COLOUR_SETTINGS[name]
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
        """Put what the field says on its swatch: the colour, and the line round it.

        Both halves are written.  ``BackgroundColor`` is the colour underneath - and the
        whole of what shows when no bitmap can be made - while ``Graphic`` is the
        bitmap painted over it, which is where the contrast line lives
        (:mod:`plan_impress.swatch`).  A control takes a new bitmap after its peer
        exists (``dev/probe_swatch_ring.py`` photographs the change), so typing a hex
        value moves the swatch with it; the peer then has to be told
        (:meth:`_repaint`), because a model written silently is not a model painted.
        """
        text = None
        try:
            text = self.control(name).getText()      # what is in the field right now
        except Exception:
            pass
        if text is None:
            text = self.values.get(name, "000000")   # before the peers exist: the value
        try:
            colour = config.hex_to_color(text, 0)
        except Exception:
            return
        try:
            model = self.control_model("swatch" + name)
        except Exception:
            return
        if model is None:
            return
        try:
            model.setPropertyValue("BackgroundColor", colour)
            model.setPropertyValue("Tag", config.color_to_hex(colour))
        except Exception:
            pass
        width, height = swatch.bitmap_size(_SWATCH_W, _SWATCH_H)
        made = swatch.graphic(self.ctx, colour, width, height,
                              swatch.ring_colour(colour, self._dark))
        if made is not None:
            try:
                model.setPropertyValue("Graphic", made)
            except Exception:
                pass
        self._repaint("swatch" + name)

    def _repaint(self, name):
        """Tell one control's peer that its model no longer says what it painted.

        Writing a model property does not by itself repaint anything: the picker's
        read-out kept the colour the dialog was opened with however often the pointer
        moved, until the control's *own* peer was invalidated with ``3`` (``ALL``) -
        fact 75.  A swatch that keeps showing the old colour while the field beside it
        says another is a lie about the setting that is about to be saved.
        """
        try:
            self.control(name).getPeer().invalidate(3)
        except Exception:
            pass

    def _install_listeners(self):
        """Attach the button, swatch and colour listeners to the peers.

        Separate from ``run()`` so a test can fire a button event without having
        to enter the modal loop.
        """
        import unohelper
        from com.sun.star.awt import XActionListener, XMouseListener, XTextListener

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

        class Swatch(unohelper.Base, XMouseListener):
            """One instance per colour chip.

            The chip is a label, not a button, because a button is painted with the
            theme's bevel around the colour (``BORDER_LINE``) - and a label has no
            action source, so the click has to be taken from ``mouseReleased``.  It
            is wrapped because an exception raised inside a listener disappears: the
            office does not carry a traceback across that boundary, and a dead
            swatch is exactly what that looks like (fact 66).
            """

            def __init__(self, field):
                self.field = field
                # the name ``_listeners`` records this one under: the peer proxy has no
                # way back to the objects attached to it, and a test that fires a click
                # has to find the listener again
                self.name = "swatch:" + field

            def mouseReleased(self, event):
                try:
                    outer._press("swatch:" + self.field)
                except Exception:
                    config.log(outer.ctx, "swatch %s:\n%s"
                               % (self.field, traceback.format_exc()))

            def mousePressed(self, event):
                pass

            def mouseEntered(self, event):
                pass

            def mouseExited(self, event):
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
            listener = Swatch(field)
            swatch.addMouseListener(listener)
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

    def _number(self, name, fallback):
        """A point size typed into a field, or ``fallback`` when it says nothing.

        Empty is not rubbish: it means "the size the deck's body text uses", and
        ``config.load`` clamps what comes back.
        """
        try:
            text = str(self._text(name)).strip().replace(",", ".")
        except Exception:
            return fallback
        if not text:
            return 0.0
        try:
            value = float(text)
        except ValueError:
            return fallback
        return value if 0.0 <= value <= 400.0 else fallback

    def _length(self, name, fallback):
        """A centimetre field as the 1/100 mm ``core`` works in, or ``None``.

        Empty says "where the deck's own content box is"; rubbish keeps the value
        that was there, the way a half-typed hex value keeps its colour instead of
        losing it.
        """
        try:
            text = str(self._text(name)).strip()
        except Exception:
            return fallback
        if not text:
            return None
        value = cm_to_units(text)
        return value if value is not None else fallback

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
            "section_color": config.hex_to_color(
                self._text("SectionColor"), self.settings.get("section_color")),
            "section_font": self._text("SectionFont").strip(),
            "section_size": self._number("SectionSize",
                                         self.settings.get("section_size")),
            "section_x": self._length("SectionX", self.settings.get("section_x")),
            "section_y": self._length("SectionY", self.settings.get("section_y")),
            "section_width": self._length("SectionWidth",
                                          self.settings.get("section_width")),
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
