"""The colour picker: what LibreOffice's line-colour dropdown does, rebuilt.

The office offers no picker to reuse - ``ColorPicker``, ``ColorBox`` and
``ColorPickerDialog`` do not exist in ``program/types/offapi.rdb``, and the one
``ColorListBox`` string there is an Object Inspector enum literal
(``dev/probe_api.py``) - so the widget is assembled out of the same AWT control
models the settings dialog uses, and the palettes come from the office's own
``.soc`` files (:mod:`plan_impress.palettes`).

The shape copies the office's own dropdown, because that is what it has to look
like not to look like an add-on:

* a caption over each group of squares (``Recently used``, then the palette's own
  name) the way the office writes ``Theme Colors`` and ``Standard Colors``;
* a grid of squares that *touch*, ten to a row;
* a read-out under the grid that names the colour the pointer is over, its name
  and its value, which is the line the real popup grows at the bottom;
* one hex field for a colour that is in no palette - the office's ``Custom
  Color…`` opens a whole dialog for that; here it is six characters.

Clicking a colour is the answer, as in the real dropdown: no OK needed.  OK is
there for the typed hex value (Enter is OK, the button is the dialog's default),
and Cancel or Escape leaves the setting as it was.

Two measurements decided this construction (``dev/probe_paint.py``):

* a control's **paint** listener is never called, so the grid cannot be *drawn* -
  every square is a button control with its ``BackgroundColor`` set instead, which
  also makes the grid tab-focusable and keyboard activatable, which a painted grid
  would not be;
* a control's **mouse** listener *does* fire, which is what makes the hover
  read-out possible at all.
"""

import traceback

import unohelper
from com.sun.star.awt import XActionListener, XItemListener, XMouseListener, \
    XTextListener

from plan_impress import config

# --------------------------------------------------------------------------- #
# the grid
# --------------------------------------------------------------------------- #

#: Cells per row.  The office's popup is ten wide, and so is this one.
COLUMNS = 10
#: Rows of squares the grid can ever show - the recent group takes one of them.
ROWS = 6
#: The button controls that are created once and then re-pointed at the colours
#: of whatever is showing: the grid cannot be drawn (fact 64), so it is buttons.
CELLS = COLUMNS * ROWS

#: One dialog unit is about 2.5 px of peer geometry (AGENTS.md fact 28), so a cell
#: is ~23 x 18 px: the size of the office's own swatches.
CELL_W = 9
CELL_H = 7

_MARGIN = 8
_HEADER_H = 16                     # the palette selector and the pager
_HEADER_GAP = 6
_CAPTION_H = 9                     # one group caption
_GROUP_GAP = 5                     # clear air between two captioned groups
_ROW_H = 18                        # a bottom row: the read-out, or the buttons
_ROW_GAP = 5
_BUTTON_W = 26
_BUTTON_H = 18
_BUTTON_GAP = 4
_COMBO_W = 54
_PAGER_W = 10
_SWATCH_W = 14

_GRID_X = _MARGIN
_GRID_W = COLUMNS * CELL_W         # 90 units, and the squares touch
#: Where the first row of squares would start; each group's caption sits above it.
_GRID_Y = _MARGIN + _HEADER_H + _HEADER_GAP
DIALOG_WIDTH = 2 * _MARGIN + _GRID_W

#: The caption the remembered colours get, the way the office labels its groups.
RECENT_CAPTION = "Recently used"

_MODEL_BUTTON = "com.sun.star.awt.UnoControlButtonModel"
_MODEL_FIXED = "com.sun.star.awt.UnoControlFixedTextModel"
_MODEL_LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"
_MODEL_EDIT = "com.sun.star.awt.UnoControlEditModel"

#: Used when the office's palettes cannot be read at all: the picker still has
#: something to show instead of opening an empty window.
FALLBACK = [("Standard", [
    ("Black", 0x000000), ("White", 0xFFFFFF), ("Red", 0xC0504D),
    ("Orange", 0xF79646), ("Yellow", 0xFFFF00), ("Green", 0x9BBB59),
    ("Turquoise", 0x4BACC6), ("Blue", 0x4F81BD), ("Violet", 0x8064A2),
    ("Grey", 0x808080)])]


def font_height():
    """The picker writes the same size as the menus and the settings dialog."""
    from plan_impress import dialog
    return dialog._FONT


# --------------------------------------------------------------------------- #
# paging and grouping
# --------------------------------------------------------------------------- #

def recent_colours(recent):
    """The recent colours as ``[(name, colour)]``, from either shape.

    ``palettes.recent_palette()`` answers with a *palette* - ``[("Recently used",
    [...])]`` - because that is what it was while it still appeared in the palette
    list; the picker shows them as a captioned group instead, so both shapes are
    accepted and the entries are sanitised the same way ``palettes`` does: a bare
    int gets its hex value as a name, and rubbish is dropped rather than reaching
    a cell, where it would be fact 67's invisible crash.
    """
    pairs = []
    for entry in recent or []:
        if isinstance(entry, int) and not isinstance(entry, bool):
            pairs.append(("", entry))
        elif isinstance(entry, (tuple, list)) and len(entry) == 2:
            head, tail = entry
            if isinstance(tail, (list, tuple)):      # a palette entry
                for item in tail:
                    if isinstance(item, (tuple, list)) and len(item) == 2:
                        pairs.append((item[0], item[1]))
                    elif isinstance(item, int) and not isinstance(item, bool):
                        pairs.append(("", item))
            elif isinstance(tail, int) and not isinstance(tail, bool):
                pairs.append((head, tail))            # already a (name, colour)
    seen, unique = set(), []
    for name, colour in pairs:
        try:
            colour = int(colour) & 0xFFFFFF
        except (TypeError, ValueError):
            continue
        if colour in seen:
            continue
        seen.add(colour)
        unique.append((str(name) if name else config.color_to_hex(colour), colour))
    return unique[:COLUMNS]


def page_count(total, cells=CELLS):
    """How many pages of cells a palette of ``total`` colours needs."""
    return max(1, (total + cells - 1) // cells)


def page_slice(colours, page, cells=CELLS):
    """The colours of one page; an out-of-range page gives an empty list."""
    start = page * cells
    return list(colours[start:start + cells])


def page_size(recent=None):
    """How many colours fit on one page: the recent group costs a row of them.

    There is no scrollable container whose model can be created (fact 65), so the
    page has a fixed number of cells, and the row the recent colours occupy is not
    available to the palette below it.
    """
    return CELLS - (COLUMNS if recent else 0)


def grid_bands(recent, palette_name, page_colours):
    """The groups the grid draws, as ``[(caption, colours)]``, empty ones dropped.

    The office's popup labels each group of squares; the recent colours are the
    first group when there are any (``recent_colours`` caps them at one row).
    """
    bands = []
    recent = list(recent or [])[:COLUMNS]
    if recent:
        bands.append((RECENT_CAPTION, recent))
    if page_colours:
        bands.append((palette_name, list(page_colours)))
    return bands


def layout(bands, top=_GRID_Y):
    """``[(caption, colours, y, rows)]`` and the y under the whole grid.

    One place decides where every caption and every row of squares goes, so the
    grid, the read-out under it and the height of the window cannot disagree.  A
    group's ``y`` is the top of its **first row of squares**; its caption sits
    ``_CAPTION_H`` above that, so the space a group takes is its caption *plus* its
    rows - counted once, or the window ends up a caption taller than the grid.
    """
    placed = []
    bottom = top
    y = top
    for caption, colours in bands:
        rows = max(1, (len(colours) + COLUMNS - 1) // COLUMNS)
        placed.append((caption, list(colours), y, rows))
        bottom = y + rows * CELL_H
        y = bottom + _GROUP_GAP + _CAPTION_H + 1
    return placed, bottom


def cell_position(index, bands_top=_GRID_Y, rows_before=0, caption_lines=0):
    """``(x, y, width, height)`` of one cell of the grid, in dialog units.

    ``rows_before`` and ``caption_lines`` are what the rows and captions above it
    have already used up - the squares touch each other, but a caption and its air
    sit between two groups (see :func:`layout`).
    """
    row = index // COLUMNS
    column = index % COLUMNS
    return (_GRID_X + column * CELL_W,
            bands_top + caption_lines + (rows_before + row) * CELL_H,
            CELL_W, CELL_H)


def cell_name(index):
    return "cell%d" % index


def readout(name, colour):
    """What the read-out says about a colour: the office shows name and value.

    The office's dropdown prints the palette's own name for the colour and nothing
    else, so an unnamed colour is just its value: inventing the word "Colour" here
    put a stray mnemonic underline under its first letter (the first label of a
    dialog gets one, ``dev/probe_underline.py``), and the picker is meant to look
    like the office's widget, not like a labelled form field.
    """
    value = "#%s" % config.color_to_hex(colour)
    # the leading space is layout, not manners: this office underlines the first
    # character of the dialog's first label as if it were a mnemonic (the buttons
    # of a Plan dialog are drawn the same way - dev/probe_underline.py), and an
    # underline under the first glyph of the read-out looks like a stray stroke.
    # A space takes the underline and is invisible.
    return " %s  %s" % (name, value) if name else " %s" % value


# --------------------------------------------------------------------------- #
# the controls, as data
# --------------------------------------------------------------------------- #

def header_specs(palette_names, pages, page, selected=0):
    """The top row: which palette, and the pager.

    Paging because there is nothing to scroll in (fact 65) and ``freecolour-hlc``
    has 240 colours; it lives up here rather than in the button row so the bottom
    has room for the swatch, the name, the hex field and the two buttons.
    """
    font = font_height()
    single = pages <= 1
    return [
        ("palettes", _MODEL_LISTBOX, [
            ("StringItemList", tuple(palette_names)),
            ("Dropdown", True), ("PositionX", _GRID_X), ("PositionY", _MARGIN),
            ("Width", _COMBO_W), ("Height", _HEADER_H), ("FontHeight", font),
            # the selection has to travel with the model (AGENTS.md fact 30)
            ("SelectedItems", (selected,)),
            ("HelpText", "Palette"),
        ]),
        ("previous", _MODEL_BUTTON, [
            ("Label", "<"), ("PositionX", _GRID_X + _COMBO_W + _BUTTON_GAP),
            ("PositionY", _MARGIN), ("Width", _PAGER_W), ("Height", _HEADER_H),
            ("FontHeight", font), ("HelpText", "Colours before these"),
            # a one-page palette has nothing to page through: a dead button would
            # look like the picker is broken
            ("Enabled", not single),
        ]),
        ("page", _MODEL_FIXED, [
            ("Label", "%d/%d" % (page + 1, pages)),
            ("PositionX", _GRID_X + _COMBO_W + _BUTTON_GAP + _PAGER_W + _BUTTON_GAP),
            ("PositionY", _MARGIN + 3),
            ("Width", _PAGER_W + 2), ("Height", _CAPTION_H), ("FontHeight", font),
        ]),
        ("next", _MODEL_BUTTON, [
            ("Label", ">"),
            ("PositionX", _GRID_X + _GRID_W - _PAGER_W), ("PositionY", _MARGIN),
            ("Width", _PAGER_W), ("Height", _HEADER_H), ("FontHeight", font),
            ("HelpText", "Colours after these"), ("Enabled", not single),
        ]),
    ]


def caption_specs(bands):
    """The group captions at their **final** positions.

    Two labels, because there are at most two groups: the recent row and the
    palette page.  A control keeps the rectangle it was created with once its peer
    exists (measured: moving it by writing ``PositionY`` to the model afterwards
    changes the model and leaves the pixels where they were), so the position has
    to be right here; :meth:`ColourPicker._paint_cells` only changes the words.
    """
    font = font_height()
    placed, bottom = layout(bands)
    specs = []
    for index in range(2):
        if index < len(placed):
            label, y = placed[index][0], placed[index][2] - _CAPTION_H
        else:
            label, y = "", bottom           # switched off, position irrelevant
        specs.append(("caption%d" % index, _MODEL_FIXED, [
            ("Label", label), ("PositionX", _GRID_X), ("PositionY", y),
            ("Width", _GRID_W), ("Height", _CAPTION_H), ("FontHeight", font),
        ]))
    return specs


def full_bands(recent, palette_name):
    """The bands as they will *look*, with the palette page padded to a full page.

    The squares are created once, at the positions of the largest grid the picker
    can ever show - the recent row plus a full page of palette colours - because
    they cannot be moved afterwards (see :func:`caption_specs`).  What changes
    between palettes and pages is only which of them are switched on and what
    colour they are.
    """
    return grid_bands(recent, palette_name, [None] * page_size(recent))


def cell_specs(bands, current, entries=None):
    """Every square of the grid as a button control, at its final position.

    All :data:`CELLS` of them always exist and are laid out for the *largest* grid
    the picker can show - :func:`full_bands` - because a control cannot be moved
    into view later: writing ``PositionX``/``PositionY`` to the model after the peer
    exists changes the model and leaves the pixels where they were (measured with
    the caption of the second group, which stayed hidden behind the palette
    selector after being "moved").  Colours, names and visibility *do* follow the
    model, which is all a repaint needs to change.

    ``bands`` therefore says where a square is and ``entries`` - the page that is
    showing, as :meth:`ColourPicker.flat_cells` returns it - says what it is:
    the two have to come apart, because the largest grid and the current page are
    rarely the same size.  A square with no colour behind it gets no ``HelpText``:
    a cell the palette does not fill says nothing when the pointer is on it, and
    :meth:`ColourPicker._paint_cells` switches it off.
    """
    placed, bottom = layout(bands)
    specs = []
    flat = []
    for _caption, colours, y, rows in placed:
        for offset in range(rows * COLUMNS):
            x, cell_y, width, height = cell_position(offset, bands_top=y)
            entry = colours[offset] if offset < len(colours) else None
            flat.append((x, cell_y, width, height, entry))
    for index in range(CELLS):
        if index < len(flat):
            x, cell_y, width, height, entry = flat[index]
        else:
            # parked below the grid, and switched off with the rest
            x, cell_y, width, height, entry = _GRID_X, bottom, CELL_W, CELL_H, None
        if entries is not None:
            entry = entries[index] if index < len(entries) else None
        specs.append((cell_name(index), _MODEL_BUTTON, [
            ("Label", ""), ("PositionX", x), ("PositionY", cell_y),
            ("Width", width), ("Height", height),
            ("BackgroundColor", int(entry[1]) & 0xFFFFFF if entry else current),
            ("HelpText", entry[0] if entry else ""),
        ]))
    return specs


def bottom_specs(bottom, current, hex_text=None):
    """The read-out line and the button row, below the grid.

    One line says what the pointer is over - the swatch, the name and the value in
    an **editable** field, which is the office's ``Custom Color…`` in the space of
    six characters - and the row under it has the two buttons the typed value
    needs.
    """
    font = font_height()
    readout_y = bottom + _ROW_GAP
    button_y = readout_y + _ROW_H + _ROW_GAP
    return [
        # a FixedText, not a button: the chip is a label, and a button would take the
        # tab focus away from OK and Cancel for a control that does nothing.
        ("preview", _MODEL_FIXED, [
            ("Label", " "), ("PositionX", _GRID_X), ("PositionY", readout_y + 2),
            ("Width", _SWATCH_W), ("Height", _ROW_H - 4),
            ("BackgroundColor", current),
        ]),
        ("name", _MODEL_FIXED, [
            ("Label", readout("", current)),
            ("PositionX", _GRID_X + _SWATCH_W + _BUTTON_GAP),
            ("PositionY", readout_y + 4),
            ("Width", _GRID_W - _SWATCH_W - _BUTTON_GAP), ("Height", _CAPTION_H),
            ("FontHeight", font),
        ]),
        ("hex", _MODEL_EDIT, [
            ("Text", hex_text if hex_text is not None
             else config.color_to_hex(current)),
            ("PositionX", _GRID_X), ("PositionY", button_y),
            ("Width", _BUTTON_W), ("Height", _BUTTON_H), ("FontHeight", font),
            ("HelpText", "Type a colour and press Enter"),
        ]),
        ("ok", _MODEL_BUTTON, [
            ("Label", "OK"),
            ("PositionX", DIALOG_WIDTH - _MARGIN - 2 * _BUTTON_W - _BUTTON_GAP),
            ("PositionY", button_y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
            ("FontHeight", font), ("DefaultButton", True),
        ]),
        ("cancel", _MODEL_BUTTON, [
            ("Label", "Cancel"), ("PositionX", DIALOG_WIDTH - _MARGIN - _BUTTON_W),
            ("PositionY", button_y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
            ("FontHeight", font), ("DefaultButton", False),
        ]),
    ]


def dialog_height(bottom):
    """How tall the window has to be for a grid that ends at ``bottom``."""
    return bottom + _ROW_GAP + _ROW_H + _ROW_GAP + _BUTTON_H + _MARGIN


def _field_specs(palette_names, bands, pages, page, current, hex_text=None,
                 selected=0):
    """Every control of the picker, and the size of the window that holds them.

    ``(specs, (width, height))`` with ``specs`` as
    ``(name, service, [(property, value)])`` - split out from the UNO calls so the
    layout can be tested without a display, the way ``dialog._field_specs`` and
    ``dialog.box_specs`` are.

    ``bands`` is the *geometry*: what :func:`full_bands` makes, not what is showing.
    The window is a popup of one fixed shape - nothing in it is ever moved, because
    a control that is switched on later does not repaint at a position it was given
    after its peer existed.  Turning cells on and off is what makes a five-colour
    deck palette and a 240-colour ``freecolour-hlc`` both fit.
    """
    bottom = bottom_of(bands)
    specs = (header_specs(palette_names, pages, page, selected)
             + caption_specs(bands)
             + cell_specs(bands, current)
             + bottom_specs(bottom, current, hex_text))
    return specs, (DIALOG_WIDTH, dialog_height(bottom))


def bottom_of(bands):
    """The y under a list of ``[(caption, colours)]`` groups."""
    return layout(bands)[1]


# --------------------------------------------------------------------------- #
# the widget
# --------------------------------------------------------------------------- #

class ColourPicker(object):
    """A modal palette chooser; ``run()`` returns an RGB int, or None.

    ``palette_list`` is what ``palettes.load_palettes()`` returns - the office's
    own ``.soc`` tables, with ``palettes.deck_palette()`` in front if the caller
    wants the deck's colours offered first.  ``recent`` is the
    ``palettes.recent_palette()`` group: a captioned group above the grid rather
    than another palette to choose from, because that is what the office does
    with it.
    """

    def __init__(self, ctx, palette_list, current=0, title="Pick a Colour",
                 recent=None):
        self.ctx = ctx
        self.palettes = [entry for entry in (palette_list or [])
                         if entry and entry[1]] or FALLBACK
        self.recent = recent_colours(recent)
        self.current = int(current) & 0xFFFFFF
        self.title = title
        self.page = 0
        self.palette_index = 0
        self.accepted = False
        self.dialog = None
        self.model = None
        self._listeners = []
        self._warnings = []

    # -- what is showing --------------------------------------------------- #

    def palette_names(self):
        return [name for name, _colours in self.palettes]

    def colours(self):
        return self.palettes[self.palette_index][1]

    def page_cells(self):
        """The colours of the palette page, sized for the room the page has."""
        return page_slice(self.colours(), self.page, page_size(self.recent))

    def pages(self):
        return page_count(len(self.colours()), page_size(self.recent))

    def bands(self):
        """The groups to draw right now: the recent row, then this page."""
        return grid_bands(self.recent, self.palette_names()[self.palette_index],
                          self.page_cells())

    def placed(self):
        """:func:`layout` of what is showing: ``[(caption, colours, y, rows)]``."""
        return layout(self.bands())[0]

    def flat_cells(self):
        """One entry per cell index: its ``(name, colour)``, or None where empty.

        Each group is padded to whole rows, exactly as :func:`cell_specs` lays the
        cells out - otherwise the palette colours would start in the *recent* row's
        squares as soon as the recent group had fewer than ten colours, which is
        the normal case.
        """
        out = []
        for _caption, colours, _y, rows in self.placed():
            for offset in range(rows * COLUMNS):
                out.append(colours[offset] if offset < len(colours) else None)
        return out

    def geometry(self):
        """The bands the controls are built at: the grid at its largest.

        Cells and captions are created once, at the positions of a full page
        (:func:`full_bands`), because a control cannot be moved afterwards; the
        cells a given page does not use are simply switched off.
        """
        return full_bands(self.recent, self.palette_names()[self.palette_index])

    # -- construction ------------------------------------------------------ #

    def build(self):
        """Create the dialog and every control in it."""
        from plan_impress import dialog
        manager = self.ctx.ServiceManager
        self.dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", self.ctx)
        self.model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self.ctx)
        self.dialog.setModel(self.model)
        specs, (width, height) = _field_specs(
            self.palette_names(), self.geometry(), self.pages(), self.page,
            self.current, config.color_to_hex(self.current), self.palette_index)
        for property_name, value in (("Width", width), ("Height", height)):
            try:
                self.model.setPropertyValue(property_name, value)
            except Exception as error:
                self._warnings.append("dialog.%s: %s" % (property_name, error))
        for name, service, props in specs:
            # models must come from the dialog model itself (AGENTS.md fact 25)
            control_model = self.model.createInstance(service)
            dialog._apply(control_model, props, self._warnings, name)
            self.model.insertByName(name, control_model)
        return self.dialog

    def control(self, name):
        return self.dialog.getControl(name)

    def _peer(self):
        from plan_impress import dialog
        toolkit = dialog._toolkit(self.ctx)
        try:
            # its own top-level window, so it takes the focus while the settings
            # dialog waits underneath it; if that is refused, hang it off the frame
            self.dialog.createPeer(toolkit, None)
        except Exception:
            self.dialog.createPeer(toolkit, dialog._parent_window(self.ctx))
        try:
            self.dialog.setTitle(self.title)
        except Exception:
            pass
        dialog.centre(self.dialog, self.ctx)

    # -- behaviour --------------------------------------------------------- #

    def _paint_cells(self):
        """Re-point every caption, square, pager label and hex field at the page.

        Nothing here moves: cells and captions keep the rectangles they were created
        with (:meth:`geometry`), because writing ``PositionX``/``PositionY`` to a
        control's model after its peer exists changes the model and leaves the
        pixels where they were - which is how the second group's caption ended up
        painted behind the palette selector.  What a page does change is which
        squares are switched on and what colour they are, so a five-colour deck
        palette and a 240-colour ``freecolour-hlc`` both fit in one window.
        """
        flat = self.flat_cells()
        for index in range(CELLS):
            name = cell_name(index)
            control = self.control(name)
            entry = flat[index] if index < len(flat) else None
            if not entry:
                # not just empty-handed: switched off, so a square the palette does
                # not fill cannot be tabbed to or clicked as if it were a colour
                _hide(control)
                continue
            colour_name, colour = entry
            control_model = self.model.getByName(name)
            control_model.setPropertyValue("BackgroundColor", int(colour) & 0xFFFFFF)
            control_model.setPropertyValue("HelpText", colour_name)
            _show(control)
        for index, control_name in enumerate(("caption0", "caption1")):
            try:
                caption = self.placed()[index][0]
            except IndexError:
                _hide(self.control(control_name))
                continue
            self.model.getByName(control_name).setPropertyValue("Label", caption)
            _show(self.control(control_name))
        single = self.pages() <= 1
        for name in ("previous", "next"):
            try:
                self.model.getByName(name).setPropertyValue("Enabled", not single)
            except Exception:
                pass
        try:
            self.model.getByName("page").setPropertyValue(
                "Label", "%d/%d" % (self.page + 1, self.pages()))
        except Exception:
            pass
        self._refresh()

    def _refresh(self, *names):
        """Say to the window that what it painted is no longer what the models say.

        Changing a model property does not by itself invalidate the peer: after a
        palette switch the squares of the old page stayed on the screen next to the
        new ones, a cell that had been switched off stayed painted in the colour
        being edited - worse than stale, it looks like a choice - and the read-out
        under the grid kept the colour it was built with however often the pointer
        moved.  The dialog has no ``updateWindow()`` (measured: ``AttributeError``);
        its *peer* has ``invalidate()``, which wants a
        ``com.sun.star.awt.WindowPaintFlags``: ``1`` (``PAINT``) repaints that window
        alone and ``3`` (``ALL``) takes the children with it - and even ``3`` on the
        dialog left the read-out's words untouched, so each control's *own* peer is
        asked as well.  ``names`` limits the second pass to the controls that were
        just written; without arguments every control is asked, which is what a
        palette switch needs.
        """
        for flags in (3, 1):
            try:
                self.dialog.getPeer().invalidate(flags)
                break
            except Exception:
                continue
        for name in (names or self.model.ElementNames):
            control = self.control(name)
            if control is None:
                continue
            # 3 = ALL: asked for 1 (PAINT) alone, a peer repaints the window and
            # leaves the control showing what it showed before, which is how the
            # read-out kept the colour the dialog was opened with however often the
            # pointer moved over the grid.
            try:
                control.getPeer().invalidate(3)
            except Exception:
                continue

    def _show_colour(self, colour, name=""):
        """Paint the read-out: the swatch, the name, the value in the field.

        The peer has to be told afterwards - writing the models alone leaves the
        line showing the colour the dialog was opened with, however often the
        pointer moves over the grid (the ``_refresh`` at the end).
        """
        self.current = int(colour) & 0xFFFFFF
        for control_name, property_name, value in (
                ("preview", "BackgroundColor", self.current),
                ("name", "Label", readout(name, self.current)),
                ("hex", "Text", config.color_to_hex(self.current))):
            try:
                self.model.getByName(control_name).setPropertyValue(property_name,
                                                                    value)
            except Exception:
                pass
        self._refresh("preview", "name", "hex")

    def _choose_palette(self, index):
        if 0 <= index < len(self.palettes) and index != self.palette_index:
            self.palette_index = index
            self.page = 0
            self._paint_cells()

    def _turn_page(self, step):
        page = min(max(self.page + step, 0), self.pages() - 1)
        if page != self.page:
            self.page = page
            self._paint_cells()

    def _typed_colour(self):
        """The colour in the hex field; the current one when it does not say."""
        try:
            text = self.control("hex").getText()
        except Exception:
            return self.current
        return config.hex_to_color(text, self.current)

    def _press(self, name):
        if name == "ok":
            self._show_colour(self._typed_colour())
            self.accepted = True
            self.dialog.endExecute()
        elif name == "cancel":
            self.accepted = False
            self.dialog.endExecute()
        elif name == "previous":
            self._turn_page(-1)
        elif name == "next":
            self._turn_page(1)
        elif name.startswith("cell"):
            index = int(name[len("cell"):])
            cells = self.flat_cells()
            entry = cells[index] if index < len(cells) else None
            if entry:
                # one click on a colour is the answer, as in the real dropdown
                self._show_colour(entry[1], entry[0])
                self.accepted = True
                self.dialog.endExecute()

    def _hover(self, index):
        cells = self.flat_cells()
        entry = cells[index] if index < len(cells) else None
        if entry:
            self._show_colour(entry[1], entry[0])

    def _install_listeners(self):
        """One listener per control: deciding from ``event.Source.Model.Name``
        has been seen to fail (AGENTS.md fact 31), so each listener is built
        knowing which control it belongs to."""
        outer = self

        class Press(unohelper.Base, XActionListener):
            def __init__(self, name):
                self.name = name

            def actionPerformed(self, event):
                try:
                    outer._press(self.name)
                except Exception:                    # fact 66
                    config.log(outer.ctx, "picker press %s:\n%s"
                               % (self.name, traceback.format_exc()))

            def disposing(self, event):
                pass

        class Chosen(unohelper.Base, XItemListener):
            def itemStateChanged(self, event):
                try:
                    outer._choose_palette(outer._selected_palette())
                except Exception:
                    config.log(outer.ctx, "picker palette:\n%s"
                               % traceback.format_exc())

            def disposing(self, event):
                pass

        class Hovered(unohelper.Base, XMouseListener):
            def __init__(self, index):
                self.index = index

            def mouseEntered(self, event):
                try:
                    outer._hover(self.index)
                except Exception:
                    pass          # the read-out is decoration; never break a click

            def mouseExited(self, event):
                pass

            def mousePressed(self, event):
                pass

            def mouseReleased(self, event):
                pass

        class Typed(unohelper.Base, XTextListener):
            def textChanged(self, event):
                try:
                    outer._show_colour(outer._typed_colour(), "")
                except Exception:
                    pass

            def disposing(self, event):
                pass

        for name in ["ok", "cancel", "previous", "next"]:
            control = self.control(name)
            listener = Press(name)
            control.addActionListener(listener)
            self._listeners.append((control, listener))
        for index in range(CELLS):
            control = self.control(cell_name(index))
            listener = Hovered(index)
            try:
                control.addMouseListener(listener)
                self._listeners.append((control, listener))
            except Exception:
                pass
        for name, listener in (("palettes", Chosen()), ("hex", Typed())):
            control = self.control(name)
            method = "addItemListener" if name == "palettes" else "addTextListener"
            try:
                getattr(control, method)(listener)
                self._listeners.append((control, listener))
            except Exception:
                pass

    def _selected_palette(self):
        """The row of the palette drop-down, or the current one if unanswered."""
        try:
            positions = self.control("palettes").getSelectedItemsPos()
            if positions:
                return int(positions[0])
        except Exception:
            pass
        return self.palette_index

    # -- lifetime ---------------------------------------------------------- #

    def show(self):
        """Attach the peers and the listeners and paint the current page.

        Separate from ``run()`` because ``run()`` enters a modal loop: without
        this split there is no way to test what happens just before it, and a
        broken line in there is invisible until a user sits in front of a settings
        dialog whose swatch does nothing.
        """
        if self._warnings:
            # a property the model refuses is otherwise invisible: the
            # control simply shows up wrong and nothing says why
            config.log(self.ctx, "picker warnings: %s" % self._warnings)
        self._peer()
        self._install_listeners()
        # only now, because hiding a control means talking to its peer: before the
        # fix a 5-colour palette left 55 squares painted in the colour being
        # edited, so they looked pickable and picked something else
        self._paint_cells()
        config.log(self.ctx, "%s: showing %d colours, page %d of %d%s"
                   % (self.palettes[self.palette_index][0], len(self.flat_cells()),
                      self.page + 1, self.pages(),
                      "" if not self.recent else " (+%d recent)" % len(self.recent)))

    def run(self):
        """Show the picker modally; the chosen RGB int, or None if cancelled."""
        if self.dialog is None:
            self.build()
        self.show()
        self.dialog.execute()
        self.dialog.setVisible(False)
        return self.current if self.accepted else None

    def dispose(self):
        for control, listener in self._listeners:
            for method in ("removeActionListener", "removeItemListener",
                           "removeMouseListener", "removeTextListener"):
                try:
                    getattr(control, method)(listener)
                except Exception:
                    pass
        self._listeners = []
        if self.dialog is not None:
            try:
                self.dialog.dispose()
            except Exception:
                pass
            self.dialog = None


def _hide(control):
    """Switch a cell or a caption off; it talks to the peer, so after ``createPeer``."""
    try:
        control.setVisible(False)
    except Exception:
        pass


def _show(control):
    try:
        control.setVisible(True)
    except Exception:
        pass


def pick(ctx, palette_list, current=0, title="Pick a Colour", recent=None):
    """Convenience wrapper: show the picker, return the RGB int or None."""
    chosen_picker = ColourPicker(ctx, palette_list, current, title, recent)
    try:
        return chosen_picker.run()
    finally:
        chosen_picker.dispose()
