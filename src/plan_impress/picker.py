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

Three measurements decided this construction (``dev/probe_paint.py``,
``dev/probe_swatch_look.py``, ``dev/probe_swatch_ring.py``):

* a control's **paint** listener is never called, so the grid cannot be *drawn* by a
  listener - it has to be drawn in advance, as a bitmap;
* the colour itself goes on an **image control**, not a button and not a label.  A
  button brings the theme's raised bevel with it, which is the "perspective-style
  border" around every colour that was reported, and its model has no ``Border`` to
  switch it off with (fact 65).  A label paints the colour flat and can be given a
  line - but only in the theme's own colour: ``BorderColor`` is ignored in every
  ``BorderStyle``, so on a dark theme a black square had no edge at all
  (``dev/probe_border_colour.py``, fact 78).  An image control paints whatever it is
  given, and what it is given is a PNG of the colour inside a one-pixel line of the
  *contrast* colour (:mod:`plan_impress.swatch`), which is how the office's own
  dropdown draws them;
* an image control's **mouse** listener *does* fire, which is what makes both the hover
  read-out and the click possible - it has no action source either, so picking a
  colour is ``mouseReleased``, not ``actionPerformed``.

What no square can do is take the tab focus, so the grid is not keyboard navigable; the
hex field beside OK is the keyboard route to a colour.
"""

import traceback

import unohelper
from com.sun.star.awt import XActionListener, XItemListener, XMouseListener, \
    XTextListener

from plan_impress import config, swatch

# --------------------------------------------------------------------------- #
# the grid
# --------------------------------------------------------------------------- #

#: Cells per row.  The office's popup is ten wide, and so is this one.
COLUMNS = 10
#: Rows of squares the grid can ever show - the recent group takes one of them.
ROWS = 6
#: The controls a colour is painted on, created once and then re-pointed at the
#: colours of whatever is showing: the grid cannot be drawn (fact 64), a button would
#: bring the theme's bevel with it (fact 77) and a label cannot draw a line of a
#: colour we choose (fact 78), so it is one image control per square, each carrying a
#: bitmap :mod:`plan_impress.swatch` draws.
CELLS = COLUMNS * ROWS

#: A square of colour has to be square in *pixels*, and a dialog unit is not square:
#: one unit is 2.53 px across and 2.39 px down (AGENTS.md fact 28), so equal units are
#: not equal pixels.  ``dev/probe_picker_ink.py`` paints candidate pairs and photographs
#: them - 9 x 7 units, the size this used, comes back a 23 x 17 rectangle ("the color
#: sample must be exact squares, not rectangles"), 14 x 14 is 35 x 33, and 13 x 14 is
#: 33 x 33, the first pair that is the same both ways and big enough to be the size of
#: the office's own swatches.  :func:`swatch.square_units` is the rule.
CELL_W = 13
CELL_H = swatch.square_units(CELL_W)
#: Clear air between two squares of the grid, in units: five pixels.  The office's own
#: colour dropdown separates its swatches, and squares that touch read as one block of
#: colour rather than as ten choices ("add a few px between colors in the menu, just
#: like in the font color picker in native libreoffice").
_CELL_GAP = 2

_MARGIN = 8
_HEADER_H = 16                     # the palette selector and the pager
_HEADER_GAP = 7                    # clear air between the selector and the grid
_CAPTION_H = 9                     # one group caption
_CAPTION_GAP = 3                   # clear air above a caption
_GROUP_GAP = 6                     # clear air between two groups
_ROW_H = 18                        # a bottom row: the read-out, or the buttons
_ROW_GAP = 5
_BUTTON_W = 26
_BUTTON_H = 18
_BUTTON_GAP = 4
#: The narrowest the palette selector ever is: what a list of short names gets, and
#: the look the grid was laid out around.  It grows for a long one, see
#: :func:`selector_width`.
_COMBO_W = 54
_PAGER_W = 10                      # one arrow of the pager
_PAGER_MIN_W = 6                   # the indicator is never narrower than this
#: Clear air between an arrow and the page indicator, in dialog units.  Centring
#: the indicator *in the space the arrows leave* is not the same as centring it
#: with air around it: at the width the grid needs, the ``1/1`` box filled exactly
#: the gap from one arrow to the other, which is the report "(1/1) is still too
#: close to < and >".  :func:`content_width` reserves this much, so the window
#: grows for it rather than the indicator being squeezed out of the middle.
_PAGER_AIR = 6
#: The chip under the grid, the colour being edited: the same 33 x 33 px square as one
#: of the grid's own squares, so the two look like the same thing (13 x 14 units, see
#: :data:`CELL_W` and :func:`swatch.square_units`).
_SWATCH_W = CELL_W
#: The chip's height: the same rule as its width, so it is the same 33 x 33 px square
#: as one of the grid's squares above it.
_SWATCH_H = swatch.square_units(_SWATCH_W)
#: The field a hex value is typed into, in units - 73 px.  It used to borrow the
#: button's width, 26 units and 48 px, where seven characters at the picker's font are
#: 62 px of ink, so "#1F4E79" was painted cut in half ("the field that can be used to
#: set the hex value of the color ... is a bit too narrow").
#: ``dev/probe_picker_ink.py`` photographs the same characters in a reference
#: ``FixedText``, where nothing can cut them, and in the field, and prints both.
_HEX_W = 31
#: How wide one glyph of the page indicator is, in dialog units: measured on the
#: peer (a digit at the picker's 12 pt is ~7 px and a unit is 2.53 px, so 2.8).
#: The indicator's box cannot be resized once its peer exists (fact 70) and a
#: ``FixedText`` has no ``TextAlign`` to centre its words in (fact 72), so the box
#: is made wide enough for the widest string the picker can answer with and put in
#: the middle of the space between the arrows by arithmetic instead.
_PAGE_CHAR_W = 2.8
#: Clear air the page indicator's box keeps round its digits, in dialog units.  A
#: ``FixedText`` has no ``TextAlign`` (fact 72) and no way to ask it for its text's
#: width (fact 46), so the box is sized by arithmetic - and at the ``+ 1`` this used,
#: ``dev/probe_picker_ink.py`` photographs "1/2" as 20 px of ink in a 23 px box: 2 px of
#: air before the first digit and **1 px after the last**, which is the report "the text
#: 2/2 of the corresponding page is slightly cut on the right (not enough padding?)".
#: Four units is 10 px, which is 5 px of air on either side of a centred "1/2" and 6 px
#: round "12/12", the widest string the picker can answer with.
_PAGE_PAD = 4
#: How wide one glyph of a palette's name is, in dialog units, at the same font.
#: ``dev/probe_selector_fit.py`` photographs every name the chooser offers twice -
#: in a ``FixedText``, where nothing can cut it, and in a dropdown at the width the
#: picker asks for - and prints the ratio for each: "In this presentation" is 141 px
#: of ink over 20 characters (2.79 units a glyph, it is mostly narrow letters),
#: "Recently used" 102 px over 13 (3.10) and "freecolour-hlc" 105 over 14 (2.97).
#: The widest ratio is the constant, or a name the probe has not photographed gets
#: cut - which is exactly how the 2.8 this used to hold, taken from the one name
#: somebody had looked at, left "In this presentation" cut in half.
_LIST_CHAR_W = 3.1
#: The selector's own furniture in the same units: the drop-down arrow and the
#: padding round the words, so the name is not clipped by the box that names it.
#: Measured, not guessed: the probe still finds the 20-character name cut at 74
#: units and whole at 78, and its words are 56 of those units - so the arrow and its
#: padding cost about 20, and two more are slack for a name nobody has photographed.
_LIST_CHROME_W = 22

_GRID_X = _MARGIN
#: The grid's width: the squares plus the air between them, so the window is never
#: narrower than what the grid needs (see :func:`content_width`).
_GRID_W = COLUMNS * CELL_W + (COLUMNS - 1) * _CELL_GAP
#: Where the first row of squares would start; each group's caption sits above it.
_GRID_Y = _MARGIN + _HEADER_H + _HEADER_GAP
#: The width the *grid* needs.  The window is this wide or wider: see
#: :func:`content_width`, which is what the window is actually given.
DIALOG_WIDTH = 2 * _MARGIN + _GRID_W

#: The caption the remembered colours get, the way the office labels its groups.
RECENT_CAPTION = "Recently used"

_MODEL_BUTTON = "com.sun.star.awt.UnoControlButtonModel"
_MODEL_FIXED = "com.sun.star.awt.UnoControlFixedTextModel"
_MODEL_IMAGE = "com.sun.star.awt.UnoControlImageControlModel"
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

    The recent colours are a captioned group, the way the office labels the rows of
    its dropdown; the palette page gets **no caption** - ``None`` - because the
    selector above the grid is already showing that name, and painting it again
    under the recent row is the duplicate the report was about ("I see twice the
    title, once in the dropdown menu and once under it").  ``palette_name`` stays in
    the signature because the caller's meaning is "the palette that is showing",
    which the selector says; do not put it back as a caption.
    """
    bands = []
    recent = list(recent or [])[:COLUMNS]
    if recent:
        bands.append((RECENT_CAPTION, recent))
    if page_colours:
        bands.append((None, list(page_colours)))
    return bands


def layout(bands, top=_GRID_Y):
    """``[(caption, colours, y, rows)]`` and the y under the whole grid.

    One place decides where every caption and every row of squares goes, so the
    grid, the read-out under it and the height of the window cannot disagree.  A
    group's ``y`` is the top of its **first row of squares**; its caption, when it
    has one, sits ``_CAPTION_H`` above that with ``_CAPTION_GAP`` of clear air over
    it - which is what keeps a caption from being drawn under the control in front
    of it (the first caption used to start three units inside the selector row, and
    the tops of its letters disappeared).  An uncaptioned group - the palette page,
    see :func:`grid_bands` - costs its rows and its air only, no phantom line.
    """
    placed = []
    y = top
    bottom = top
    for caption, colours in bands:
        rows = max(1, (len(colours) + COLUMNS - 1) // COLUMNS)
        cap = _CAPTION_H if caption else 0
        if cap:
            y += _CAPTION_GAP
        placed.append((caption, list(colours), y + cap, rows))
        bottom = y + cap + rows * CELL_H + max(0, rows - 1) * _CELL_GAP
        y = bottom + _GROUP_GAP
    return placed, bottom


def cell_position(index, bands_top=_GRID_Y, rows_before=0, caption_lines=0,
                  x=_GRID_X):
    """``(x, y, width, height)`` of one cell of the grid, in dialog units.

    ``rows_before`` and ``caption_lines`` are what the rows and captions above it
    have already used up - the squares are separated by :data:`_CELL_GAP` of clear
    air, but a caption and its air sit between two groups as well (see :func:`layout`).
    ``x`` is the grid's left edge, which follows the window's width (see
    :func:`grid_x`).

    The pitch is size plus air, which is what separates one colour from the next the
    way the office's own dropdown separates its swatches; the squares themselves are
    square in *pixels*, not in units (see :data:`CELL_W`).
    """
    row = index // COLUMNS
    column = index % COLUMNS
    return (x + column * (CELL_W + _CELL_GAP),
            bands_top + caption_lines + (rows_before + row) * (CELL_H + _CELL_GAP),
            CELL_W, CELL_H)


def cell_name(index):
    return "cell%d" % index


def readout(name, colour):
    """What the read-out says about a colour: the office shows name and value.

    The office's dropdown prints the palette's own name for the colour and nothing
    else, so an unnamed colour is just its value: inventing the word "Colour" here
    put a stroke under one of its letters, and the picker is meant to look like the
    office's widget, not like a labelled form field.

    The leading space is layout, not manners.  The office underlines the first letter
    of the label that stands in front of an edit field, as the mnemonic that focuses
    it - the read-out stood in front of the hex field, so its "F" came out underlined
    like a broken glyph.  The empty label in :func:`bottom_specs` is what absorbs
    that; the space keeps the line off the chip's edge while it is at it
    (``dev/probe_underline.py`` photographs the six variants).
    """
    value = "#%s" % config.color_to_hex(colour)
    return " %s  %s" % (name, value) if name else " %s" % value


# --------------------------------------------------------------------------- #
# the controls, as data
# --------------------------------------------------------------------------- #

def page_label(page, pages):
    """What the indicator between the two arrows says: ``"2/5"``."""
    return "%d/%d" % (page + 1, pages)


def selector_width(palette_names):
    """How wide the palette selector has to be to say the longest name it offers.

    ``palettes.deck_palette()`` calls the deck's own colours *In this presentation*,
    20 characters, and at the width the grid alone needs the selector clipped it -
    the report was that the chooser cuts the name.  A list box cannot be asked how
    wide its words are (fact 46: no ``FontDescriptor`` on a peer, no text metrics
    anywhere), so the width comes from ``dev/probe_selector_fit.py``, which
    photographs the same words twice: in a ``FixedText`` that cannot be cut, and in a
    dropdown at this width.  ``_LIST_CHAR_W`` is the widest pixels-per-glyph any name
    measures and ``_LIST_CHROME_W`` what the arrow and the padding leave the words.

    It is sized for **every** palette the picker offers, not for the one that happens
    to be showing when the window opens, because the box cannot be resized once its
    peer exists (fact 70) and switching to a longer name must not truncate it.
    """
    longest = max([len(str(name)) for name in palette_names] + [0])
    return max(_COMBO_W, int(longest * _LIST_CHAR_W + 0.999) + _LIST_CHROME_W)


def page_label_width(widest_pages=None):
    """How wide the page indicator's box has to be for the widest string it says.

    The same number :func:`pager_geometry` sizes the box with, asked for on its own:
    it is also what the window's width has to reserve, or widening the window for a
    long palette name takes the room away from the ``12/12`` in the middle.
    """
    widest = max(1, int(widest_pages or 1))
    return max(_PAGER_MIN_W,
               int(round(len(page_label(widest - 1, widest)) * _PAGE_CHAR_W))
               + _PAGE_PAD)


def content_width(palette_names=(), widest_pages=None):
    """How wide the window has to be: what the grid needs, or the header row.

    The squares are the fixed thing - ten columns of the office's own size - so the
    window grows around them when the selector's words need the room, which is what
    "put the dialog a bit wider so *In this presentation* is not cut" asked for.  The
    header row is selector, gap, two arrows and the space between them: that sum, plus
    the margins, is the narrowest window the selector fits in - and the space between
    the arrows is what :func:`page_label_width` says the indicator needs, so growing
    the window for a name cannot take the page number's room away.
    """
    room = (_MARGIN + selector_width(palette_names) + _BUTTON_GAP + 2 * _PAGER_W
            + 2 * _PAGER_AIR + page_label_width(widest_pages) + _MARGIN)
    return max(DIALOG_WIDTH, room)


def grid_x(width=DIALOG_WIDTH):
    """Where the grid starts in a window of ``width``: centred, never too close.

    A window wider than the grid - the only reason it ever is, see
    :func:`content_width` - would otherwise leave all the extra space on the right,
    and the squares would look shoved into the left of their own popup.
    """
    return max(_MARGIN, (int(width) - _GRID_W) // 2)


def pager_geometry(pages, widest_pages=None, right=_GRID_X + _GRID_W, left=None):
    """``(previous_x, label_x, label_w, next_x)`` - the arrows and the indicator.

    The indicator belongs *between* the arrows, which it used not to be: its box had
    a fixed width and started left of where the arrows are, so it ran four units
    under the ``>`` button and the page number looked shoved to one side with half
    of it behind the arrow.  The box is sized for the widest string the picker can
    answer with - it cannot be resized after its peer exists (fact 70) - and then
    centred in the space between the arrows by arithmetic, because a ``FixedText``
    has no ``TextAlign`` (fact 72).  A palette long enough to need ten pages takes
    the whole space, which is the most the arrows leave it.

    ``right`` is where the row ends and ``left`` where the arrows begin: both follow
    the selector's width, which follows the longest palette name (see
    :func:`header_specs`), and the defaults are the grid's own edges.
    """
    next_x = right - _PAGER_W
    previous_x = _GRID_X + _COMBO_W + _BUTTON_GAP if left is None else int(left)
    # what the arrows leave is not what the indicator may fill: the air either side
    # is what makes the page number read as a thing of its own rather than as part
    # of an arrow (the report was "(1/1) is still too close to < and >").
    first = previous_x + _PAGER_W + _PAGER_AIR
    last = next_x - _PAGER_AIR
    room = max(0, last - first)
    widest = max(1, int(widest_pages or pages))
    label_w = max(_PAGER_MIN_W, min(page_label_width(widest), room))
    label_x = first + (room - label_w) // 2
    return previous_x, label_x, label_w, next_x


def header_specs(palette_names, pages, page, selected=0, widest_pages=None,
                 width=None):
    """The top row: which palette, and the pager.

    Paging because there is nothing to scroll in (fact 65) and ``freecolour-hlc``
    has 240 colours; it lives up here rather than in the button row so the bottom
    has room for the swatch, the name, the hex field and the two buttons.

    ``widest_pages`` is the longest page count any palette the picker offers has:
    the indicator's box is built once and for all (see :func:`pager_geometry`), so
    it has to fit ``12/12`` even when the palette that opens is ``standard``.
    ``width`` is the window's, which the selector's words decide (see
    :func:`content_width`); the row runs from the left margin to the right one, so a
    window grown for a long name grows the selector and not the squares.
    """
    font = font_height()
    single = pages <= 1
    width = content_width(palette_names, widest_pages) if width is None \
        else int(width)
    # The row belongs to the window, not to the grid: it runs margin to margin, so
    # the selector gets what its longest name needs (see :func:`content_width`) and
    # the ``>`` is flush with the right margin.  The squares are the thing that is
    # centred (see :func:`grid_x`), because they are the popup's visual mass.
    left = _MARGIN
    right = width - _MARGIN
    # what the longest name needs, but never so much that the indicator is squeezed
    # out from between the arrows: the pager's room is the one thing not to trade
    combo_w = min(selector_width(palette_names),
                  right - left - (_BUTTON_GAP + 2 * _PAGER_W + _PAGER_MIN_W))
    previous_x, label_x, label_w, next_x = pager_geometry(
        pages, widest_pages, right=right, left=left + combo_w + _BUTTON_GAP)
    return [
        ("palettes", _MODEL_LISTBOX, [
            ("StringItemList", tuple(palette_names)),
            ("Dropdown", True), ("PositionX", left), ("PositionY", _MARGIN),
            ("Width", combo_w), ("Height", _HEADER_H), ("FontHeight", font),
            # the selection has to travel with the model (AGENTS.md fact 30)
            ("SelectedItems", (selected,)),
            ("HelpText", "Palette"),
        ]),
        ("previous", _MODEL_BUTTON, [
            ("Label", "<"), ("PositionX", previous_x),
            ("PositionY", _MARGIN), ("Width", _PAGER_W), ("Height", _HEADER_H),
            ("FontHeight", font), ("HelpText", "Colours before these"),
            # a one-page palette has nothing to page through: a dead button would
            # look like the picker is broken
            ("Enabled", not single),
        ]),
        ("page", _MODEL_FIXED, [
            ("Label", page_label(page, pages)),
            ("PositionX", label_x),
            ("PositionY", _MARGIN + (_HEADER_H - _CAPTION_H) // 2),
            ("Width", label_w), ("Height", _CAPTION_H), ("FontHeight", font),
        ]),
        ("next", _MODEL_BUTTON, [
            ("Label", ">"),
            ("PositionX", next_x), ("PositionY", _MARGIN),
            ("Width", _PAGER_W), ("Height", _HEADER_H), ("FontHeight", font),
            ("HelpText", "Colours after these"), ("Enabled", not single),
        ]),
    ]


def caption_specs(bands, x=None):
    """The group captions at their **final** positions.

    Two labels, because there are at most two groups: the recent row and the
    palette page.  A control keeps the rectangle it was created with once its peer
    exists (measured: moving it by writing ``PositionY`` to the model afterwards
    changes the model and leaves the pixels where they were), so the position has
    to be right here; :meth:`ColourPicker._paint_cells` only changes the words.
    ``x`` is the grid's left edge (see :func:`grid_x`): a caption belongs to the
    squares it labels, not to the window.
    """
    font = font_height()
    left = _GRID_X if x is None else int(x)
    placed, bottom = layout(bands)
    specs = []
    for index in range(2):
        if index < len(placed):
            label, y = placed[index][0], placed[index][2] - _CAPTION_H
        else:
            label, y = "", bottom           # switched off, position irrelevant
        specs.append(("caption%d" % index, _MODEL_FIXED, [
            ("Label", label or ""), ("PositionX", left), ("PositionY", y),
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


def cell_specs(bands, current, entries=None, x=None):
    """Every square of the grid as a flat colour with a solid line, at its position.

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

    Each square is an **image control** carrying the colour inside a line of the
    contrast colour (:func:`swatch_props`, :mod:`plan_impress.swatch`) - not a button,
    which the office bevels, and not a coloured label, whose line can only ever be the
    theme's own colour (fact 77, fact 78).  It has no action source either, so the click
    is ``mouseReleased``.

    ``x`` is the grid's left edge - :func:`grid_x`, which centres the squares in a
    window the selector's words have made wider than the grid.
    """
    left = _GRID_X if x is None else int(x)
    placed, bottom = layout(bands)
    specs = []
    flat = []
    for _caption, colours, y, rows in placed:
        for offset in range(rows * COLUMNS):
            cell_x, cell_y, width, height = cell_position(offset, bands_top=y,
                                                          x=left)
            entry = colours[offset] if offset < len(colours) else None
            flat.append((cell_x, cell_y, width, height, entry))
    for index in range(CELLS):
        if index < len(flat):
            cell_x, cell_y, width, height, entry = flat[index]
        else:
            # parked below the grid, and switched off with the rest
            cell_x, cell_y, width, height, entry = left, bottom, CELL_W, CELL_H, None
        if entries is not None:
            entry = entries[index] if index < len(entries) else None
        specs.append((cell_name(index), _MODEL_IMAGE,
                      [("PositionX", cell_x), ("PositionY", cell_y),
                       ("Width", width), ("Height", height),
                       ("HelpText", entry[0] if entry else "")]
                      + swatch.swatch_props(entry[1] if entry else current)))
    return specs


def bottom_specs(bottom, current, hex_text=None, x=None, width=None):
    """The read-out line and the button row, below the grid.

    One line says what the pointer is over - the swatch, the name and the value in
    an **editable** field, which is the office's ``Custom Color…`` in the space of
    six characters - and the row under it has the two buttons the typed value
    needs.

    The read-out belongs to the grid, so the chip lines up with the first column
    (``x``, see :func:`grid_x`); the buttons belong to the window and are flush with
    its right margin, the way a dialog's are.
    """
    font = font_height()
    left = _GRID_X if x is None else int(x)
    right = (DIALOG_WIDTH if width is None else int(width)) - _MARGIN
    readout_y = bottom + _ROW_GAP
    button_y = readout_y + _ROW_H + _ROW_GAP
    return [
        # the chip is the same kind of square as one of the grid, drawn the same way: a
        # button here would show the theme's bevel around the colour and would take the
        # tab focus away from OK and Cancel for a control that does nothing when it is
        # pressed
        ("preview", _MODEL_IMAGE,
         [("PositionX", left),
          ("PositionY", readout_y + (_ROW_H - _SWATCH_H) // 2),
          ("Width", _SWATCH_W), ("Height", _SWATCH_H)] + swatch.swatch_props(current)),
        ("name", _MODEL_FIXED, [
            ("Label", readout("", current)),
            ("PositionX", left + _SWATCH_W + _BUTTON_GAP),
            ("PositionY", readout_y + 4),
            ("Width", _GRID_W - _SWATCH_W - _BUTTON_GAP), ("Height", _CAPTION_H),
            ("FontHeight", font),
        ]),
        # One empty label directly before the field, invisible and one unit tall.  The
        # office treats the label that comes before an edit as *that field's* label and
        # underlines its first letter as a mnemonic: with the read-out sitting directly
        # in front of the hex field, "#1F4E79" was drawn with a stroke under its "F",
        # which reads as a broken glyph.  An empty label takes the role and shows
        # nothing (``dev/probe_underline.py``, six variants: with and without the
        # absorber, before a button, and alone).
        ("hex-label", _MODEL_FIXED, [
            ("Label", ""), ("PositionX", left), ("PositionY", button_y - 4),
            ("Width", 4), ("Height", 3),
        ]),
        ("hex", _MODEL_EDIT, [
            ("Text", hex_text if hex_text is not None
             else config.color_to_hex(current)),
            ("PositionX", left), ("PositionY", button_y),
            ("Width", _HEX_W), ("Height", _BUTTON_H), ("FontHeight", font),
            ("HelpText", "Type a colour and press Enter"),
        ]),
        ("ok", _MODEL_BUTTON, [
            ("Label", "OK"),
            ("PositionX", right - 2 * _BUTTON_W - _BUTTON_GAP),
            ("PositionY", button_y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
            ("FontHeight", font), ("DefaultButton", True),
        ]),
        ("cancel", _MODEL_BUTTON, [
            ("Label", "Cancel"), ("PositionX", right - _BUTTON_W),
            ("PositionY", button_y), ("Width", _BUTTON_W), ("Height", _BUTTON_H),
            ("FontHeight", font), ("DefaultButton", False),
        ]),
    ]


def dialog_height(bottom):
    """How tall the window has to be for a grid that ends at ``bottom``."""
    return bottom + _ROW_GAP + _ROW_H + _ROW_GAP + _BUTTON_H + _MARGIN


def _field_specs(palette_names, bands, pages, page, current, hex_text=None,
                 selected=0, entries=None, widest_pages=None, width=None):
    """Every control of the picker, and the size of the window that holds them.

    ``(specs, (width, height))`` with ``specs`` as
    ``(name, service, [(property, value)])`` - split out from the UNO calls so the
    layout can be tested without a display, the way ``dialog._field_specs`` and
    ``dialog.box_specs`` are.

    ``bands`` is the *geometry*: what :func:`full_bands` makes, not what is showing.
    The window is a popup of one fixed shape - nothing in it is ever moved, because
    a control that is switched on later does not repaint at a position it was given
    after its peer existed.  Turning cells on and off is what makes a five-colour
    deck palette and a 240-colour ``freecolour-hlc`` both fit.  ``entries``, when it
    is given, is the page that is showing (see :func:`cell_specs`), and
    ``widest_pages`` the longest page count of any palette, which is what decides how
    wide the page indicator has to be (see :func:`pager_geometry`).

    The width is the other thing decided here and once: :func:`content_width` asks
    what the *longest palette name* needs, because the selector cannot be widened
    afterwards (fact 70) and a name cut in half - "In this presentati..." - is what
    the report was about.  The grid keeps its size and is centred (see
    :func:`grid_x`); the header and the buttons follow the window's margins.
    """
    bottom = bottom_of(bands)
    width = content_width(palette_names, widest_pages) if width is None \
        else int(width)
    left = grid_x(width)
    specs = (header_specs(palette_names, pages, page, selected, widest_pages,
                          width=width)
             + caption_specs(bands, x=left)
             + cell_specs(bands, current, entries, x=left)
             + bottom_specs(bottom, current, hex_text, x=left, width=width))
    return specs, (width, dialog_height(bottom))


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
        #: Whether the office's theme is dark, which decides the colour of the line
        #: round every swatch (:func:`plan_impress.swatch.ring_colour`).  ``None``
        #: means nothing said, and then each square is lined against its own colour.
        self.dark = swatch.theme_is_dark(ctx)
        self._pixels = None

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

    def all_pages(self):
        """The longest page count of any palette offered: what the indicator fits.

        The page indicator's box is built once, with the rest of the picker, and
        cannot be resized afterwards (fact 70), so it has to be wide enough for the
        widest string *any* palette can answer with - not for the one that happens
        to be showing when the window opens.
        """
        room = page_size(self.recent)
        return max([page_count(len(colours), room) for _name, colours in self.palettes]
                   + [1])

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
            self.current, config.color_to_hex(self.current), self.palette_index,
            entries=self.flat_cells(), widest_pages=self.all_pages())
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

    def _pixels_of(self, name, units_w, units_h):
        """The pixel size ``name`` is painted at, or the size its units say.

        The line is one pixel *of the bitmap*, so the bitmap wants the control's own
        size: a dialog unit is 2.53 x 2.39 px at the usual screen (AGENTS.md facts 28
        and 64), which is what :func:`plan_impress.swatch.bitmap_size` turns a rectangle
        into and the only answer available before a peer exists.  Afterwards the peer is
        asked, because on another screen that is the only number that is not a guess -
        and ``ScaleMode`` 2 stretches whatever it is given over the control, so being
        wrong costs a thicker line and never an empty square.
        """
        size = swatch.bitmap_size(units_w, units_h)
        control = self.control(name) if self.dialog is not None else None
        try:
            rect = control.getPeer().getPosSize()
            if rect.Width > 1 and rect.Height > 1:
                size = (int(rect.Width), int(rect.Height))
        except Exception:
            pass
        return size

    def _bitmap_size(self):
        """The pixel size a square of the grid is painted at, remembered."""
        if self._pixels is None:
            self._pixels = self._pixels_of(cell_name(0), CELL_W, CELL_H)
        return self._pixels

    def _set_graphic(self, control_model, colour, size=None):
        """Hand a swatch the bitmap it is drawn from: its colour, its contrast line.

        ``Graphic`` rather than ``ImageURL``, because nothing may be written to a user's
        disk: the bytes reach the graphic provider through a ``Pipe``, in the signed
        spelling of ``sequence<octet>`` - the unsigned one is refused there, which is the
        one thing about this route that is not obvious (``dev/probe_swatch_stream.py``).
        It is also a property a control takes *after* its peer exists, which is what a
        palette switch is (``dev/probe_swatch_ring.py`` photographs the change).

        ``size`` is the bitmap's pixel size: the control's own, which for a square of
        the grid is :meth:`_bitmap_size` and for the chip under it something else
        entirely - one size for both would make the chip's line a pixel and a half thick.
        ``False`` when no bitmap can be made: the control keeps its plain
        ``BackgroundColor``, the flat square this widget had before the line was drawn,
        and a chooser that cannot draw a line must still be a chooser.
        """
        width, height = size or self._bitmap_size()
        made = swatch.graphic(self.ctx, colour, width, height,
                              swatch.ring_colour(colour, self.dark))
        if made is None:
            return False
        try:
            control_model.setPropertyValue("Graphic", made)
        except Exception:
            return False
        return True

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
            control_model.setPropertyValue("Tag", config.color_to_hex(colour))
            control_model.setPropertyValue("HelpText", colour_name)
            self._set_graphic(control_model, colour)
            _show(control)
        for index, control_name in enumerate(("caption0", "caption1")):
            try:
                caption = self.placed()[index][0]
            except IndexError:
                caption = None
            if not caption:
                # a group with nothing to say over it.  The palette page never has a
                # caption: the selector above the grid names it, and the second copy
                # of that name is what "I see twice the title" was about, so this is
                # switched off rather than left blank.
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
                "Label", page_label(self.page, self.pages()))
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

    def _paint_preview(self):
        """The chip under the grid, lined like a square of the grid above it.

        It needs saying at build time as well as on hover: the specs describe the
        control and ``_show_colour`` repaints it when the pointer moves, so before the
        fix it opened as a flat rectangle with no line at all - which is exactly the
        report about the palette, in the one place nobody hovered.
        """
        try:
            preview = self.model.getByName("preview")
        except Exception:
            return
        if preview is not None:
            self._set_graphic(preview, self.current,
                              self._pixels_of("preview", _SWATCH_W, _SWATCH_H))

    def _show_colour(self, colour, name=""):
        """Paint the read-out: the swatch, the name, the value in the field.

        The peer has to be told afterwards - writing the models alone leaves the
        line showing the colour the dialog was opened with, however often the
        pointer moves over the grid (the ``_refresh`` at the end).
        """
        self.current = int(colour) & 0xFFFFFF
        for control_name, property_name, value in (
                ("preview", "BackgroundColor", self.current),
                ("preview", "Tag", config.color_to_hex(self.current)),
                ("name", "Label", readout(name, self.current)),
                ("hex", "Text", config.color_to_hex(self.current))):
            try:
                self.model.getByName(control_name).setPropertyValue(property_name,
                                                                    value)
            except Exception:
                pass
        # the chip's line is drawn too, and with it: it names the colour the pointer is
        # over, so a stale line is a wrong read-out
        self._paint_preview()
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

        class Cell(unohelper.Base, XMouseListener):
            """One instance per square: the pointer over it names the colour, a click
            on it is the answer.

            A square is a label and not a button, because a button would be painted
            with the theme's bevel around the colour (fact 77) - and a label has no
            action source, so the click has to come from ``mouseReleased`` rather
            than from ``actionPerformed``.
            """

            def __init__(self, index):
                self.index = index

            def mouseEntered(self, event):
                try:
                    outer._hover(self.index)
                except Exception:
                    pass          # the read-out is decoration; never break a click

            def mouseReleased(self, event):
                try:
                    outer._press(cell_name(self.index))
                except Exception:                    # fact 66
                    config.log(outer.ctx, "picker cell %d:\n%s"
                               % (self.index, traceback.format_exc()))

            def mousePressed(self, event):
                pass

            def mouseExited(self, event):
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
            listener = Cell(index)
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
        # the chip is a drawn square like the grid's, so it wants its bitmap before the
        # page is painted: _paint_cells() ends by invalidating the window and every
        # control in it, which is what makes the new bitmap reach the screen
        self._paint_preview()
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
