"""The colour picker: what LibreOffice's font-colour dropdown does, rebuilt.

The office offers no picker to reuse - ``ColorPicker``, ``ColorBox`` and
``ColorPickerDialog`` do not exist in ``program/types/offapi.rdb``, and the one
``ColorListBox`` string there is an Object Inspector enum literal
(``dev/probe_api.py``) - so the widget is assembled out of the same AWT control
models the settings dialog uses, and the palettes come from the office's own
``.soc`` files (:mod:`plan_impress.palettes`).

Two things were probed before choosing this shape (``dev/probe_paint.py``):

* a control's paint listener is never called, so the grid cannot be *drawn* -
  it is sixty button controls with their ``BackgroundColor`` set instead;
* a control's mouse listener *does* report pixel coordinates, which is why a
  hand-drawn grid had to be ruled out rather than assumed impossible.

Like the real dropdown, clicking a colour is the answer.  OK accepts the colour
in the preview, Cancel leaves the setting as it was; Escape is Cancel and Enter
is OK, because the OK button is the dialog's default button.
"""

import unohelper
from com.sun.star.awt import XActionListener, XItemListener

from plan_impress import config, palettes

#: Cells per row and per page.  Sixty is what fits without scrolling, and there
#: is no scrollable container whose model can be created, so longer palettes
#: (``freecolour-hlc`` has hundreds) are paged instead.
COLUMNS = 10
ROWS = 6
CELLS = COLUMNS * ROWS

_MARGIN = 8
_LABEL_H = 10
_BUTTON_H = 18
_CELL_W = 9
_CELL_H = 7
_GRID_X = _MARGIN
_GRID_W = COLUMNS * _CELL_W
_GRID_H = ROWS * _CELL_H
_HEADER_H = 16                            # the palette drop-down
_PREVIEW_H = 14
_PREVIEW_Y = _MARGIN + _HEADER_H + 4
_GRID_Y = _PREVIEW_Y + _PREVIEW_H + 6
_PREVIEW_W = 14
_HEX_X = _MARGIN + _PREVIEW_W + 4
_BUTTON_W = 26
_BUTTON_GAP = 4
PAGER_Y = _GRID_Y + _GRID_H + 6
_BUTTON_Y = PAGER_Y + _BUTTON_H + 6
# as wide as the grid and no wider: this is meant to read as the office's
# own colour dropdown, which is a square-ish popup, not a settings sheet
DIALOG_WIDTH = 2 * _MARGIN + _GRID_W
DIALOG_HEIGHT = _BUTTON_Y + _BUTTON_H + _MARGIN

_MODEL_BUTTON = "com.sun.star.awt.UnoControlButtonModel"
_MODEL_FIXED = "com.sun.star.awt.UnoControlFixedTextModel"
_MODEL_LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"

#: Used when the office's palettes cannot be read at all: the picker still has
#: something to show instead of opening an empty window.
FALLBACK = [("Standard", [
    ("Black", 0x000000), ("White", 0xFFFFFF), ("Red", 0xC0504D),
    ("Orange", 0xF79646), ("Yellow", 0xFFFF00), ("Green", 0x9BBB59),
    ("Turquoise", 0x4BACC6), ("Blue", 0x4F81BD), ("Violet", 0x8064A2),
    ("Grey", 0x808080)])]


def page_count(total, cells=CELLS):
    """How many pages of cells a palette of ``total`` colours needs."""
    return max(1, (total + cells - 1) // cells)


def page_slice(colours, page, cells=CELLS):
    """The colours of one page; an out-of-range page gives an empty list."""
    start = page * cells
    return list(colours[start:start + cells])


def cell_position(index):
    """``(x, y, width, height)`` of one cell of the grid, in dialog units."""
    return (_GRID_X + (index % COLUMNS) * _CELL_W,
            _GRID_Y + (index // COLUMNS) * _CELL_H,
            _CELL_W, _CELL_H)


def cell_name(index):
    return "cell%d" % index


def _field_specs(palette_names, page_colours, page, pages, current):
    """Every control of the picker as ``(name, service, [(property, value)])``.

    Split out from the UNO calls so the layout can be tested without a display,
    the way ``dialog._field_specs`` is.
    """
    specs = [
        ("palettes", _MODEL_LISTBOX, [
            ("StringItemList", tuple(palette_names)),
            ("Dropdown", True), ("PositionX", _MARGIN), ("PositionY", _MARGIN),
            ("Width", _GRID_W), ("Height", _HEADER_H),
            # the selection has to travel with the model (AGENTS.md fact 30)
            ("SelectedItems", (0,)),
        ]),
        ("preview", _MODEL_FIXED, [
            ("Label", " "), ("PositionX", _MARGIN), ("PositionY", _PREVIEW_Y),
            ("Width", _PREVIEW_W), ("Height", _PREVIEW_H),
            ("BackgroundColor", current),
        ]),
        ("hex", _MODEL_FIXED, [
            ("Label", config.color_to_hex(current)),
            ("PositionX", _HEX_X), ("PositionY", _PREVIEW_Y + 2),
            ("Width", _GRID_W - _PREVIEW_W - 4), ("Height", _LABEL_H),
        ]),
    ]
    for index in range(CELLS):
        x, y, width, height = cell_position(index)
        name, colour = page_colours[index] if index < len(page_colours) else ("", current)
        specs.append((cell_name(index), _MODEL_BUTTON, [
            ("Label", ""), ("PositionX", x), ("PositionY", y),
            ("Width", width), ("Height", height),
            ("BackgroundColor", colour),
            ("HelpText", name),
        ]))
    specs.append(("previous", _MODEL_BUTTON, [
        ("Label", "<"), ("PositionX", _GRID_X), ("PositionY", PAGER_Y),
        ("Width", 14), ("Height", _BUTTON_H),
    ]))
    specs.append(("page", _MODEL_FIXED, [
        ("Label", "%d / %d" % (page + 1, pages)),
        ("PositionX", _GRID_X + 18), ("PositionY", PAGER_Y + 4),
        ("Width", 34), ("Height", _LABEL_H),
    ]))
    specs.append(("next", _MODEL_BUTTON, [
        ("Label", ">"), ("PositionX", _GRID_X + 56), ("PositionY", PAGER_Y),
        ("Width", 14), ("Height", _BUTTON_H),
    ]))
    specs.append(("ok", _MODEL_BUTTON, [
        ("Label", "OK"),
        ("PositionX", DIALOG_WIDTH - 2 * _BUTTON_W - _BUTTON_GAP - _MARGIN),
        ("PositionY", _BUTTON_Y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
        ("DefaultButton", True),
    ]))
    specs.append(("cancel", _MODEL_BUTTON, [
        ("Label", "Cancel"), ("PositionX", DIALOG_WIDTH - _BUTTON_W - _MARGIN),
        ("PositionY", _BUTTON_Y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
    ]))
    return specs


class ColourPicker(object):
    """A modal palette chooser; ``run()`` returns an RGB int, or None.

    ``palette_list`` is what ``palettes.load_palettes()`` returns, optionally
    with ``palettes.deck_palette()`` and ``palettes.recent_palette()`` in
    front; the caller decides the order because it knows whether it is picking
    a heading colour or a muted one.
    """

    def __init__(self, ctx, palette_list, current=0, title="Pick a Colour"):
        self.ctx = ctx
        self.palettes = [entry for entry in (palette_list or [])
                        if entry and entry[1]] or FALLBACK
        self.current = int(current) & 0xFFFFFF
        self.title = title
        self.page = 0
        self.palette_index = 0
        self.accepted = False
        self.dialog = None
        self.model = None
        self._listeners = []
        self._warnings = []

    # -- construction ------------------------------------------------------ #

    def palette_names(self):
        return [name for name, _colours in self.palettes]

    def colours(self):
        return self.palettes[self.palette_index][1]

    def build(self):
        """Create the dialog and every control in it."""
        from plan_impress import dialog
        manager = self.ctx.ServiceManager
        self.dialog = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialog", self.ctx)
        self.model = manager.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self.ctx)
        self.dialog.setModel(self.model)
        for property_name, value in (("Width", DIALOG_WIDTH), ("Height", DIALOG_HEIGHT)):
            try:
                self.model.setPropertyValue(property_name, value)
            except Exception as error:
                self._warnings.append("dialog.%s: %s" % (property_name, error))
        specs = _field_specs(self.palette_names(), page_slice(self.colours(), self.page),
                             self.page, page_count(len(self.colours())), self.current)
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

    # -- behaviour --------------------------------------------------------- #

    def _paint_cells(self):
        """Point the cells at the current page and give them its colours."""
        colours = page_slice(self.colours(), self.page)
        for index in range(CELLS):
            control_model = self.model.getByName(cell_name(index))
            if index < len(colours):
                name, colour = colours[index]
                control_model.setPropertyValue("BackgroundColor", colour)
                control_model.setPropertyValue("HelpText", name)
                self.control(cell_name(index)).setVisible(True)
            else:
                # an unused cell has to disappear rather than keep the colour it
                # had on the previous page: a stale cell that still looks
                # pickable picks the wrong colour
                self.control(cell_name(index)).setVisible(False)
        try:
            self.model.getByName("page").setPropertyValue(
                "Label", "%d / %d" % (self.page + 1, page_count(len(self.colours()))))
        except Exception:
            pass

    def _show_colour(self, colour):
        self.current = int(colour) & 0xFFFFFF
        try:
            self.model.getByName("preview").setPropertyValue("BackgroundColor",
                                                             self.current)
        except Exception:
            pass
        try:
            self.model.getByName("hex").setPropertyValue(
                "Label", config.color_to_hex(self.current))
        except Exception:
            pass

    def _choose_palette(self, index):
        if 0 <= index < len(self.palettes) and index != self.palette_index:
            self.palette_index = index
            self.page = 0
            self._paint_cells()

    def _turn_page(self, step):
        pages = page_count(len(self.colours()))
        page = min(max(self.page + step, 0), pages - 1)
        if page != self.page:
            self.page = page
            self._paint_cells()

    def _press(self, name):
        if name == "ok":
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
            colours = page_slice(self.colours(), self.page)
            if index < len(colours):
                # one click on a colour is the answer, as in the real dropdown
                self._show_colour(colours[index][1])
                self.accepted = True
                self.dialog.endExecute()

    def _install_listeners(self):
        """One listener per control: deciding from ``event.Source.Model.Name``
        has been seen to fail (AGENTS.md fact 31), so each listener is built
        knowing which control it belongs to."""
        outer = self

        class Press(unohelper.Base, XActionListener):
            def __init__(self, name):
                self.name = name

            def actionPerformed(self, event):
                outer._press(self.name)

            def disposing(self, event):
                pass

        class Chosen(unohelper.Base, XItemListener):
            def itemStateChanged(self, event):
                outer._choose_palette(outer._selected_palette())

            def disposing(self, event):
                pass

        for name in ["ok", "cancel", "previous", "next"] + [
                cell_name(index) for index in range(CELLS)]:
            control = self.control(name)
            listener = Press(name)
            control.addActionListener(listener)
            self._listeners.append((control, listener))
        control = self.control("palettes")
        listener = Chosen()
        control.addItemListener(listener)
        self._listeners.append((control, listener))

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
        broken line in there is invisible until a user sits in front of a
        settings dialog whose swatch does nothing.
        """
        if self._warnings:
            # a property the model refuses is otherwise invisible: the
            # control simply shows up wrong and nothing says why
            config.log(self.ctx, "picker warnings: %s" % self._warnings)
        self._peer()
        self._install_listeners()
        # only now, because hiding a control means talking to its peer:
        # a short palette left every spare cell painted in the current
        # colour, so 55 of the 60 squares looked pickable and were not
        self._paint_cells()
        colours = page_slice(self.colours(), self.page)
        config.log(self.ctx, "%s: showing %d of %d colours, page %d of %d"
                   % (self.palettes[self.palette_index][0], len(colours),
                      len(self.colours()), self.page + 1,
                      page_count(len(self.colours()))))

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
            for method in ("removeActionListener", "removeItemListener"):
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


def pick(ctx, palette_list, current=0, title="Pick a Colour"):
    """Convenience wrapper: show the picker, return the RGB int or None."""
    picker = ColourPicker(ctx, palette_list, current, title)
    try:
        return picker.run()
    finally:
        picker.dispose()
