#!/usr/bin/env python3
"""Test suite for Plan Impress.

    make test            # or: python3 tests/run_tests.py

Needs a development office running (``dev/start_ui.sh``); the integration tests
load documents in UI mode because moving slides and dispatching commands both
require a controller.  Tests that need the extension to be installed are
skipped with a notice when it is not.

Exit status is non-zero when something failed.
"""

import os
import re
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402  (also puts pyuno on sys.path)
import uno  # noqa: E402  (needs lo to have set that up)

from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sections.odp")
NO_FOOTER_FIXTURE = os.path.join(HERE, "fixtures", "sections_no_footer.odp")
#: The section titles the fixture carries, in deck order (`make_fixture.py`).
SECTION_NAMES = ["Introduction", "Architecture", "Demo"]
SERVICE = "service:org.nicolasderumigny.planimpress.InsertPlan?insert"
#: The other four commands the menu carries, by the URL a click takes.
REMOVE_SERVICE = "service:org.nicolasderumigny.planimpress.RemovePlan?remove"
#: The URL *Section Titles* is bound to, for the dispatch test below.
SECTION_SERVICE = "service:org.nicolasderumigny.planimpress.SectionTitles?section_titles"
REMOVE_SECTION_SERVICE = \
    "service:org.nicolasderumigny.planimpress.RemoveSectionTitles?remove_section_titles"
SETTINGS_SERVICE = "service:org.nicolasderumigny.planimpress.Settings?settings"
#: The URL *Toggle Debug Log* is bound to: the last row of the menu (fact 98).
DEBUG_URL = "service:org.nicolasderumigny.planimpress.Debug?debug"
#: The rows of the *Plan* menu, in the order they are meant to appear: the two
#: commands that put the plan slides in and take them out, then the two that write the
#: section names and take them back, then the two that change nothing in the deck.
#: What the office hands back is sorted by node name, not by this list (fact 98), so
#: both are pinned: ``the_menu_groups_the_commands_in_the_order_the_deck_is_worked_in``
#: reads the file and ``the_menu_rows_come_back_in_the_order_the_file_lists_them``
#: reads the merged configuration.
MENU_ROWS = [SERVICE, REMOVE_SERVICE, "private:separator", SECTION_SERVICE,
             REMOVE_SECTION_SERVICE, "private:separator", SETTINGS_SERVICE, DEBUG_URL]
#: What each of those rows has to read as: a row that names the wrong command is the
#: report "Insert Section Titles" was, when the two section items could be swapped.
MENU_TITLES = {SERVICE: "Insert Plan Slides", REMOVE_SERVICE: "Remove Plan Slides",
               SECTION_SERVICE: "Insert Section Titles",
               REMOVE_SECTION_SERVICE: "Remove Section Titles",
               SETTINGS_SERVICE: "Settings…", DEBUG_URL: "Toggle Debug Log"}
#: Where the merged ``Addons.xcu`` keeps the rows of the *Plan* submenu.  The node
#: names the configuration answers with *are* the menu's rows, in its own order.
SUBMENU_PATH = ("/org.openoffice.Office.Addons/AddonUI/OfficeMenuBarMerging/"
                "org.nicolasderumigny.planimpress/S1/MenuItems/M1/Submenu")
#: what ``tests/make_fixture.py`` writes into the footer of every slide
FOOTER_TEXT = "Quarterly Review 2026"

RESULTS = []


def test(function):
    """Collector decorator, so the file stays dependency free."""
    RESULTS.append((function.__name__, function))
    return function


class Skip(Exception):
    pass


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #

@test
def colour_helpers():
    assert config.color_to_hex(0xB0B0B0) == "B0B0B0"
    assert config.hex_to_color("b0b0b0") == 0xB0B0B0
    assert config.hex_to_color("#FFF") == 0x000FFF
    assert config.hex_to_color("nonsense", 12) == 12
    assert config._as_color("#336699", 0) == 0x336699
    assert config._as_color(True, 7) == 7
    assert config._as_color(None, 7) == 7


@test
def profile_dir_comes_from_the_deployment():
    """Where settings are stored must be the profile of the office running us."""
    deployed = ("/opt/dev/loprofile/user/uno_packages/cache/uno_packages"
                "/lu1abc.tmp_/plan-impress.oxt/plan_impress/config.py")
    assert config._profile_from_path(deployed) == "/opt/dev/loprofile/user"
    # a checkout is not a deployment: no "user/uno_packages" in the path
    assert config._profile_from_path("/tmp/repo/src/plan_impress/config.py") is None
    # and a profile directory that happens to be called "user" is not enough
    assert config._profile_from_path("/home/x/user/documents/config.py") is None


@test
def point_size_conversion():
    """The pt <-> 1/100 mm conversion, without needing an office.

    Getting this factor wrong is invisible to every other assertion: a plan
    slide once rendered with a 260 pt heading and still passed the layout test.
    """
    assert abs(core._UNITS_PER_POINT - 35.28) < 0.1, core._UNITS_PER_POINT
    # 100 mm of box for three lines leaves far more than 18 pt: keep the size
    assert core._fit_point_size(18.0, 10000, 3) == 18.0
    # 10 mm for three lines does not: clamp to the readable floor
    assert core._fit_point_size(18.0, 1000, 3) == 10.0
    # a long list in a normal box has to shrink
    assert core._fit_point_size(32.0, 9134, 30) < 12.0
    assert core._fit_point_size(18.0, 10000, 0) == 18.0

    class Placeholder(object):
        def __init__(self, height):
            self.CharHeight = height

    assert core._master_char_height(Placeholder(44.0), 32.0) == 44.0
    for nonsense in (0, -1, 400, None, "large"):
        assert core._master_char_height(Placeholder(nonsense), 32.0) == 32.0, nonsense
    assert core._master_char_height(None, 18.0) == 18.0

    class Paragraph(object):
        def __init__(self, height):
            self.CharHeight = height

    class PlaceholderWithLevel(Placeholder):
        """A master placeholder whose first paragraph asks for another size.

        That is what a real master looks like: its content placeholder keeps one
        paragraph per outline level, and the level - not the shape - is what the
        slides are drawn with.  Measured on a deck off the disk: 32 pt as a shape,
        31 pt as a paragraph, and every title of the deck is 31 pt.
        """

        def __init__(self, height, level):
            Placeholder.__init__(self, height)
            self.level = level

        def createEnumeration(self):
            return iter([Paragraph(self.level)])

    assert core._master_char_height(PlaceholderWithLevel(32.0, 31.0), 18.0) == 31.0
    assert core._master_char_height(PlaceholderWithLevel(32.0, None), 18.0) == 32.0
    assert core._master_char_height(PlaceholderWithLevel(32.0, 400), 18.0) == 32.0

    # where the heading stops painting, which is where the list has to start
    one_line = int(20.0 * core._UNITS_PER_POINT * core._LINE_SPACING)
    assert core._heading_bottom(1000, 1000, 20.0, "top") == 1000 + one_line
    assert core._heading_bottom(1000, 3000, 20.0, "bottom") == 4000
    centred = core._heading_bottom(1000, 3000, 20.0, "centre")
    assert 1000 + 1500 < centred < 1000 + 3000, centred
    assert centred == 1000 + (3000 + one_line) // 2, centred


@test
def list_label_follows_the_template():
    """Which label the rows get, from the template's own level - and no office.

    The plan list takes the label style the deck counts with, so a deck whose outline
    says ``I. II. III.`` gets roman numerals; only a template that does not count at
    all - a bullet character, a bitmap, the slide's own number, no label - gets digits
    instead, and then the two properties that size and place *a glyph* have to be
    corrected (:func:`_number_list`).  The integers are the measured ones, which is
    what makes this worth pinning: ``ARABIC`` is 4, not 5, and 1 is a letter.
    """
    class Entry(object):
        def __init__(self, name, value):
            self.Name, self.Value = name, value

    class Level(object):
        """A one-level ``NumberingRules`` stand-in."""

        def __init__(self, **level):
            self.entries = [Entry(name, value) for name, value in level.items()]

        def getByIndex(self, index):
            return self.entries if index == 0 else []

    arabic = core._numbering_type_arabic()
    assert arabic == 4, arabic
    for counting in (core._numbering_constant("ROMAN_UPPER", 2),
                     core._numbering_constant("ROMAN_LOWER", 3),
                     core._numbering_constant("CHARS_LOWER_LETTER", 1),
                     arabic):
        assert core._list_label_type(Level(NumberingType=counting)) == (counting, False)
    glyph_labels = list(core.CHARACTER_LABELS) + [
        core._numbering_constant("PAGE_DESCRIPTOR", 7),
        core._numbering_constant("NUMBER_NONE", 5), 0, None, "four"]
    for uncounted in glyph_labels:
        assert core._list_label_type(Level(NumberingType=uncounted)) == (arabic, True), (
            uncounted)
    assert core._list_label_type(None) == (arabic, True)


@test
def settings_roundtrip(tmp_path=os.path.join(ROOT, "out", "profile-test")):
    os.makedirs(tmp_path, exist_ok=True)
    fake_ctx = FakeContext(tmp_path)
    settings = config.load(fake_ctx)
    assert settings["muted_color"] == config.DEFAULT_MUTED_COLOR, settings
    settings["muted_color"] = 0x123456
    settings["title"] = "Outline"
    config.save(fake_ctx, settings)
    again = config.load(fake_ctx)
    assert again["muted_color"] == 0x123456, again
    assert again["title"] == "Outline", again
    # a corrupt file must not break anything
    with open(config.settings_path(fake_ctx), "w") as handle:
        handle.write("{ not json")
    assert config.load(fake_ctx)["muted_color"] == config.DEFAULT_MUTED_COLOR


class FakeContext(object):
    """Just enough component context for config._profile_dir."""

    def __init__(self, folder):
        self.folder = folder

    class _Manager(object):
        def __init__(self, folder):
            self.folder = folder

        def createInstanceWithContext(self, name, ctx):
            folder = self.folder

            class _Sub(object):
                def getSubstitutedValue(self, key):
                    return "file://" + folder
            return _Sub()

    @property
    def ServiceManager(self):
        return self._Manager(self.folder)


# --------------------------------------------------------------------------- #
# dialog model (no peer, so it works without a window manager)
# --------------------------------------------------------------------------- #

@test
def dialog_field_specs():
    from plan_impress import dialog
    values = {"MutedColor": "B0B0B0", "TextColor": "000000",
              "Title": "Plan", "master": "Default"}
    specs = dialog._field_specs(values, ["Default", "Dark"])
    names = [name for name, _service, _props in specs]
    for expected in ("labelMutedColor", "MutedColor", "swatchMutedColor",
                     "TextColor", "swatchTextColor", "Title", "Master",
                     "ok", "cancel"):
        assert expected in names, (expected, names)
    by_name = {name: (service, dict(props)) for name, service, props in specs}
    assert by_name["MutedColor"][0].endswith("UnoControlEditModel")
    assert by_name["MutedColor"][1]["Text"] == "B0B0B0"
    assert by_name["Master"][0].endswith("UnoControlListBoxModel")
    assert by_name["Master"][1]["StringItemList"] == ("Default", "Dark")
    # the master to show travels with the model: a selection set on the inserted
    # child never reaches the peer, and the box stays empty
    assert by_name["Master"][1]["SelectedItems"] == (0,), by_name["Master"][1]
    gone = {name: dict(props) for name, _service, props
            in dialog._field_specs(dict(values, master="No longer here"),
                                   ["Default", "Dark"])}
    assert gone["Master"]["SelectedItems"] == (0,), gone["Master"]
    assert by_name["swatchMutedColor"][1]["BackgroundColor"] == 0xB0B0B0
    assert by_name["swatchTextColor"][1]["BackgroundColor"] == 0x000000
    # the plan slide's heading is a named row of its own, not "Slide heading"
    assert by_name["labelTitle"][1]["Label"] == "Plan slide title:", by_name["labelTitle"]
    # and it is not capped: only the two hex fields are short
    assert "MaxLen" not in by_name["Title"][1], by_name["Title"][1]
    # every control must sit inside the dialog, with a size of its own
    spots = {}
    for name, _service, props in specs:
        props = dict(props)
        assert props["Width"] > 0 and props["Height"] > 0, (name, props)
        assert props["PositionX"] + props["Width"] <= dialog.DIALOG_WIDTH, name
        assert props["PositionY"] + props["Height"] <= dialog.DIALOG_HEIGHT, name
        spots.setdefault((props["PositionX"], props["PositionY"]), []).append(name)
    # ... and no two of them may share a position: that is what "all the controls
    # are stacked on top of each other" looks like in the specs.
    shared = {spot: names for spot, names in spots.items() if len(names) > 1}
    assert not shared, "controls sharing a position: %s" % shared


@test
def dialog_text_is_readable_and_rows_are_not_cramped():
    """Letters as big as the menu's, and clear space between the entries.

    Both reports were made by looking at the dialog, and neither is visible to a
    "is it laid out" assertion: with ``FontHeight`` 10 the labels measured 13 px of
    ink where a Plan menu item measures 14 px, and the rows were 14 units apart for
    12-unit-tall fields, so the next label began 2 units below the previous field.
    The numbers here are the ones ``python3 dev/measure_text.py`` reads off a
    screenshot of the dialog next to the open menu.
    """
    from plan_impress import dialog
    values = {"MutedColor": "B0B0B0", "TextColor": "000000",
              "Title": "Plan", "master": "Default"}
    specs = dialog._field_specs(values, ["Default", "Dark"])
    by_name = {name: dict(props) for name, _service, props in specs}
    # everything that shows words sets its own size: without it a control falls
    # back to the toolkit default, which is the small text that started this
    for name in ("labelMutedColor", "labelTextColor", "labelTitle", "labelMaster",
                 "MutedColor", "TextColor", "Title", "Master", "ok", "cancel"):
        assert by_name[name].get("FontHeight", 0) >= 12, (name, by_name[name])
    assert dialog._FONT >= 12, dialog._FONT
    # rows must not touch: the gap between one field's bottom and the next one's top
    fields = [by_name[name]["PositionY"]
              for name in ("MutedColor", "TextColor", "Title", "Master")]
    for above, below in zip(fields, fields[1:]):
        gap = (below - above) - dialog._FIELD_H
        assert gap >= 6, "rows %d and %d share %d units of space" % (above, below, gap)
    # and a label must clear the field of the row above it too, or the whole block
    # reads as one wall of text
    order = ("MutedColor", "TextColor", "Title", "Master")
    bottoms = [by_name[name]["PositionY"] + by_name[name]["Height"] for name in order]
    labels = [by_name["label" + name]["PositionY"] for name in order]
    for above, below in zip(bottoms, labels[1:]):
        assert below - above >= 6, "label starts %d units under the field above" % (
            below - above)


@test
def palettes_are_the_ones_the_office_shows():
    """The picker offers LibreOffice's own colour tables, correctly parsed.

    The office exposes no palette API at all (``dev/probe_api.py`` finds no
    ``ColorPicker``/``ColorBox``/``ColorPickerDialog`` in ``offapi.rdb``), so the
    data is read from ``share/palette/*.soc`` - which means the parser, not an
    interface, is what silently breaks when a file uses a different XML
    namespace.  A palette that parses to nothing just never appears.
    """
    from plan_impress import palettes
    found = dict(palettes.load_palettes())
    for name in ("standard", "libreoffice", "material", "html"):
        assert name in found, (name, sorted(found))
    colours = found["standard"]
    assert len(colours) > 50, len(colours)
    for label, colour in colours:
        assert isinstance(label, str) and label, (label, colour)
        assert isinstance(colour, int) and not isinstance(colour, bool), (label, colour)
        assert 0 <= colour <= 0xFFFFFF, (label, hex(colour))
    values = [colour for _label, colour in colours]
    assert 0x000000 in values and 0xFFFFFF in values, "standard has no black or white"
    # the preferred order is what makes the dropdown predictable
    order = [name for name, _colours in palettes.load_palettes()]
    assert order.index("standard") < order.index("freecolour-hlc"), order


@test
def palettes_read_both_namespaces_and_survive_rubbish():
    """``standard.soc`` and ``libreoffice.soc`` do not agree on namespaces."""
    from plan_impress import palettes
    old = ('<?xml version="1.0"?>'
           '<office:color-table '
           'xmlns:office="http://openoffice.org/2000/office" '
           'xmlns:draw="http://openoffice.org/2000/drawing" '
           'draw:name="Old">'
           '<draw:color draw:name="Black" draw:color="#000000"/>'
           '<draw:color draw:name="Red" draw:color="#F00"/>'
           '<draw:color draw:name="Broken" draw:color="not-a-colour"/>'
           '</office:color-table>')
    name, colours = palettes.parse_colour_table(old, "fallback")
    assert name == "Old", name
    assert colours == [("Black", 0x000000), ("Red", 0xFF0000)], colours
    new = ('<?xml version="1.0"?>'
           '<office:color-table '
           'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
           '<draw:color draw:name="Teal" draw:color="#008080"/>'
           '</office:color-table>')
    assert palettes.parse_colour_table(new, "new")[1] == [("Teal", 0x008080)]
    assert palettes.parse_colour_table("this is not xml", "fallback") == ("fallback", [])
    assert palettes.hex_to_rgb("#abc") == 0xAABBCC
    assert palettes.hex_to_rgb("green") is None
    # an unreadable file yields the file's name and no colours, never an exception
    assert palettes.read_soc("/nonexistent/nope.soc") == ("nope", [])


@test
def user_palette_replaces_the_shipped_one():
    """A user's edited palette wins, and does not appear twice."""
    import shutil
    import tempfile
    from plan_impress import palettes
    user = tempfile.mkdtemp(prefix="planimpress-palette-")
    shipped = tempfile.mkdtemp(prefix="planimpress-shipped-")
    try:
        with open(os.path.join(user, "standard.soc"), "w", encoding="utf-8") as handle:
            handle.write('<?xml version="1.0"?><color-table>'
                         '<color name="Mine" color="#123456"/></color-table>')
        with open(os.path.join(shipped, "standard.soc"), "w", encoding="utf-8") as handle:
            handle.write('<?xml version="1.0"?><color-table>'
                         '<color name="Black" color="#000000"/>'
                         '<color name="White" color="#FFFFFF"/></color-table>')
        loaded = palettes.load_palettes(directories=[user, shipped])
        assert [name for name, _colours in loaded] == ["standard"], loaded
        assert dict(loaded)["standard"] == [("Mine", 0x123456)], loaded
    finally:
        shutil.rmtree(user, ignore_errors=True)
        shutil.rmtree(shipped, ignore_errors=True)


@test
def recently_picked_colours_are_remembered_newest_first():
    """What the picker shows as *Recently used* comes straight from the settings.

    The list survives a save and a load, so it has to be able to survive a user
    editing the JSON file too: strings, booleans and out-of-range numbers in it
    must not become colours.
    """
    from plan_impress import config
    settings = {"recent_colors": [0x00FF00, "red", True, 0x1_0000_00, 0x00FF00]}
    remembered = config.remember_colour(settings, 0x1F6EC8)
    assert remembered[0] == 0x1F6EC8, remembered        # newest first
    assert 0x00FF00 in remembered, remembered           # and kept, without duplicates
    assert remembered.count(0x00FF00) == 1, remembered
    assert all(isinstance(c, int) and 0 <= c <= 0xFFFFFF for c in remembered), remembered
    # the cap: a list long enough to prove it, each colour distinct
    for index in range(config.RECENT_LIMIT + 10):
        config.remember_colour(settings, index)
    assert len(settings["recent_colors"]) == config.RECENT_LIMIT, settings
    assert settings["recent_colors"][0] == index, settings["recent_colors"]
    # and it survives the file: junk dropped, order kept
    saved = config._as_colors(remembered + ["junk", None, True])
    assert saved == remembered, saved


@test
def recent_palette_offers_pairs_of_name_and_colour():
    """The remembered colours come back as a palette, not a list of numbers."""
    from plan_impress import config, palettes
    settings = dict(config.DEFAULTS)
    assert palettes.recent_palette(settings) == [], "nothing remembered, no palette"
    settings["recent_colors"] = [0x22AA44, 0x22AA44, "nonsense", 0x1F6EC8]
    entries = palettes.recent_palette(settings)
    assert [name for name, _colours in entries] == ["Recently used"], entries
    colours = entries[0][1]
    assert [colour for _label, colour in colours] == [0x22AA44, 0x1F6EC8], colours
    for label, colour in colours:
        assert label == "%06X" % colour, (label, colour)


@test
def picker_pages_cover_every_colour():
    """Paging must not lose colours: a palette cell the user cannot reach is a bug."""
    from plan_impress import picker
    colours = [("c%d" % index, index) for index in range(250)]
    pages = picker.page_count(len(colours))
    assert pages == -(-250 // picker.CELLS), (pages, picker.CELLS)
    assert picker.page_count(picker.CELLS) == 1
    assert picker.page_count(picker.CELLS + 1) == 2
    reached = [colour for page in range(pages)
               for _name, colour in picker.page_slice(colours, page)]
    assert reached == [colour for _name, colour in colours], "colours unreachable"
    assert picker.page_count(0) == 1, "an empty palette must still have a page"
    assert picker.page_slice(colours, 99) == [], "a page past the end must be empty"
    # with a recent row above the grid the page has one row less, and paging has to
    # count the colours it can actually show or the last row is never reachable
    size = picker.page_size([("x", 1)] * picker.COLUMNS)
    assert size == picker.CELLS - picker.COLUMNS, size
    assert picker.page_count(0) == 1
    with_recent = [colour for page in range(picker.page_count(len(colours), size))
                   for _name, colour in picker.page_slice(colours, page, size)]
    assert with_recent == [colour for _name, colour in colours], "lost a colour"


@test
def picker_hides_the_cells_beyond_the_palette():
    """A short palette must not leave 55 squares that look pickable.

    The grid is a fixed 60 buttons, so the cells past the end of the palette are
    only honest once they are switched off - they are otherwise painted in the
    colour being edited and click as if they were a choice.
    """
    from plan_impress import picker
    ctx = lo.connect()
    colours = [("c%d" % index, index * 0x010101) for index in range(5)]
    window = picker.ColourPicker(ctx, [("Few", colours),
                                       ("Many", [("x%d" % index, index)
                                                 for index in range(picker.CELLS + 7)])],
                                 current=0x22AA44)
    window.build()

    def shown():
        return [index for index in range(picker.CELLS)
                if window.control(picker.cell_name(index)).isVisible()]

    try:
        window.show()                  # peers, listeners, cells: everything but
        assert shown() == list(range(5)), shown()
        window._choose_palette(1)             # a full first page
        assert shown() == list(range(picker.CELLS)), shown()
        window._turn_page(1)                  # and the remainder on the second
        assert shown() == list(range(7)), shown()
    finally:
        window.dispose()


@test
def picker_cells_are_laid_out_apart():
    """The grid is sixty squares: ten to a row, touching, each one its own colour."""
    from plan_impress import picker
    recent = [("#%06X" % (index * 0x010101), index * 0x010101)
              for index in range(1, 4)]
    colours = [("c%d" % index, index * 1000) for index in range(25)]
    bands = picker.full_bands(recent, "standard")
    entries = picker.recent_colours(recent) + colours
    cells = dict((name, dict(props)) for name, _service, props
                 in picker.cell_specs(bands, 0x123456, entries))
    assert len(cells) == picker.CELLS, len(cells)
    for index in range(len(entries)):
        assert cells["cell%d" % index]["BackgroundColor"] == entries[index][1], index
        assert cells["cell%d" % index]["HelpText"] == entries[index][0], \
            "a cell without its colour name says nothing on hover"
    for index in range(len(entries), picker.CELLS):
        assert cells["cell%d" % index]["HelpText"] == "", "an empty cell looks pickable"
    spots = {}
    for name, props in cells.items():
        assert props["Width"] > 0 and props["Height"] > 0, (name, props)
        spots.setdefault((props["PositionX"], props["PositionY"]), []).append(name)
    shared = dict((spot, names) for spot, names in spots.items() if len(names) > 1)
    assert not shared, "squares on top of each other: %s" % shared
    # ten to a row, each separated from the next: squares that touch read as one block
    # of colour and the office's own dropdown does not do that - see
    # :func:`the_grid_leaves_clear_air_between_its_squares` for the air itself
    rows = {}
    for name, props in cells.items():
        rows.setdefault(props["PositionY"], []).append(props)
    for y, row in rows.items():
        assert len(row) == picker.COLUMNS, "row at %s holds %s squares" % (y, len(row))
        row.sort(key=lambda props: props["PositionX"])
        for left, right in zip(row, row[1:]):
            assert right["PositionX"] == left["PositionX"] + left["Width"] + \
                picker._CELL_GAP, "gap between %s and %s" % (
                    left["PositionX"], right["PositionX"])


@test
def picker_is_the_offices_dropdown():
    """The chooser is the office's *line color* dropdown, control by control.

    The report was that it was ugly.  The office has exactly one way of showing
    colours, so "like that" is a list of things a test can check without a display:
    the palette selector with the pager beside it, a caption over each group of
    squares, the name and value of the colour under the grid with a field to type
    one into, and one OK and one Cancel flush with the grid.
    ``dev/probe_picker_look.py`` is the picture these assertions describe.
    """
    from plan_impress import picker
    names = ["standard", "deck"]
    recent = [("#%06X" % (index * 0x010101), index * 0x010101)
              for index in range(1, 4)]
    page = [("Blue 1", 0x2A57D7), ("Green 3", 0x93CAD7)]
    bands = picker.full_bands(recent, "standard")
    bottom = picker.bottom_of(bands)
    width, height = picker.DIALOG_WIDTH, picker.dialog_height(bottom)

    def rows_of(specs):
        return dict((name, dict(props)) for name, _service, props in specs)

    header = rows_of(picker.header_specs(names, 3, 0, 1))
    assert list(header["palettes"]["StringItemList"]) == names, header["palettes"]
    assert header["palettes"]["Dropdown"] is True
    assert list(header["palettes"]["SelectedItems"]) == [1], \
        "the selector must show the palette that is being displayed (fact 30)"
    assert (header["previous"]["Label"], header["next"]["Label"]) == ("<", ">")
    assert header["page"]["Label"] == "1/3", header["page"]
    assert header["previous"]["PositionX"] >= header["palettes"]["PositionX"] + \
        header["palettes"]["Width"], "the pager sits on the selector"
    one_page = rows_of(picker.header_specs(names, 1, 0, 0))
    assert not one_page["previous"]["Enabled"] and not one_page["next"]["Enabled"], \
        "a one-page palette must not offer a dead arrow"
    # the page indicator belongs *between* the two arrows.  Its box used to have a
    # fixed width and start left of where the arrows are, so it ran four units under
    # the > button and the number sat visibly off-centre.
    for specs, count in ((header, 3), (one_page, 1)):
        left = specs["previous"]["PositionX"] + specs["previous"]["Width"]
        right = specs["next"]["PositionX"]
        label = specs["page"]
        assert label["PositionX"] >= left and \
            label["PositionX"] + label["Width"] <= right, \
            "the page indicator is behind an arrow: %s" % specs
        assert abs(label["PositionX"] + label["Width"] / 2.0 - (left + right) / 2.0) \
            <= 1, "the page indicator is not centred between the arrows: %s" % specs
        # ... and centring the box is only half of it: the box used to fill the whole
        # space between the arrows, so its words started against one and the report
        # was "(1/1) is still too close to < and >".  Three units is the width of a
        # glyph, the least there can be between two things that are read as separate;
        # it is a number here rather than the code's own constant, because a bar that
        # moves with the code it is meant to catch catches nothing.
        assert label["PositionX"] - left >= 3 and \
            right - (label["PositionX"] + label["Width"]) >= 3, \
            "the page number is jammed against an arrow: %s" % specs
    # ... and it is sized for the longest page count the picker offers, not for the
    # palette that happened to be showing when the window opened
    long_palette = rows_of(picker.header_specs(names, 12, 0, 0, 12))
    assert long_palette["page"]["Width"] > header["page"]["Width"], \
        "12/12 would not fit the box built for 1/3"

    captions = rows_of(picker.caption_specs(bands))
    placed, _bottom = picker.layout(bands)
    assert captions["caption0"]["Label"] == picker.RECENT_CAPTION, captions
    # the palette's own name is said once, by the selector: a caption under the
    # recent row repeating it is the duplicate the report was about
    assert not captions["caption1"]["Label"], \
        "the palette name is painted again under the selector that names it"
    assert [caption for caption, _colours in bands if caption] == \
        [picker.RECENT_CAPTION], "a group is captioned that the selector already names"
    for index, (_caption, _colours, y, _rows) in enumerate(placed):
        if not _caption:
            continue
        caption = captions["caption%d" % index]
        assert caption["PositionY"] < y, "the caption is not above its squares"
        assert caption["PositionY"] + caption["Height"] <= y, \
            "the caption is painted over its own squares"
        # ... and it is not painted under the selector row either: it used to start
        # three units inside it, which cut the tops off the letters
        selector = header["palettes"]
        assert caption["PositionY"] >= selector["PositionY"] + selector["Height"], \
            "%s is drawn under the palette selector" % captions

    cells = rows_of(picker.cell_specs(bands, 0x1F4E79,
                                      picker.recent_colours(recent) + page))
    bottom_row = rows_of(picker.bottom_specs(bottom, 0x1F4E79, "1F4E79"))
    for name, props in list(header.items()) + list(captions.items()) + \
            list(cells.items()) + list(bottom_row.items()):
        assert props["PositionX"] >= 0 and props["PositionY"] >= 0, (name, props)
        assert props["PositionX"] + props["Width"] <= width, \
            "%s is outside the chooser on the right" % name
        assert props["PositionY"] + props["Height"] <= height, \
            "%s is below the bottom of the chooser" % name
    # the read-out: the colour's own name and value, and a field to type one in
    assert bottom_row["name"]["Label"] == picker.readout("", 0x1F4E79)
    assert "#1F4E79" in bottom_row["name"]["Label"]
    assert "Dark Gray 4" in picker.readout("Dark Gray 4", 0x111111)
    assert bottom_row["hex"]["Text"] == "1F4E79", "the hex field starts empty"
    # and the buttons: one OK that Enter answers, one Cancel, both flush with the
    # squares above them
    assert (bottom_row["ok"]["Label"], bottom_row["cancel"]["Label"]) == ("OK",
                                                                          "Cancel")
    assert bottom_row["ok"]["DefaultButton"] is True
    assert not bottom_row["cancel"]["DefaultButton"], \
        "Enter would answer Cancel, which is how a box says no to everything"
    right = picker._GRID_X + picker._GRID_W
    assert bottom_row["cancel"]["PositionX"] + bottom_row["cancel"]["Width"] == right
    assert bottom_row["ok"]["PositionX"] + bottom_row["ok"]["Width"] <= \
        bottom_row["cancel"]["PositionX"]
    # the recent row costs the page a row of squares, or the last row is unreachable
    assert picker.page_size(recent) == picker.CELLS - picker.COLUMNS


@test
def the_chooser_is_wide_enough_for_the_names_it_shows():
    """The window is as wide as the longest palette name needs - the grid is not.

    "Put the dialog a bit wider so *In this presentation* is not cut."  The deck's own
    colours are offered under that name (``palettes.deck_palette()``, asserted by
    ``deck_palette_lists_the_colours_the_deck_uses``): twenty characters, in a selector
    that had the one width the grid happened to need.  A list box cannot be asked how
    wide its words are (fact 46: no ``FontDescriptor`` on a peer, no text metrics), so
    the bar is the number ``dev/probe_picker_width.py`` photographs - the same words in
    a ``FixedText`` of the same font are 142 px of ink, 56 dialog units, before the
    drop-down arrow.  The squares are ten columns of the office's own size and stay
    that size; the window grows around them, the grid is centred in the extra, and the
    page number keeps the room the arrows leave it.
    """
    from plan_impress import picker
    name = "In this presentation"
    names = ["standard", "libreoffice", "freecolour-hlc", name]
    bands = picker.full_bands([], name)
    specs, (width, height) = picker._field_specs(
        names, bands, 5, 0, 0x1F4E79, "1F4E79", 0,
        entries=[("Blue 1", 0x2A57D7)] * picker.page_size([]), widest_pages=5)
    rows = dict((control, dict(props)) for control, _service, props in specs)
    # The bar is the number ``dev/probe_selector_fit.py`` photographs, not a formula
    # of the picker's own: the probe renders each name twice - in a ``FixedText``
    # nothing can cut, and in a dropdown at this width - and finds *In this
    # presentation* cut at 74 units and whole at 78.  The first version of this test
    # asked for the words and six units more, passed, and the name was cut in half on
    # the screen; a bar that low pins nothing, and a bar written with the code's own
    # constants moves when the code is wrong.
    selector = rows["palettes"]
    assert selector["Width"] >= 78, \
        "%d units is what the probe photographs as cut for %r" % (
            selector["Width"], name)
    # ... and for a name of *wide* letters, which is what the per-glyph constant has
    # to be sized for: the probe measures "Recently used" at 102 px of ink over 13
    # characters - 3.1 units a glyph, where "In this presentation" is 2.79 - and the
    # arrow and its padding cost 51 px, so 153 px = 61 units is the floor.
    assert picker.selector_width(["Recently used"]) >= 61, \
        "%d units cuts a name the probe measures at 153 px" % \
        picker.selector_width(["Recently used"])
    assert selector["Width"] >= len(name) * picker._LIST_CHAR_W + \
        picker._LIST_CHROME_W, "the box holds neither the words nor the arrow"
    assert selector["PositionX"] + selector["Width"] <= rows["previous"]["PositionX"], \
        "the selector is drawn under the pager"
    # the squares are not stretched to pay for the name, and they are centred, or the
    # extra width would leave them shoved into one side of their own popup
    cells = [dict(props) for control, _service, props in specs
             if control.startswith("cell")]
    left = min(cell["PositionX"] for cell in cells)
    right = max(cell["PositionX"] + cell["Width"] for cell in cells)
    assert right - left == picker._GRID_W, "the grid was stretched to pay for the name"
    assert abs(left - (width - right)) <= 1, \
        "the grid is not centred: %d units of margin left, %d right" % (
            left, width - right)
    # the page number keeps what it needs even in a window grown for a name
    room = rows["next"]["PositionX"] - (rows["previous"]["PositionX"]
                                        + rows["previous"]["Width"])
    assert rows["page"]["Width"] >= len(picker.page_label(4, 5)) * 2.8, \
        "the indicator lost its room to the selector: %d of %d" % (
            rows["page"]["Width"], room)
    # and nothing hangs outside the window it was measured for
    for control, _service, props in specs:
        props = dict(props)
        assert 0 <= props["PositionX"] and props["PositionX"] + props["Width"] \
            <= width, "%s is outside the chooser on the right" % control
        assert props["PositionY"] + props["Height"] <= height, \
            "%s is below the bottom of the chooser" % control
    # short names grow nothing: the deck's two-word list gets the same window no
    # names at all would, and it is never wider than the grid's own floor unless the
    # header's furniture needs the room
    assert picker.content_width(["standard", "tonal"]) == picker.content_width([])
    assert picker.content_width([]) >= picker.DIALOG_WIDTH


@test
def a_swatch_is_its_colour_inside_a_line_of_the_contrast_colour():
    """The bitmap a square is painted from: its colour, and one pixel of line.

    A colour cannot be given a line of its *own* by the toolkit - every ``BorderStyle``
    paints the theme's grey and ``BorderColor`` is ignored (fact 78) - so the line is
    drawn by :mod:`plan_impress.swatch`, with nothing beyond ``zlib`` and ``struct``
    because LibreOffice's own Python has no imaging library.  A file nobody can read is
    not a tested file, so this reads it back with the same two: the size the control is
    painted at, a row of nothing but the line above and below, the line at both sides,
    and the colour in the middle.
    """
    import struct
    import zlib
    from plan_impress import swatch
    fill, line = 0x1F4E79, 0xF2F2F2

    def rows_of(payload):
        """The decoded scanlines of a PNG written by :func:`swatch.png_bytes`."""
        assert payload[:8] == b"\x89PNG\r\n\x1a\n", \
            "not a PNG: the office would paint an empty square"
        assert payload[12:16] == b"IHDR", payload[12:16]
        width, height, depth, kind = struct.unpack(">IIBB", payload[16:26])
        assert (depth, kind) == (8, 2), \
            "not 8-bit RGB, so not the colour that was asked for"
        body, pos = [], 8
        while pos + 8 <= len(payload):
            size, kind = struct.unpack(">I4s", payload[pos:pos + 8])
            if kind == b"IDAT":
                body.append(zlib.decompress(payload[pos + 8:pos + 8 + size]))
            pos += 12 + size
        raw = b"".join(body)
        stride = 1 + 3 * width
        assert len(raw) == stride * height, \
            "%d bytes for a %dx%d RGB image" % (len(raw), width, height)
        return width, height, stride, [raw[i * stride:(i + 1) * stride]
                                       for i in range(height)]

    def pixel(row, x):
        return (row[1 + 3 * x], row[2 + 3 * x], row[3 + 3 * x])

    def rgb(colour):
        return (colour >> 16 & 255, colour >> 8 & 255, colour & 255)

    width, height, _stride, rows = rows_of(swatch.png_bytes(23, 17, fill, line))
    assert (width, height) == (23, 17), (width, height)
    assert all(row[0] == 0 for row in rows), "a scanline must start with its filter byte"
    assert all(pixel(row, x) == rgb(line) for row in (rows[0], rows[-1])
               for x in range(width)), "no line across the top and the bottom"
    middle = rows[height // 2]
    assert pixel(middle, 0) == rgb(line) and pixel(middle, width - 1) == rgb(line), \
        "the line does not close on the sides"
    assert pixel(middle, width // 2) == rgb(fill), "the colour is not what is painted"
    # a square with no line is the colour right to the edge: the fallback when no
    # bitmap can be made at all, which has to be the old look and not a hole
    _w, _h, _s, rows = rows_of(swatch.png_bytes(4, 4, fill))
    assert all(pixel(row, x) == rgb(fill) for row in rows for x in range(4)), rows
    # the size the bitmap is drawn at is the size the control is painted at, because
    # the line is one pixel *of the bitmap* (facts 28 and 64: 2.53 x 2.39 px to a unit)
    assert swatch.bitmap_size(9, 7) == (23, 17), swatch.bitmap_size(9, 7)


@test
def the_line_round_a_colour_contrasts_with_what_it_sits_on():
    """Black on a dark theme needs a light line; white on a light theme a dark one.

    "look how the default palette color are drawn, with a thin white border on a dark
    theme, and think dark border and a white theme."  The office's own dropdown does
    exactly that and no property of ours can (fact 78), so the rule lives in
    :func:`plan_impress.swatch.ring_colour` and is pinned against the two colours that
    show whether it is right - and against the case where nothing says which theme the
    office is on, which has to fail safe: each square is then lined against its own
    colour, so a black square never arrives without an edge.
    """
    from plan_impress import swatch
    on_dark = swatch.ring_colour(0x000000, dark=True)
    on_light = swatch.ring_colour(0xFFFFFF, dark=False)
    assert swatch.luminance(on_dark) >= 0xC0, \
        "%06X is not a light line for a dark theme" % on_dark
    assert swatch.luminance(on_light) <= 0x60, \
        "%06X is not a dark line for a light theme" % on_light
    assert on_dark != on_light, "one line for both themes is one wrong theme"
    # one line for every square of a grid, which is how the office's own looks
    assert swatch.ring_colour(0x2A57D7, dark=True) == on_dark
    assert swatch.ring_colour(0x93CAD7, dark=False) == on_light
    # nothing said about the theme: the colour that would disappear gets the light
    # line, the one that already stands out gets the dark one
    assert swatch.ring_colour(0x000000) == on_dark
    assert swatch.ring_colour(0xFFFFFF) == on_light
    assert swatch.ring_colour(0x1F4E79) == on_dark, "a dark blue on a dark dialog"
    assert swatch.ring_colour(0xF79646) == on_light
    # and neither is the grey the office would have drawn: that is the line that made
    # the dark squares vanish (dev/probe_border_colour.py, fact 78)
    assert (swatch.luminance(on_dark), swatch.luminance(on_light)) != (0x2B, 0x2B)


@test
def the_chooser_tells_a_dark_theme_from_the_desktop():
    """Which theme the office is on: asked of the desktop, because nothing else says.

    ``getSettings`` and ``XStyleFacility`` are not on the toolkit proxy and the one
    theme node that will answer, ``/org.openoffice.Office.Common/Appearance``, says
    ``ApplicationAppearance = 0`` and ``LibreOfficeTheme = 0`` on this **dark** office:
    both are its "follow the system" value and no enum in the type repository says which
    number means dark (``dev/probe_theme.py``, ``dev/probe_border_colour.py``).  So the
    files LibreOffice itself reads when it is told to follow the system are read here,
    and the answer has to be right for them and ``None`` - never a guess - when there is
    nothing to read at all.
    """
    import os
    import tempfile
    from plan_impress import swatch

    def says(**files):
        home = tempfile.mkdtemp()
        for relative, contents in files.items():
            path = os.path.join(home, relative)
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, "w") as handle:
                handle.write(contents)
        return swatch.theme_is_dark(environ={}, home=home)

    gtk = os.path.join(".config", "gtk-3.0", "settings.ini")
    assert says(**{gtk: "[Settings]\ngtk-application-prefer-dark-theme=true\n"}) is True
    assert says(**{gtk: "[Settings]\ngtk-theme-name=Arc-Dark\n"}) is True
    assert says(**{gtk: "[Settings]\ngtk-theme-name=Adwaita\n"}) is False
    assert says(**{".gtkrc-2.0": 'gtk-theme-name="Breeze Dark"\n'}) is True
    assert says(**{os.path.join(".config", "kdeglobals"):
                   "[General]\nColorScheme=Breeze\n"}) is False
    assert says() is None, "with nothing to read the honest answer is 'unknown'"
    # what the developer says beats everything: a screenshot has to be able to say
    # which theme it was taken in (the PLAN_IMPRESS_DATA_DIR of the theme question)
    assert swatch.theme_is_dark(environ={"PLAN_IMPRESS_THEME": "light"},
                                home="/nonexistent") is False
    assert swatch.theme_is_dark(environ={"PLAN_IMPRESS_THEME": "dark"},
                                home="/nonexistent") is True
    # and the environment's own spelling of it, for a desktop that only says it there
    assert swatch.theme_is_dark(environ={"GTK_THEME": "Adwaita:dark"},
                                home="/nonexistent") is True


@test
def colours_are_painted_flat_with_a_contrast_line():
    """Every colour is a flat square with a thin line of its own, never a bevel.

    The report was "a very ugly perspective-style border around the color ... both in
    the palette and in the option screen"; the follow-up was to copy the office's own
    grid, which lines every swatch in the contrast of the theme.  The first of those is
    the theme's **button bevel** - dark above and to the left, light below and to the
    right, measured in ``dev/probe_swatch_look.py`` - and a button model has no
    ``Border`` to switch it off with (fact 65).  The second is something no property can
    do: a label's line is the theme's colour in every ``BorderStyle`` there is,
    ``BorderColor`` accepted and ignored (``dev/probe_border_colour.py``, fact 78).  So
    every colour - the squares of the grid, the chip under them, the swatches beside the
    hex fields - is an **image control** carrying a bitmap :mod:`plan_impress.swatch`
    draws, and what a test can pin without a display is the four properties that make
    that bitmap land: no office border to fight the drawn line, a ``ScaleMode`` that
    covers the square, no tab stop, and the colour written where a peer cannot hide it.
    """
    from plan_impress import dialog, picker, swatch
    recent = [("#112233", 0x112233)]
    bands = picker.full_bands(recent, "standard")
    entries = picker.recent_colours(recent) + [("Blue 1", 0x2A57D7)]
    # the colours a square may stand for: the page's, and the colour being edited for
    # the squares the palette does not fill (which are switched off, so they cannot be
    # picked - see picker_hides_the_cells_beyond_the_palette)
    hexes = set(config.color_to_hex(colour) for _name, colour in entries)
    hexes.add(config.color_to_hex(0x1F4E79))
    squares = dict((name, (service, dict(props))) for name, service, props
                   in picker.cell_specs(bands, 0x1F4E79, entries))
    assert len(squares) == picker.CELLS, len(squares)
    for name, (service, props) in squares.items():
        assert service == picker._MODEL_IMAGE, \
            "%s is a %s: a button brings the theme's bevel and a label can only be " \
            "lined in the theme's own colour" % (name, service.rsplit(".", 1)[-1])
        assert props["Border"] == 0, "%s asks for the office's line as well" % name
        assert props["ScaleMode"] == swatch.SCALE_MODE_FILL, \
            "%s would leave the control's own colour round the bitmap" % name
        assert props["Tabstop"] is False, "%s can be tabbed to" % name
        assert props["Tag"] in hexes, \
            "%s does not say which colour it stands for" % name
    # the chip that says what the pointer is over is the same kind of square
    bottom = picker.bottom_of(bands)
    below = dict((name, (service, dict(props))) for name, service, props
                 in picker.bottom_specs(bottom, 0x1F4E79, "1F4E79"))
    assert below["preview"][0] == picker._MODEL_IMAGE, "the chip is a bevelled button"
    assert below["preview"][1]["Border"] == 0, below["preview"]
    assert below["preview"][1]["Tag"] == "1F4E79", below["preview"][1]
    # and so is the one in the settings dialog: the "option screen" of the report
    values = {"MutedColor": "B0B0B0", "TextColor": "000000",
              "Title": "Plan", "master": "Default", "SectionColor": "1F4E79"}
    rows = dict((name, (service, dict(props))) for name, service, props
                in dialog._field_specs(values, ["Default"]))
    for field in dialog._COLOUR_FIELDS:
        service, props = rows["swatch" + field]
        assert service == dialog._IMAGE, \
            "the %s swatch is a %s" % (field, service.rsplit(".", 1)[-1])
        assert props["Border"] == 0, props
        assert props["Tag"] == values[field], props
        assert props["BackgroundColor"] == config.hex_to_color(values[field], 0), props
    # the buttons that stay buttons (they are buttons: the office bevels those)
    assert rows["ok"][0] == dialog._BUTTON and rows["cancel"][0] == dialog._BUTTON


@test
def every_colour_carries_a_bitmap_of_its_own():
    """The squares and swatches really are given a bitmap, lined for this theme.

    The test above pins the description; this is as close as an assertion gets to the
    picture.  After the chooser has been shown, every square's model must answer a
    ``Graphic`` - the office paints nothing without one - and what was asked for has to
    be that square's own colour, inside a line of the contrast colour for the theme the
    office is on, at the pixel size the square is painted at.  The graphics
    :mod:`plan_impress.swatch` has already made are the record of that;
    ``dev/probe_swatch_ring.py`` is the photograph of the same thing.
    """
    from plan_impress import dialog, picker, swatch
    ctx = lo.connect()
    colours = [("Black", 0x000000), ("Blue", 0x2A57D7), ("White", 0xFFFFFF)]
    window = picker.ColourPicker(ctx, [("Few", colours)], current=0x112233)
    window.build()
    try:
        window.show()
        drawn = set(swatch._GRAPHICS)
        rect = window.control(picker.cell_name(0)).getPeer().getPosSize()
        for index, (name, colour) in enumerate(colours):
            control_model = window.model.getByName(picker.cell_name(index))
            assert getattr(control_model, "Graphic", None) is not None, \
                "%s has no bitmap: the office paints a flat colour with no edge" % name
            ring = swatch.ring_colour(colour, window.dark)
            assert (colour, rect.Width, rect.Height, ring, swatch.RING_WIDTH) in drawn, \
                "%s was not drawn with a %06X line at the %dx%d it is painted at" \
                % (name, ring, rect.Width, rect.Height)
            assert control_model.Tag == config.color_to_hex(colour), control_model.Tag
        # the chip under the grid is a drawn square as well, and it is not a square of
        # the grid: at the grid's bitmap size its line came out a pixel and a half
        # thick, which is the kind of thing only the pixels of the control tell you
        chip = window.control("preview").getPeer().getPosSize()
        window._show_colour(0x000000, "Black")
        lined = (0x000000, chip.Width, chip.Height,
                 swatch.ring_colour(0x000000, window.dark), swatch.RING_WIDTH)
        where = "the chip is not lined at the %dx%d it is painted at" % (
            chip.Width, chip.Height)
        assert lined in set(swatch._GRAPHICS), where
    finally:
        window.dispose()

    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0x000000, "text_color": 0xFFFFFF})
    form = dialog.SettingsDialog(ctx, settings, ["Master1"])
    form.build()
    try:
        drawn = set(swatch._GRAPHICS)
        for field in dialog._COLOUR_FIELDS:
            control_model = form.control_model("swatch" + field)
            colour = config.hex_to_color(form.values[field], 0)
            assert getattr(control_model, "Graphic", None) is not None, \
                "the %s swatch paints no bitmap" % field
            assert (colour, swatch.bitmap_size(dialog._SWATCH_W, dialog._SWATCH_H)[0],
                    swatch.bitmap_size(dialog._SWATCH_W, dialog._SWATCH_H)[1],
                    swatch.ring_colour(colour, form._dark),
                    swatch.RING_WIDTH) in drawn, \
                "the %s swatch is not lined for this theme" % field
        assert form.warnings == [], form.warnings
    finally:
        form.dispose()


@test
def picker_paints_nothing_on_top_of_anything_else():
    """No two controls of the chooser occupy the same pixels.

    "The text is cramped" meant the first group caption began three units *inside* the
    selector row, so the tops of its letters were drawn behind the dropdown.  Two
    controls in one place is invisible to an assertion about either one of them alone
    and cheap to catch from the specs the widget is built from, so it stays caught -
    here for the whole chooser, including the squares, the captions and the bottom row.
    """
    from plan_impress import picker
    recent = [("#%06X" % (index * 0x010101), index * 0x010101)
              for index in range(1, 4)]
    page = [("Blue %d" % index, index * 0x010101) for index in range(1, 20)]
    entries = picker.recent_colours(recent) + page
    bands = picker.full_bands(recent, "standard")
    specs, (width, height) = picker._field_specs(
        ["standard", "libreoffice"], bands, 2, 0, 0x1F4E79, "1F4E79", 0,
        entries=entries, widest_pages=2)
    painted = []
    for name, _service, props in specs:
        props = dict(props)
        if name.startswith("cell") and not props.get("HelpText"):
            continue            # a square the palette does not fill is switched off
        if name.startswith("caption") and not props.get("Label"):
            continue            # a group with nothing to say over it is switched off
        painted.append((name, props))
    assert len(painted) > 20, "nothing was checked: %s" % painted
    for index, (left_name, left) in enumerate(painted):
        for right_name, right in painted[index + 1:]:
            apart = (left["PositionX"] + left["Width"] <= right["PositionX"]
                     or right["PositionX"] + right["Width"] <= left["PositionX"]
                     or left["PositionY"] + left["Height"] <= right["PositionY"]
                     or right["PositionY"] + right["Height"] <= left["PositionY"])
            assert apart, "%s is drawn on top of %s: %s / %s" % (
                left_name, right_name, left, right)


@test
def a_colour_is_a_square_of_pixels_and_never_a_strip():
    """Every colour carrier is square in *pixels*, which a dialog unit is not.

    "the color picker's color sample must be exact squares, not rectangles".  A dialog
    unit is 2.53 px across and 2.39 px down (fact 28), so a control that is a square in
    the model is a rectangle on the screen: the 9 x 7 units a square of the grid used to
    be is 23 x 17 px, and the swatch beside a hex field in the settings dialog was
    22 x 12 units, 56 x 29 px - a strip.  ``dev/probe_picker_ink.py`` paints candidate
    pairs and photographs them (13 x 14 units is 33 x 33 px, the smallest pair that is
    the same both ways at a size one can click); the rule that comes out of the
    photographs is :func:`swatch.square_units`, and everything that shows a colour in
    this extension is sized by it, so they cannot drift apart.
    """
    from plan_impress import dialog, picker, swatch
    carriers = [("a square of the chooser's grid", picker.CELL_W, picker.CELL_H),
                ("the chip under the grid", picker._SWATCH_W, picker._SWATCH_H),
                ("the swatch beside a hex field", dialog._SWATCH_W, dialog._SWATCH_H)]
    for what, width, height in carriers:
        assert width >= 8, "%s is %d units: too small to click or to read" % (
            what, width)
        assert height == swatch.square_units(width), \
            "%s is %dx%d units, which the photographs come back as %d x %d px" % (
                what, width, height, width * swatch.PX_PER_UNIT_X,
                height * swatch.PX_PER_UNIT_Y)
        assert abs(width * swatch.PX_PER_UNIT_X
                   - height * swatch.PX_PER_UNIT_Y) <= 1, \
            "%s is %dx%d units: %d px wide and %d px tall is not a square" % (
                what, width, height, width * swatch.PX_PER_UNIT_X,
                height * swatch.PX_PER_UNIT_Y)
    # the constants are no use unless the rectangles the two widgets are built from
    # are the same squares
    values = {"MutedColor": "B0B0B0", "TextColor": "000000",
              "Title": "Plan", "Master": "Default"}
    carriers += [("the swatch in the settings dialog's specs", 0, 0)]
    for name, _service, props in dialog._field_specs(values, ["Default"]):
        if not name.startswith("swatch"):
            continue
        props = dict(props)
        assert props["Height"] == swatch.square_units(props["Width"]), \
            "the %s is %dx%d units in the dialog's own specs" % (
                name, props["Width"], props["Height"])
        carriers[-1] = (name, props["Width"], props["Height"])
    for name, _service, props in picker.bottom_specs(60, 0x1F4E79):
        if name != "preview":
            continue
        props = dict(props)
        assert props["Height"] == swatch.square_units(props["Width"]), \
            "the %s is %dx%d units in the chooser's own specs" % (
                name, props["Width"], props["Height"])
    assert all(width and height for _what, width, height in carriers), \
        "nothing was checked: %s" % (carriers,)


@test
def the_grid_leaves_clear_air_between_its_squares():
    """Two colours that touch read as one block, so the grid is a grid of squares.

    "add a fex px between colors in the menu, just like in the font color picker in
    native libreoffice".  The squares used to tile - ``x + column * CELL_W`` - which
    makes ten of them one rectangle of colour with no seam to see a choice in; the
    office's own dropdown separates its swatches.  :func:`picker.cell_position` is the
    one place the pitch is decided, and the grid's width has to pay for the air or the
    last column is drawn outside the window.
    """
    from plan_impress import picker, swatch
    assert picker._CELL_GAP >= 2, \
        "%d units of air is %d px: nothing between two colours" % (
            picker._CELL_GAP, picker._CELL_GAP * swatch.PX_PER_UNIT_X)
    first = picker.cell_position(0)
    right = picker.cell_position(1)
    assert right[0] - (first[0] + first[2]) == picker._CELL_GAP, \
        "two squares of one row are %d units apart, not %d" % (
            right[0] - (first[0] + first[2]), picker._CELL_GAP)
    below = picker.cell_position(picker.COLUMNS)
    assert below[1] - (first[1] + first[3]) == picker._CELL_GAP, \
        "two squares of one column are %d units apart" % (
            below[1] - (first[1] + first[3]))
    assert picker._GRID_W == picker.COLUMNS * picker.CELL_W + \
        (picker.COLUMNS - 1) * picker._CELL_GAP, \
        "the grid's width does not count the air, so the last column is outside"


@test
def colour_squares_are_square_and_apart_on_the_screen():
    """The peers agree with the rule: the same number of pixels both ways, not touching.

    Both reports are about pixels and no property says what a control paints (fact 46),
    so this asks the real controls what geometry their peers were given - which is the
    peer, in pixels, and the only thing in the API that answers for a square.  A cell
    back at 9 x 7 units fails the first assertion with 23 x 17 px; ``_CELL_GAP`` at 0
    fails the second with 0 px between two neighbours; and the field a colour is typed
    into is asked the same question, because "#1F4E79" being cut in half is the same
    kind of report as a square that is not one.
    """
    from plan_impress import picker
    ctx = lo.connect()
    colours = [("Blue %d" % index, 0x2A57D7 + 0x010101 * index)
               for index in range(1, 21)]
    window = picker.ColourPicker(ctx, [("Few", colours)], current=0x112233,
                                 recent=[("#112233", 0x112233)])
    window.build()
    try:
        window.show()

        def rect(name):
            size = window.control(name).getPeer().getPosSize()
            return (int(size.X), int(size.Y), int(size.Width), int(size.Height))

        for name in (picker.cell_name(0), picker.cell_name(1), "preview"):
            _x, _y, width, height = rect(name)
            assert abs(width - height) <= 1, \
                "%s is %dx%d px: a rectangle, not the square that was asked for" % (
                    name, width, height)
        first, right = rect(picker.cell_name(0)), rect(picker.cell_name(1))
        across = right[0] - (first[0] + first[2])
        assert across >= 3, "two colours %d px apart read as one block" % across
        below = rect(picker.cell_name(picker.COLUMNS))
        down = below[1] - (first[1] + first[3])
        assert down >= 3, "two colours one above the other are %d px apart" % down
        # the same question asked of the one control that carries words a user has to
        # be able to read: the field a colour is typed into
        assert rect("hex")[2] >= 70, \
            "the hex field is %d px, and the probe photographs '#1F4E79' at 64 px of " \
            "digits before the field's own padding" % rect("hex")[2]
    finally:
        window.dispose()


@test
def the_hex_field_is_wide_enough_for_the_value_it_shows():
    """The field a colour is typed into is not cut - its seven characters fit.

    "the field that can be used to set the hex value of the color in the color pick is a
    bit too narrow".  It borrowed the button's width, 26 units = 66 px, and
    ``config.hex_to_color`` accepts a leading ``#``, so seven characters have to fit
    where the box was painted for six.  ``dev/probe_picker_ink.py`` paints the same
    value into fields of four widths and photographs the ink: 49, 54, 62 and 64 px, the
    last of them in a 73 px box - so it stops growing there and was clipped at the 66 px
    this had.  The bar is those 64 px of digits plus the padding the field keeps for
    itself; the peer is asked for the same number in
    :func:`colour_squares_are_square_and_apart_on_the_screen`.
    """
    from plan_impress import picker, swatch
    specs, (_width, _height) = picker._field_specs(
        ["standard"], picker.full_bands([], "standard"), 1, 0, 0x1F4E79, "1F4E79", 0)
    rows = dict((name, dict(props)) for name, _service, props in specs)
    box = rows["hex"]["Width"] * swatch.PX_PER_UNIT_X
    assert box >= 70, \
        "the hex field is %d units = %d px, and the probe photographs '#1F4E79' at " \
        "64 px of digits before the field's own padding" % (rows["hex"]["Width"], box)


@test
def the_message_box_is_wide_enough_for_the_path_it_prints():
    """The log path *Toggle Debug Log* prints reaches its box whole.

    "the *debug log enable/disable* window message has not enough width, the message is
    cut (incomplete path)".  A ``FixedText`` wraps nothing (fact 72), so a line longer
    than its own box is not wrapped - it is painted past the edge and the tail never
    appears; the box wraps in Python at ``_BOX_CHARS`` and that number has to agree with
    the width of the label.  ``dev/probe_message_width.py`` photographs the path's own
    characters at the box's font: 240 px of ink over 30 of them, 296 px over 38, and the
    label stops painting at its own edge - which is how 44 characters (344 px) in a
    278 px label looked like a truncated path.
    """
    from plan_impress import dialog, swatch
    path = "/home/derumigny/.config/libreoffice/4/user/planimpress/debug.log"
    text = "Debug log enabled, writing to:\n%s" % path
    lines = dialog.box_lines(text)
    room = dialog._BOX_TEXT_W * swatch.PX_PER_UNIT_X
    for line in lines:
        assert len(line) * dialog._BOX_CHAR_W <= room, \
            "%r is %d characters, about %d px of ink, in a label %d units = %d px wide" \
            % (line, len(line), len(line) * dialog._BOX_CHAR_W,
               dialog._BOX_TEXT_W, room)
    assert path in "".join(lines), "the wrapping lost part of the path: %s" % lines
    specs, (width, _height) = dialog.box_specs(text, 1)
    for name, _service, props in specs:
        if not name.startswith("text"):
            continue
        props = dict(props)
        assert props["PositionX"] + props["Width"] <= width, \
            "%s is painted outside the window" % name


@test
def the_page_indicator_is_not_cut():
    """The page number has air round it, or its last digit is painted past the box.

    "in the color picker box, the text 2/2 of the corresponding page is slightly cut on
    the right (not enough padding?)".  The indicator's box is sized by arithmetic,
    because a ``FixedText`` has no ``TextAlign`` (fact 72) and no way to be asked how
    wide its words are (fact 46); at ``+ 1`` unit of bearing ``dev/probe_picker_ink.py``
    photographs "1/2" as 20 px of ink in a 23 px box, 2 px of air before the first digit
    and 1 px after the last.  The bars are the ink that probe measures for the shortest
    and the widest string the picker answers with, plus 6 px to be sure.
    """
    from plan_impress import picker, swatch
    for pages, ink in ((2, 20), (12, 32)):
        label = picker.page_label(pages - 1, pages)
        units = picker.page_label_width(pages)
        assert units * swatch.PX_PER_UNIT_X >= ink + 6, \
            "%r paints %d px in a box of %d units = %d px" % (
                label, ink, units, units * swatch.PX_PER_UNIT_X)


@test
def clicking_a_square_answers_the_picker():
    """A square answers the chooser on a click, and names itself on the pointer.

    The squares are labels now, not buttons, because a button is painted with the
    theme's bevel around the colour (fact 77) - and a label fires no action event at
    all, so a click has to arrive through the mouse listener that was really attached
    to the peer.  This is what says the grid still answers at all.
    """
    from plan_impress import picker
    ctx = lo.connect()
    colours = [("Blue", 0x2A57D7), ("Green", 0x22AA44), ("Black", 0x000000)]
    window = picker.ColourPicker(ctx, [("Few", colours)], current=0x112233)
    window.build()
    try:
        window.show()
        squares = [listener for _control, listener in window._listeners
                   if hasattr(listener, "mouseReleased")]
        assert len(squares) == picker.CELLS, \
            "a grid of %d squares has %d click listeners" % (picker.CELLS, len(squares))
        squares[1].mouseEntered(object())      # the pointer goes over the second one
        assert window.current == 0x22AA44, window.current
        assert "Green" in window.model.getByName("name").Label, \
            window.model.getByName("name").Label
        squares[1].mouseReleased(object())     # and a click on it is the answer
        assert window.accepted, "clicking a colour did not answer the chooser"
        assert window.current == 0x22AA44, window.current
    finally:
        window.dispose()


@test
def picking_a_colour_fills_the_field_and_is_remembered():
    """Clicking a swatch fills the hex field and puts the colour in Recent."""
    from plan_impress import config, dialog, picker as picker_module
    ctx = lo.connect()
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x000000,
                     "recent_colors": [0x22AA44]})
    window = dialog.SettingsDialog(ctx, settings, ["Master1"])
    window.build()
    original = picker_module.pick
    seen = []

    def answer(ctx, entries, current=0, title="", recent=None):
        seen.append((entries, current, title, recent))
        return 0x1F6EC8

    picker_module.pick = answer
    try:
        window._peer()
        window._pick_colour("MutedColor")
    finally:
        picker_module.pick = original
    try:
        assert window._text("MutedColor") == "1F6EC8", window._text("MutedColor")
        assert window.settings["recent_colors"][0] == 0x1F6EC8, window.settings
        assert seen and seen[0][1] == 0xB0B0B0, \
            "the picker did not start at the current colour"
        assert seen[0][2], "the picker opened without a title"
        offered = [name for name, _colours in seen[0][0]]
        assert "standard" in [name.lower() for name in offered], offered[:4]
        # the colours the user picked before are a group of their own above the
        # grid, as in the office's dropdown - not another palette in the list
        assert not [name for name in offered if name.lower() == "recently used"], \
            "the recent colours are not a palette: %s" % offered[:4]
        remembered = picker_module.recent_colours(seen[0][3])
        assert [colour for _name, colour in remembered] == [0x22AA44], remembered
        # and it is saved: config.save() writes every known key, so a result()
        # that drops recent_colors would silently forget what was just picked
        result = window.result()
        # both the newly picked colour and the one that was already
        # remembered go to the file: config.save() writes every key
        assert result["recent_colors"] == [0x1F6EC8, 0x22AA44], result
    finally:
        window.dispose()


@test
def deck_palette_lists_the_colours_the_deck_uses():
    """The picker offers the presentation's own colours first."""
    from plan_impress import palettes
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, os.path.join(ROOT, "tests/fixtures/sections.odp"),
                      hidden=True)
    try:
        entries = palettes.deck_palette(doc)
    finally:
        lo.close(doc)
    assert entries, "no colours found in the fixture deck"
    name, colours = entries[0]
    assert name == "In this presentation", name
    assert colours, entries
    # a cell is built by unpacking each entry, so the shape is part of the
    # contract - bare ints once made the picker die inside its listener
    for label, colour in colours:
        assert isinstance(label, str) and label, (label, colour)
        assert isinstance(colour, int) and 0 <= colour <= 0xFFFFFF, (label, colour)
    values = [colour for _label, colour in colours]
    # the fixture's own blues, so a plan slide can match the deck
    assert 0x3465A4 in values or 0x729FCF in values, [hex(c) for c in values]


# the text of the box the *Toggle Debug Log* report turned on: a long path is one
# long word, which is the case a wrapper gets wrong
_LOG_PATH = "/".join(["a-very-long-profile-directory-name"] * 3) + "/planimpress/debug.log"
_BOX_TEXT = "Debug log enabled, writing to\n%s" % _LOG_PATH


@test
def message_box_reports_what_it_says():
    """Our own message box fits its text and its buttons answer what they promise.

    ``Toolkit.createMessageBox`` is gone - its docstring says why - so everything
    the extension tells the user goes through the box built here.  A box that paints
    only its OK button is indistinguishable from a menu item that does nothing, which
    is the report this came from, so the words themselves are what is asserted.
    """
    from plan_impress import dialog
    lines = dialog.box_lines(_BOX_TEXT)
    assert lines[0] == "Debug log enabled, writing to", lines
    assert any(line.startswith("a-very-long-profile") for line in lines[1:]), lines
    assert all(len(line) <= dialog._BOX_CHARS for line in lines), \
        "a line wider than the box is drawn outside it"
    assert _LOG_PATH.replace("/", "") in "".join(lines).replace("/", "").replace(" ", ""), \
        "the log file the user is being sent to is not in the box"
    assert dialog.box_lines("a\n\nb") == ["a", "", "b"], "a blank line vanished"
    assert dialog.box_lines("") == [""], "an empty message would build a box with no text"

    for buttons, labels in ((1, ("OK", "Cancel")), (5, ("Yes", "No"))):
        specs, (width, height) = dialog.box_specs(_BOX_TEXT, buttons)
        controls = dict((name, dict(props)) for name, _service, props in specs)
        text = dict((name, props) for name, props in controls.items()
                    if name.startswith("text"))
        pressed = dict((name, props) for name, props in controls.items()
                       if not name.startswith("text"))
        assert len(text) == len(lines), "one label per line: %s against %s" % (text, lines)
        assert sorted(props["Label"] for props in pressed.values()) == sorted(labels), \
            sorted(pressed)
        for name, props in controls.items():
            assert props["PositionX"] >= 0 and props["PositionY"] >= 0, (name, props)
            assert props["PositionX"] + props["Width"] <= width, \
                "%s is outside the box on the right" % name
            assert props["PositionY"] + props["Height"] <= height, \
                "%s is below the bottom of the box" % name
            assert props["FontHeight"] >= dialog._FONT, \
                "%s is smaller than the menu text" % name
        assert min(props["PositionX"] for props in pressed.values()) > 0
        assert max(props["PositionX"] + props["Width"]
                   for props in pressed.values()) == width - dialog._BOX_MARGIN, \
            "the buttons are not in the bottom right corner"
        assert min(props["PositionY"] for props in pressed.values()) >= \
            max(props["PositionY"] + props["Height"] for props in text.values()), \
            "the buttons are painted over the message"
        default = [name for name, props in pressed.items() if props.get("DefaultButton")]
        assert default == [labels[0].lower()], \
            "Enter must answer %s, not the other one: %s" % (labels[0], default)


@test
def message_box_answers_its_buttons():
    """The buttons answer the codes ``confirm`` reads, with the office holding the window.

    ``message()`` itself cannot be called from here: it blocks until somebody
    presses something.  :func:`dialog._build_box` is the same box without the modal
    loop, so the answer each button gives - and that Enter gives the *primary* one,
    which is where a ``DefaultButton`` on Cancel once made every box say no - is
    checked against a real window.
    """
    from plan_impress import dialog
    ctx = lo.connect()
    text = "Remove the plan slides of this deck?"
    for buttons, answers, primary, secondary in (
            (1, {"ok": dialog.RESULT_OK, "cancel": dialog.RESULT_CANCELLED},
             dialog.RESULT_OK, dialog.RESULT_CANCELLED),
            (5, {"yes": dialog.RESULT_YES, "no": dialog.RESULT_NO},
             dialog.RESULT_YES, dialog.RESULT_NO)):
        box = dialog._build_box(ctx, text, buttons, dialog.TITLE)
        try:
            dialog._show_box(box["dialog"], ctx, dialog.TITLE)
            names = list(box["model"].ElementNames)
            for name in answers:
                assert name in names, "no %s button: %s" % (name, names)
            assert len([name for name in names if name.startswith("text")]) == \
                len(dialog.box_lines(text)), names
            place = box["dialog"].getPeer().getPosSize()
            # fact 27: a dialog that is not given its size stays at the 300x450
            # *unit* default, which is about 760x1075 px - a box that size is
            # obviously wrong for one line of text, so the numbers prove the model
            # property took effect
            assert 200 < place.Width < 600 and 80 < place.Height < 600, \
                "the window kept the AWT default instead of its text: %s" % (place,)
            for name, expected in answers.items():
                box["state"]["result"] = -1
                box["press"](name)
                assert box["state"]["result"] == expected, \
                    "%s answered %s" % (name, box["state"]["result"])
            box["state"]["result"] = -1
            box["press_key"](dialog._KEY_RETURN)
            assert box["state"]["result"] == primary, "Enter answered the wrong button"
            box["state"]["result"] = -1
            box["press_key"](dialog._KEY_ESCAPE)
            assert box["state"]["result"] == secondary, "Escape answered the wrong button"
        finally:
            box["dialog"].dispose()


@test
def toggling_the_debug_log_says_what_it_did():
    """*Toggle Debug Log* has to show something, and say where the log is in full.

    The Job always ran and always moved the marker; what was missing was the report.
    Both halves are asserted here: the marker the logger looks for really flips, and
    a box that names the log file is asked for - with the office's own
    ``createMessageBox`` this call produced a window with nothing in it.  The path then
    has to *reach* the box, whole: the first version wrapped at 44 characters, painted
    344 px of path in a 278 px label and the tail never appeared.
    """
    import handler
    from plan_impress import config, dialog
    folder = os.path.join(ROOT, "out", "profile-debug")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    ctx = FakeContext(folder)
    path = config.debug_log_path(ctx)
    marker = os.path.join(os.path.dirname(path), "debug")
    if os.path.exists(marker):
        os.remove(marker)
    shown = []
    original = dialog.message

    def record(context, text, buttons=1, title=dialog.TITLE):
        shown.append((text, buttons, title))
        return dialog.RESULT_OK

    dialog.message = record
    try:
        job = handler.Debug(ctx)
        job.do_debug()
        assert os.path.exists(marker), "no marker: the log would not be written"
        assert shown, "the command showed nothing at all"
        text, buttons, _title = shown[0]
        assert "enabled" in text and "disabled" not in text, text
        assert path in text, "the box does not say where the log is: %s" % text
        assert buttons == 1, "an OK box is enough: %s" % buttons
        del shown[:]
        job.do_debug()
        assert not os.path.exists(marker), "the marker is still there: the log is on"
        assert shown and "disabled" in shown[0][0], shown
        assert path in shown[0][0], shown
    finally:
        dialog.message = original
        if os.path.exists(marker):
            os.remove(marker)


@test
def dialog_controls_are_laid_out_apart():
    """The peer geometry of the real dialog: distinct, non-zero, inside the window.

    The settings dialog used to open as a corner-sized window with every control
    on top of the others, and no model-level assertion noticed, because the
    controls were inserted without any geometry at all (their models came from the
    service manager, which gives them no ``PositionX``/``Width`` properties).  This
    checks what the user sees, measured on the native peers; the same thing by eye
    is ``python3 dev/debug_dialog_form.py show 8`` plus a screenshot.
    """
    from plan_impress import dialog
    ctx = lo.connect()
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x1F6EC8,
                     "title": "Plan", "master": "Master2"})
    window = dialog.SettingsDialog(ctx, settings, ["Master1", "Master2"])
    window.build()
    try:
        window._peer()
        size = window.dialog.getPosSize()
        assert size.Width > 0 and size.Height > 0, "the dialog has no size"
        # the window must follow the model rather than the 300x450 default, which
        # the aspect ratio shows without depending on the display's scaling
        wanted = dialog.DIALOG_WIDTH / float(dialog.DIALOG_HEIGHT)
        got = size.Width / float(size.Height)
        assert abs(got - wanted) / wanted < 0.15, (
            "the window is %dx%d (ratio %.2f) but the model asks for %dx%d (ratio %.2f)"
            % (size.Width, size.Height, got, dialog.DIALOG_WIDTH, dialog.DIALOG_HEIGHT,
               wanted))
        spots = {}
        for name, _service, _props in dialog._field_specs(window.values, window.masters):
            peer = window.control(name).getPosSize()
            assert peer.Width > 0 and peer.Height > 0, "%s has no size: %r" % (name, peer)
            assert peer.X >= 0 and peer.Y >= 0, "%s is off the window: %r" % (name, peer)
            assert peer.X + peer.Width <= size.Width + 4, \
                "%s sticks out on the right: %r in %r" % (name, peer, size)
            assert peer.Y + peer.Height <= size.Height + 4, \
                "%s sticks out at the bottom: %r in %r" % (name, peer, size)
            spots.setdefault((peer.X, peer.Y), []).append(name)
        shared = {spot: names for spot, names in spots.items() if len(names) > 1}
        assert not shared, "controls drawn on top of each other: %s" % shared
        # the labels really are next to their fields, not on top of them
        for name, _service, _props in dialog._field_specs(window.values, window.masters):
            if not name.startswith("label"):
                continue
            label = window.control(name).getPosSize()
            field = window.control(name[len("label"):]).getPosSize()
            assert label.X + label.Width <= field.X + 4, \
                "%s overlaps its field: %r vs %r" % (name, label, field)
    finally:
        window.dispose()


@test
def dialog_build_and_read_back():
    """Build the real control model, add a peer, and read the values back."""
    from plan_impress import dialog
    ctx = lo.connect()
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0x00FF00, "title": "Agenda", "master": "Master2"})
    window = dialog.SettingsDialog(ctx, settings, ["Master1", "Master2"])
    window.build()
    try:
        model = window.model
        for name in ("MutedColor", "TextColor", "Title", "Master", "ok", "cancel"):
            assert model.hasByName(name), name
        assert model.getByName("MutedColor").getPropertyValue("Text") == "00FF00"
        assert model.getByName("Title").getPropertyValue("Text") == "Agenda"
        assert tuple(model.getByName("Master").getPropertyValue("StringItemList")) == \
            ("Master1", "Master2")
        assert window.warnings == [], window.warnings
        # a native peer must attach without a visible window (Xvfb session)
        window._peer()
        assert list(window.control("Master").getSelectedItems()) == ["Master2"], \
            list(window.control("Master").getSelectedItems())
        result = window.result()
        assert result == {"muted_color": 0x00FF00, "text_color": 0x000000,
                          "title": "Agenda", "master": "Master2",
                          "recent_colors": [],
                          # the section box: nothing was set, so nothing is claimed -
                          # empty means "the deck's own", which is what a deck that
                          # has never been styled gets
                          "section_color": config.DEFAULT_SECTION_COLOR,
                          "section_font": "", "section_size": 0.0,
                          "section_x": None, "section_y": None,
                          "section_width": None}, result
        # typing an invalid colour must fall back to the stored one
        window.control("TextColor").setText("zzzzzz")
        assert window.result()["text_color"] == 0x000000
        window.control("TextColor").setText("123456")
        assert window.result()["text_color"] == 0x123456
    finally:
        window.dispose()


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #

def _paragraph_colors(shape):
    colors = []
    enum = shape.createEnumeration()
    while enum.hasMoreElements():
        colors.append(enum.nextElement().CharColor)
    return colors


@test
def insert_plan_layout():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        before = core.page_names(doc)
        settings = dict(config.DEFAULTS)
        settings.update({"muted_color": 0x112233, "text_color": 0xEE0000,
                         "title": "Plan"})
        report = core.insert_plan(doc, settings, ctx)

        names = core.page_names(doc)
        assert names[0] == core.OVERVIEW_NAME, names
        assert names[1] == "PlanImpress:Section=1", names
        assert names[2] == "welcome", names
        assert names.count(core.OVERVIEW_NAME) == 1
        for index in range(3):
            assert core.section_page_name(index) in names, names
        # one plan slide per section, at the top of it
        sections = core.get_sections(doc)
        assert len(sections) == 3, sections
        # the ranges as the document reports them: the plan slide first, then the
        # slides the section already had.  Asserting only the names above once let
        # three plan slides sit in the wrong sections and still pass.
        assert [section["indexes"] for section in sections] == \
            [[1, 2, 3], [4, 5, 6, 7], [8, 9, 10]], sections
        for index, section in enumerate(sections):
            assert section["slides"][0] == core.section_page_name(index), section
            assert section["start"] == names.index(section["slides"][0]), section
        # the overview is not part of any section
        assert core.OVERVIEW_NAME not in [
            name for section in sections for name in section["slides"]]
        assert len(names) == len(before) + 4, (names, before)
        assert report["inserted"] == 4, report

        # colours: the current section is highlighted, the rest are muted
        pages = doc.DrawPages
        by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                   for i in range(pages.Count)}
        for index in range(3):
            page = by_name[core.section_page_name(index)]
            body = core._body_shape(page)
            assert body is not None, "no body shape on section plan slide"
            colors = _paragraph_colors(body)
            assert len(colors) == 3, colors
            assert colors[index] == 0xEE0000, (index, colors)
            assert all(c == 0x112233 for i, c in enumerate(colors) if i != index), \
                (index, colors)
            title = core._title_shape(page)
            assert title.getString() == "Plan", title.getString()

        # the overview lists the sections too, nothing dimmed
        overview = by_name[core.OVERVIEW_NAME]
        colors = _paragraph_colors(core._body_shape(overview))
        assert colors == [0xEE0000] * 3, colors
    finally:
        lo.close(doc)


@test
def insert_plan_with_default_slide_names():
    """A deck the user built in Impress itself, not the renamed-pages fixture.

    ``DrawPages`` names such a deck ``page1``, ``page2``, … while the section
    lists its slides under the display names ``Slide 1``, ``Slide 2``, …; the
    fixture renames every page, so it never exercised that spelling and
    ``insert_plan`` answered "Section '…' refers to slides that no longer exist"
    for any deck a user had actually made.  The document is saved and reloaded to
    be sure the section list comes back through the importer that way.
    """
    import uno
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    path = os.path.join(ROOT, "out", "default-names.odp")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    try:
        pages = doc.DrawPages
        while pages.Count < 8:
            pages.insertNewByIndex(pages.Count)
        # slide 1 and 8 belong to no section; the ids are what other documents
        # refer to a section by, so the rewrite has to carry them along
        core.set_sections(doc, [
            {"name": "Intro", "id": "{11111111-1111-1111-1111-111111111111}",
             "slides": [1, 2]},
            {"name": "Body", "id": "{22222222-2222-2222-2222-222222222222}",
             "slides": [3, 4, 5]},
            {"name": "End", "id": "{33333333-3333-3333-3333-333333333333}",
             "slides": [6]}])
        listed = [section["slides"][0] for section in core.get_sections(doc)]
        assert listed == ["Slide 2", "Slide 4", "Slide 7"], listed
        doc.storeToURL(uno.systemPathToFileUrl(path),
                       (lo.pv("FilterName", "impress8"),))
        lo.close(doc)

        doc = lo.open_doc(desk, path, hidden=False)
        assert core.page_names(doc) == ["page%d" % i for i in range(1, 9)], \
            core.page_names(doc)
        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        after = report["sections_after"]
        # a plan slide in front of each section, and the deck's own slides kept;
        # the last section also swallows the trailing slide, because
        # SlideSections cannot end a section before the end of the deck
        # (dev/debug_sections.py)
        assert [section["indexes"] for section in after] == \
            [[2, 3, 4], [5, 6, 7, 8], [9, 10, 11]], after
        assert report["slides"][1] == core.OVERVIEW_NAME, report["slides"]
        assert core.OVERVIEW_NAME not in [
            name for section in after for name in section["slides"]], after
        assert [section["id"] for section in after] == [
            "{11111111-1111-1111-1111-111111111111}",
            "{22222222-2222-2222-2222-222222222222}",
            "{33333333-3333-3333-3333-333333333333}"], after

        assert core.remove_plan(doc) == 4, core.page_names(doc)
        assert core.page_names(doc) == ["page%d" % i for i in range(1, 9)], \
            core.page_names(doc)
        assert [section["id"] for section in core.get_sections(doc)] == [
            "{11111111-1111-1111-1111-111111111111}",
            "{22222222-2222-2222-2222-222222222222}",
            "{33333333-3333-3333-3333-333333333333}"], core.get_sections(doc)
    finally:
        try:
            lo.close(doc)
        except Exception:
            pass


@test
def plan_slide_typography():
    """Readable sizes, with nothing drawn off the slide.

    ``CharHeight`` is a point size while all the geometry properties are
    1/100 mm; mixing the two up once produced a 260 pt heading, and no colour
    or ordering assertion noticed.  The master's own placeholder rectangles are
    reused where they fit, so this also guards the fallback logic.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        pages = doc.DrawPages
        checked = 0
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            if not str(page.Name).startswith(core.PLAN_PREFIX):
                continue
            checked += 1
            title, body = core._title_shape(page), core._body_shape(page)
            assert title is not None and body is not None, page.Name
            assert 12.0 <= title.CharHeight <= 80.0, (page.Name, title.CharHeight)
            assert 10.0 <= body.CharHeight <= 60.0, (page.Name, body.CharHeight)
            assert title.CharHeight > body.CharHeight, page.Name
            assert body.Position.Y >= title.Position.Y, page.Name
            for shape in (title, body):
                where = (page.Name, shape.ShapeType, shape.Position, shape.Size)
                assert shape.Position.X >= 0 and shape.Position.Y >= 0, where
                assert shape.Size.Width > 0 and shape.Size.Height > 0, where
                assert (shape.Position.X + shape.Size.Width) <= page.Width * 1.02, where
                assert (shape.Position.Y + shape.Size.Height) <= page.Height * 1.02, where
        assert checked == 4, checked
    finally:
        lo.close(doc)


def _plan_pages(doc):
    """``(index, page)`` for every slide this extension generated."""
    pages = doc.DrawPages
    return [(i, pages.getByIndex(i)) for i in range(pages.Count)
            if str(pages.getByIndex(i).Name).startswith(core.PLAN_PREFIX)]


def _pdf_page_texts(doc, name):
    """The text of each page **as rendered**, via a PDF export.

    ``getString()`` is no guide for a footer: a field portion answers with the
    placeholder stored in the file (``<number>``, ``<footer>``) rather than the
    number or text that is drawn, so whether a footer really appears can only be
    read off the output.  ``pdftotext`` (poppler) is what ``dev/render_plan.py``
    uses for the same reason.
    """
    folder = os.path.join(ROOT, "out", "tests-pdf")
    os.makedirs(folder, exist_ok=True)
    pdf = os.path.join(folder, "%s.pdf" % name)
    if os.path.exists(pdf):
        os.remove(pdf)
    doc.storeToURL(uno.systemPathToFileUrl(pdf),
                   (lo.pv("FilterName", "impress_pdf_Export"),))
    texts = []
    for number in range(1, doc.DrawPages.Count + 1):
        result = subprocess.run(
            ["pdftotext", "-f", str(number), "-l", str(number), pdf, "-"],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise Skip("pdftotext failed: %s" % (result.stderr or "").strip()[:120])
        texts.append(result.stdout)
    return texts


def _footer_band(page):
    """``{kind: (x, y, width, height, char height)}`` for the bottom band.

    The rendered text is deliberately not part of this - see
    :func:`_pdf_page_texts` for why.  The height is kept separate from the
    position because Impress fits a text shape's height to its content, so a
    mirrored shape may differ there by a fraction of a millimetre.
    """
    out = {}
    for shape in core._footer_shapes(page):
        position, size = shape.Position, shape.Size
        out[core._footer_kind(shape)] = (position.X, position.Y, size.Width,
                                         size.Height, getattr(shape, "CharHeight", None))
    return out


def _install_footer_band(doc, page, master):
    """Give ``page`` the footer frames a deck written elsewhere carries per slide.

    The standalone version, with the measurements, is ``dev/debug_footer_saved.py``.
    Two things it depends on: a footer shape created by ``createInstance`` arrives
    *holding its own field*, so it has to be emptied before anything is put in it,
    and the content has to be a field rather than text for the date and the page
    number to stay live on every slide.
    """
    fields = {"FooterShape": "com.sun.star.presentation.TextField.Footer",
              "DateTimeShape": "com.sun.star.text.TextField.DateTime",
              "SlideNumberShape": "com.sun.star.text.TextField.PageNumber"}
    installed = []
    for shape in core._footer_shapes(master):
        kind = core._footer_kind(shape)
        if kind not in fields:
            continue
        try:
            fresh = doc.createInstance("com.sun.star.presentation.%s" % kind)
            page.add(fresh)
            fresh.Position = shape.Position
            fresh.Size = shape.Size
            fresh.CharHeight = shape.CharHeight
            text = fresh.getText()
            cursor = text.createTextCursor()
            cursor.gotoStart(False)
            cursor.gotoEnd(True)
            text.insertString(cursor, "", True)
            text.insertTextContent(text.createTextCursor(),
                                   doc.createInstance(fields[kind]), False)
        except Exception as error:
            raise AssertionError("could not install a %s: %s (%s)"
                                 % (kind, type(error).__name__, error))
        installed.append(kind)
    return installed


@test
def plan_slides_carry_the_decks_footer():
    """The generated slides show the same bottom band as the rest of the deck.

    Impress keeps the footer on the *slide* (``com.sun.star.presentation.DrawPage``:
    ``FooterText``, ``DateTimeText`` and the ``Is...Visible`` switches), so a page
    made by ``insertNewByIndex`` starts without one and the plan slides used to
    come out bare while every slide of the deck had a footer.  Checked twice: on
    the properties, and in the rendered PDF - a footer that is in the model but
    not on the page passes only the second check.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        donor = core._footer_state(doc.DrawPages.getByIndex(0))
        assert donor.get("FooterText") == FOOTER_TEXT, donor
        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        assert report["footer"] == "welcome", report

        plan = _plan_pages(doc)
        assert len(plan) == 4, [(index, page.Name) for index, page in plan]
        for _index, page in plan:
            state = core._footer_state(page)
            for name, value in donor.items():
                assert state.get(name) == value, (page.Name, name, state.get(name), value)

        texts = _pdf_page_texts(doc, "footer")
        reference = texts[core.page_names(doc).index("welcome")]
        dates = re.findall(r"\d+[/.]\d+[/.]\d+", reference)
        assert dates, ("the deck's own slide prints no date: %r" % reference)
        for index, page in plan:
            assert FOOTER_TEXT in texts[index], (page.Name, texts[index])
            assert dates[0] in texts[index], (page.Name, texts[index])
            # a real page-number field: it prints the plan slide's own number
            assert str(index + 1) in texts[index], (page.Name, texts[index])
    finally:
        lo.close(doc)


def _paragraphs(shape):
    out = []
    enum = shape.createEnumeration()
    while enum.hasMoreElements():
        out.append(enum.nextElement())
    return out


def _level(rules, index=0):
    """The properties of one list level of a ``NumberingRules`` object."""
    if rules is None:
        return {}
    return dict((entry.Name, entry.Value) for entry in rules.getByIndex(index))


@test
def plan_slides_use_the_template_placeholders():
    """Heading and list are the deck's own placeholders, and the list is numbered.

    Five separate things, none of which a plain text shape at a computed rectangle
    got right: the boxes and the characters come from the deck's *own slides* - the
    master page is the fallback under them, because a slide keeps the box and the
    font it was given and disagrees with its master all the time (the list used to
    hug the left edge in a font of its own) -, the page is on the title-plus-content
    layout - *set before* the shapes exist, or Impress keeps the boxes it already
    gave them -, the sections are the template's own first list level with only the
    label turned into a number, the list starts below the *text* of the heading and
    not below the middle of its box, and a dimmed row dims its number with it, which
    per-paragraph colours alone do not do because the label is painted with the
    level's ``BulletColor``.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        settings = dict(config.DEFAULTS)
        settings.update({"text_color": 0x102030, "muted_color": 0xCBCBCB})
        core.insert_plan(doc, settings, ctx)
        master = core._master_page(doc, "")
        # what the deck paints with, which is not necessarily the master page
        template_title, template_body = core._style_source(doc, master)
        assert template_body is not None, "the fixture has no content placeholder"
        assert template_title is not None, "the fixture has no title placeholder"
        template_body_paragraph = core._first_paragraph(template_body) or template_body
        pages = doc.DrawPages
        by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                   for i in range(pages.Count)}
        basis = None
        for name in [core.OVERVIEW_NAME] + [core.section_page_name(i)
                                            for i in range(3)]:
            page = by_name[name]
            assert page.Layout == core._LAYOUT_OUTLINE, (name, page.Layout)
            title, body = core._title_shape(page), core._body_shape(page)
            assert title is not None and body is not None, name
            assert core._is_content(body), (name, body.ShapeType)
            assert (body.Position.X, body.Size.Width) == \
                (template_body.Position.X, template_body.Size.Width), (
                    name, body.Position, body.Size,
                    template_body.Position, template_body.Size)
            wanted = core._rect(template_title, (page.Width * 0.08, page.Height * 0.05),
                                (page.Width * 0.84, page.Height * 0.16),
                                page.Width, page.Height)
            assert (title.Position.X, title.Size.Width) == (wanted[0], wanted[2]), (
                name, title.Position, title.Size, wanted)
            # the list has to clear the heading's *text*: this template anchors it
            # in the middle of a box twice as tall as the line, so the bottom of the
            # box is well below where the heading ends and the box's top is above it
            assert body.Position.Y >= core._heading_bottom(
                title.Position.Y, title.Size.Height, title.CharHeight,
                core._text_anchor(title)), (name, body.Position.Y, title.Position,
                                            title.Size.Height, title.CharHeight)

            # the list style is the template's own, with only the label replaced -
            # and the label itself is the template's too wherever it counts: the
            # bullet font, size, indentation and label colour are what makes the
            # number look like it belongs on the slide
            rules = dict((p.Name, p.Value)
                         for p in body.NumberingRules.getByIndex(0))
            master_level = _level(core._numbering_rules(template_body))
            wanted_type, wanted_extra, substituted = core._template_label(
                doc, master, template_body)
            assert rules["NumberingType"] == wanted_type, (
                name, rules["NumberingType"], master_level.get("NumberingType"))
            for attribute in ("Prefix", "Suffix", "BulletFont", "LeftMargin",
                              "StartWith", "Adjust"):
                if attribute in wanted_extra:
                    continue    # taken from the level whose numerals are used
                assert rules.get(attribute) == master_level.get(attribute), (
                    name, attribute, rules.get(attribute), master_level.get(attribute))
            # the two properties that are *not* inherited when a digit was invented
            # for a glyph: it sizes that glyph (45 % of the text height here) and
            # pulls it into the margin, which makes an unreadable digit glued to
            # the text - a number is text, so never smaller than it, and it gets
            # the block's own left edge as its column.  SymbolTextDistance cannot
            # be set on its own (writes are ignored) and follows FirstLineOffset.
            if substituted:
                assert rules.get("BulletRelSize") == max(
                    int(master_level.get("BulletRelSize") or 100), 100), (
                    name, rules.get("BulletRelSize"))
                assert rules.get("FirstLineOffset") == -rules.get("LeftMargin"), (
                    name, rules.get("FirstLineOffset"), rules.get("LeftMargin"))
            else:
                for attribute in ("BulletRelSize", "FirstLineOffset",
                                  "SymbolTextDistance"):
                    assert rules.get(attribute) == master_level.get(attribute), (
                        name, attribute)
            paragraphs = _paragraphs(body)
            assert [para.NumberingIsNumber for para in paragraphs] == [True] * 3, name
            assert [para.NumberingLevel for para in paragraphs] == [0] * 3, name
            for paragraph in paragraphs:
                # the number has a column of its own: the label hangs into the
                # margin by the level's own indent, asked for on the paragraph,
                # which is what keeps the digit off the text
                assert paragraph.ParaLeftMargin >= rules["LeftMargin"], (
                    name, paragraph.ParaLeftMargin)
                assert paragraph.ParaFirstLineIndent <= -rules["LeftMargin"], (
                    name, paragraph.ParaFirstLineIndent)
                # and the characters of the *paragraph* too: one of a new outline
                # placeholder otherwise takes them from the page style's outline
                # level, which is a bold of its own in the default template
                for attribute in core.PARAGRAPH_ATTRIBUTES:
                    assert getattr(paragraph, attribute) == \
                        getattr(template_body_paragraph, attribute), (
                        name, attribute, getattr(paragraph, attribute),
                        getattr(template_body_paragraph, attribute))
            # the label is drawn by the numbering, it is not in the text: copying a
            # section name out of the slide has to give back the plain name
            assert [para.getString() for para in paragraphs] == SECTION_NAMES, (
                name, [para.getString() for para in paragraphs])
            # the characters are the template's too - a shape built with
            # createInstance() would come in the page style's font instead.  The
            # point size is the one the template *paints* with, which is what
            # `_master_char_height` asks the first paragraph for.
            for attribute in ("CharFontName", "CharWeight"):
                assert getattr(body, attribute) == getattr(template_body, attribute), (
                    name, attribute, getattr(body, attribute),
                    getattr(template_body, attribute))
                assert getattr(title, attribute) == getattr(template_title, attribute), (
                    name, attribute, getattr(title, attribute),
                    getattr(template_title, attribute))
            assert body.CharHeight == core._master_char_height(template_body, 0.0), (
                name, body.CharHeight, template_body.CharHeight,
                getattr(core._first_paragraph(template_body), "CharHeight", None))
            assert title.CharHeight == core._master_char_height(template_title, 0.0), (
                name, title.CharHeight, template_title.CharHeight,
                getattr(core._first_paragraph(template_title), "CharHeight", None))

            # one size and one base colour for the overview and the plan slides;
            # only which paragraph is highlighted differs between them
            if basis is None:
                basis = (body.CharHeight, body.CharColor)
            assert (body.CharHeight, body.CharColor) == basis, (name, basis)
            assert body.CharColor == 0x102030, name
        # a dimmed section dims its number too.  The label is painted with the
        # level's BulletColor - which the template sets to its own accent colour -
        # so a dimmed paragraph carries its own copy of the rules with that one
        # property changed; the current one keeps the template's colour.  (That
        # the list still counts 1, 2, 3 across the three rule objects is what the
        # rendered slide in dev/debug_numbering.py has to show.)
        colors = _paragraph_colors(core._body_shape(by_name[core.section_page_name(1)]))
        assert colors == [0xCBCBCB, 0x102030, 0xCBCBCB], colors
        body = core._body_shape(by_name[core.section_page_name(1)])
        template_bullet = core._level_value(core._numbering_rules(template_body),
                                            "BulletColor")
        # a template that fixes no bullet colour (-1 = "follow the character
        # colour") gets the highlight colour on the current row instead
        current_bullet = template_bullet if isinstance(template_bullet, int) \
            and template_bullet >= 0 else 0x102030
        labels = [core._level_value(para.NumberingRules, "BulletColor")
                  for para in _paragraphs(body)]
        assert labels == [0xCBCBCB, current_bullet, 0xCBCBCB], (labels, template_bullet)
    finally:
        lo.close(doc)


@test
def plan_rows_are_numbered_the_way_the_template_numbers():
    """The rows count the way the deck's own list does - roman, letters, digits.

    The label used to be forced to ``NumberingType.ARABIC``, which put ``1. 2. 3.``
    on a deck whose outline counts ``I. II. III.``: the one thing on the slide the
    template already has a style for was the one thing that disagreed with it.  Here
    the deck's content placeholder is turned into a roman list and the plan rows have
    to follow it, ``Suffix`` included - and keep the ``BulletRelSize`` and
    ``FirstLineOffset`` the template gives its own label, wrong as those look for a
    bullet.  Only where the template draws no label at all do digits go in, and then
    the two properties that size and place *a glyph* are corrected: a digit is not a
    decorative character, so it is never smaller than the text and gets its column.

    The third case is the one a real deck actually has: its content level draws a
    glyph (so nothing there counts) while its **title** level counts - a template
    keeps its numbering format with the heading, not with the body - so the rows have
    to follow the title's numerals and its suffix.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    roman = core._numbering_constant("ROMAN_UPPER", 2)
    no_label = core._numbering_constant("NUMBER_NONE", 5)
    try:
        def relabel(numbering_type, suffix, wanted=None):
            """Make every placeholder of the deck (content, or ``wanted``) count so."""
            wanted = wanted or core._is_content
            changed = 0
            for container in (doc.MasterPages, doc.DrawPages):
                for i in range(container.Count):
                    for shape in core._text_shapes(container.getByIndex(i)):
                        if not wanted(shape):
                            continue
                        rules = core._copy_numbering(
                            doc, core._numbering_rules(shape))
                        # 80 % and an offset that is not -LeftMargin: a label tuned
                        # for the template's own glyph, which a *copied* label keeps
                        # and a *substituted* digit has to correct
                        core._patch_level(rules, {"NumberingType": numbering_type,
                                                  "Suffix": suffix,
                                                  "BulletRelSize": 80,
                                                  "LeftMargin": 1200,
                                                  "FirstLineOffset": -400})
                        shape.NumberingRules = rules
                        changed += 1
            assert changed, "the fixture has no placeholder to relabel"

        relabel(roman, ".")
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        pages = [page for _index, page in _plan_pages(doc)]
        assert pages, core.page_names(doc)
        # what the deck now says about its own list, from the placeholder the plan
        # slides copy their look from (the deck's slides, the master underneath)
        template_body = core._style_source(doc, core._master_page(doc, ""))[1]
        assert template_body is not None, "the fixture has no content placeholder"
        template_level = _level(core._numbering_rules(template_body))
        assert template_level["NumberingType"] == roman, template_level
        for page in pages:
            level = _level(core._numbering_rules(core._body_shape(page)))
            assert level["NumberingType"] == roman, (page.Name, level)
            assert level["Suffix"] == ".", (page.Name, level)
            # the label is the template's, so its size and its column are too
            for attribute in ("BulletRelSize", "FirstLineOffset", "LeftMargin"):
                assert level[attribute] == template_level[attribute], (
                    page.Name, attribute, level, template_level)

        # no label at all: only now is a number invented, and then it has to be a
        # readable one - full height, and a column of its own
        relabel(no_label, "")
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        for page in [page for _index, page in _plan_pages(doc)]:
            level = _level(core._numbering_rules(core._body_shape(page)))
            assert level["NumberingType"] == core._numbering_type_arabic(), (
                page.Name, level)
            assert level["BulletRelSize"] == 100, (page.Name, level)
            assert level["FirstLineOffset"] == -level["LeftMargin"], (page.Name, level)

        # ... unless the deck counts somewhere else, which is how decks are: this
        # one draws a glyph in the body and keeps its numerals in the heading
        relabel(roman, ")", wanted=core._is_title)
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        title_level = _level(core._numbering_rules(
            core._deck_placeholder(doc, core._master_page(doc, ""), core._is_title)))
        assert title_level["NumberingType"] == roman, title_level
        rows = [page for _index, page in _plan_pages(doc)]
        assert rows, core.page_names(doc)
        for page in rows:
            level = _level(core._numbering_rules(core._body_shape(page)))
            assert level["NumberingType"] == roman, (page.Name, level)
            # the literal text around the number belongs to the format as much as
            # the numerals do, so it comes from the same level
            assert level["Suffix"] == ")", (page.Name, level)
            # ... but the *placement* stays the body's own, and a counting label put
            # into a level that drew a glyph is corrected to be readable: full height
            # and a column of its own (the heading's 80 % / -400 belong to a heading)
            body_level = _level(core._numbering_rules(template_body))
            assert level["LeftMargin"] == body_level["LeftMargin"], (page.Name, level)
            assert level["BulletRelSize"] == max(
                int(body_level["BulletRelSize"] or 100), 100), (page.Name, level)
            assert level["FirstLineOffset"] == -level["LeftMargin"], (page.Name, level)
    finally:
        lo.close(doc)


@test
def plan_slides_copy_the_deck_own_slides():
    """The look comes from the deck's slides; the master page is only the fallback.

    A slide keeps the box and the characters it was given, so the two disagree on
    any deck somebody worked on: the deck this was measured on titles its slides in
    **31 pt at y = 1474** where its master placeholder says **32 pt at y = 1500**,
    and the generated heading came out a point larger than the deck's own and a few
    tenths of a millimetre off, next to it.  Here the fixture's master is left
    untouched and its content slides are moved instead: everything the plan slides
    show has to follow the slides, and nothing of it may come from the master.

    Two rules of that lookup are in this one test as well: the value the slides
    *agree on* wins, so the one slide that was edited apart from the rest ("the odd
    one out") does not move them; and the size is the one the template paints with,
    which is the first paragraph's - the outline level - and not the shape's.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        master = core._master_page(doc, "")
        master_title = core._title_shape(master)
        assert master_title is not None, "the fixture's master has no title"
        master_said = (master_title.Position.X, master_title.Position.Y,
                       master_title.Size.Width, master_title.CharHeight)
        moved = 0
        pages = doc.DrawPages
        for i in range(pages.Count):
            page = pages.getByIndex(i)
            if str(page.Name) == "welcome":         # the odd one out: outvoted
                continue
            title = core._title_shape(page)
            if title is None:
                continue
            title.Position = core._point(3000, 900)
            title.Size = core._size(20000, 1500)
            title.CharFontName = "Liberation Serif"
            title.CharHeight = 40.0                 # what the shape says ...
            for paragraph in core._paragraphs_of(title):
                paragraph.CharHeight = 27.5         # ... and what it paints with
            moved += 1
        assert moved >= 3, moved
        odd = [pages.getByIndex(i) for i in range(pages.Count)
               if str(pages.getByIndex(i).Name) == "questions"]
        assert len(odd) == 1, "the fixture lost its odd one out"
        core._title_shape(odd[0]).Position = core._point(9000, 7000)

        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        pages = doc.DrawPages
        by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                   for i in range(pages.Count)}
        for name in [core.OVERVIEW_NAME] + [core.section_page_name(i)
                                            for i in range(3)]:
            title = core._title_shape(by_name[name])
            assert title is not None, name
            assert title.Position.X == 3000, (name, title.Position)
            assert title.Size.Width == 20000, (name, title.Size)
            # Impress fits a text shape's height to its content and grows it around
            # the centre, so the box the template gives is a starting point here -
            # a couple of tenths of a millimetre, not a different position
            assert 700 < title.Position.Y < 1100, (name, title.Position)
            assert 1100 < title.Size.Height < 1900, (name, title.Size)
            assert title.CharHeight == 27.5, (name, title.CharHeight)
            assert title.CharFontName == "Liberation Serif", (
                name, title.CharFontName)
        # and none of that came from the master, which still says something else
        assert (master_title.Position.X, master_title.Position.Y,
                master_title.Size.Width, master_title.CharHeight) == master_said
        assert (3000, 900, 20000, 27.5) != master_said, master_said
    finally:
        lo.close(doc)


@test
def plan_slides_mirror_the_decks_footer_shapes():
    """A deck that carries its footer frames on every slide gets them copied too.

    That is how a deck written by something other than Impress stores the band
    (``presentation:class="footer"`` frames in ``content.xml``), and there the page
    properties are not enough: the master has nothing to draw from.  The shapes
    have to be recreated - same place, same size, same type size - with their
    *fields*, because a copied page-number field still prints the number of the
    slide it now sits on.

    The deck is saved and reopened before the plan slides are generated: the case
    the user has is a deck off the disk, and a field read from a file is not the
    object that was created (``dev/debug_footer_saved.py``).
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        master = doc.MasterPages.getByIndex(0)
        slide = doc.DrawPages.getByIndex(0)
        installed = _install_footer_band(doc, slide, master)
        assert installed == ["DateTimeShape", "FooterShape", "SlideNumberShape"], installed
        donor = _footer_band(slide)
        # every kind of band shape must have a field service to fall back on
        assert set(core.FOOTER_FIELD_SERVICES) >= set(core.FOOTER_SHAPE_KINDS), \
            core.FOOTER_FIELD_SERVICES
        saved = os.path.join(ROOT, "out", "deck-with-footers.odp")
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        doc.storeToURL(uno.systemPathToFileUrl(saved),
                       (lo.pv("FilterName", "impress8"),))
    finally:
        lo.close(doc)

    doc = lo.open_doc(desk, saved, hidden=False)
    try:
        band = _footer_band(doc.DrawPages.getByIndex(0))
        assert sorted(band) == sorted(donor), (sorted(band), sorted(donor))
        for kind, wanted in donor.items():
            assert band[kind][:3] == wanted[:3], (kind, band[kind], wanted)

        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        assert report["footer"] == "welcome", report
        plan = _plan_pages(doc)
        assert len(plan) == 4, plan
        for index, page in plan:
            got = _footer_band(page)
            assert sorted(got) == sorted(donor), (page.Name, sorted(got), sorted(donor))
            for kind, wanted in donor.items():
                got_x, got_y, got_w, got_h, got_pt = got[kind]
                x, y, width, height, char_height = wanted
                assert (got_x, got_y, got_w) == (x, y, width), \
                    (page.Name, kind, (got_x, got_y, got_w), (x, y, width))
                assert abs(got_h - height) < 60, (page.Name, kind, got_h, height)
                assert got_pt == char_height, (page.Name, kind, got_pt, char_height)

        texts = _pdf_page_texts(doc, "footer-shapes")
        # what one of the deck's own slides prints, the plan slides must print too
        reference = texts[core.page_names(doc).index("welcome")]
        dates = re.findall(r"\d+[/.]\d+[/.]\d+", reference)
        assert dates, ("no date on the deck's own slide: %r" % reference)
        for index, page in plan:
            assert FOOTER_TEXT in texts[index], (page.Name, texts[index])
            assert dates[0] in texts[index], (page.Name, texts[index])
            # a live page-number field: the plan slide's own number, not the donor's
            assert str(index + 1) in texts[index], (page.Name, texts[index])
    finally:
        lo.close(doc)


@test
def plan_slides_do_not_invent_a_footer():
    """A deck with nothing in the bottom band must not get a footer either.

    The obvious way to "fix" a missing footer - always copy the master's band, or
    always switch ``IsFooterVisible`` on - adds a date and a page number to decks
    that never asked for one.  ``sections_no_footer.odp`` is the case to catch
    that: the switches are on there (Impress leaves them on) but nothing prints.
    """
    if not os.path.exists(NO_FOOTER_FIXTURE):
        raise Skip("regenerate the fixtures: python3 tests/make_fixture.py")
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, NO_FOOTER_FIXTURE, hidden=False)
    try:
        assert core.footer_source(doc) is None, "this deck has nothing to print"
        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        assert report["footer"] is None, report
        for _index, page in _plan_pages(doc):
            assert core._footer_shapes(page) == [], page.Name
            state = core._footer_state(page)
            assert not str(state.get("FooterText") or "").strip(), (page.Name, state)
        texts = _pdf_page_texts(doc, "no-footer")
        # What a slide of this deck is allowed to print at all: the heading and the
        # numbered list, with nothing in the bottom band.  "no digits anywhere" was
        # the first version of this check, and the template's own list numbers broke
        # it - the 1, 2, 3 belong to the list, not to a page number - so the lines
        # are compared instead: a date, a footer text or a page number would add one.
        wanted = ["Plan"] + ["%d %s" % (number, name)
                             for number, name in enumerate(SECTION_NAMES, 1)]
        for index, page in _plan_pages(doc):
            lines = [line.strip() for line in texts[index].splitlines() if line.strip()]
            assert lines == wanted, (page.Name, lines, wanted)
    finally:
        lo.close(doc)


@test
def footer_source_is_the_slide_that_prints_something():
    """Which slide the band is copied from, without an office.

    ``IsFooterVisible`` being true is not a footer: the author can switch it on
    and type nothing, and then there is nothing to copy.  The trap this pins is
    treating a switch as content, which would hand every plan slide a footer the
    deck does not have.
    """
    class Shape(object):
        def __init__(self, kind):
            self.ShapeType = "com.sun.star.presentation." + kind

    class Page(object):
        def __init__(self, name, shapes=(), **properties):
            self.Name = name
            self.shapes = list(shapes)
            self.Count = len(self.shapes)
            for property_name, value in properties.items():
                setattr(self, property_name, value)

        def getByIndex(self, index):
            return self.shapes[index]

    class Document(object):
        def __init__(self, pages):
            self.DrawPages = type("Pages", (), {})()
            self.DrawPages.pages = list(pages)
            self.DrawPages.Count = len(pages)
            self.DrawPages.getByIndex = lambda index: pages[index]

    switched_on_but_empty = Page(
        "blank", IsFooterVisible=True, FooterText="   ", IsDateTimeVisible=True,
        IsDateTimeFixed=True, DateTimeText="", IsPageNumberVisible=False)
    assert core.footer_source(Document([switched_on_but_empty])) is None

    typed_footer = Page("typed", FooterText="Quarterly Review", IsFooterVisible=True)
    assert core.footer_source(Document([switched_on_but_empty, typed_footer])) \
        is typed_footer
    # a page number alone is content, and so is a date that is a field
    numbered = Page("numbered", IsPageNumberVisible=True)
    assert core.footer_source(Document([numbered])) is numbered
    dated = Page("dated", IsDateTimeVisible=True, IsDateTimeFixed=False)
    assert core.footer_source(Document([dated])) is dated
    # frames on the slide count even when the properties say nothing
    framed = Page("framed", shapes=[Shape("FooterShape")])
    assert core.footer_source(Document([framed])) is framed
    # a generated slide is never the source: it is what we are writing
    generated = Page(core.PLAN_PREFIX + "Overview", FooterText="copy of a copy")
    assert core.footer_source(Document([generated])) is None
    assert core.footer_source(Document([generated, typed_footer])) is typed_footer


@test
def insert_plan_is_idempotent():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        settings = dict(config.DEFAULTS)
        first = core.insert_plan(doc, settings, ctx)["slides"]
        second = core.insert_plan(doc, settings, ctx)["slides"]
        assert first == second, (first, second)
        assert core.remove_plan(doc) == 4
        assert core.page_names(doc) == [
            "welcome", "agenda-notes", "overview-diagram", "data-model", "apis",
            "live-demo", "questions"], core.page_names(doc)
        # the sections themselves have to come back too, at their old positions
        assert [section["indexes"] for section in core.get_sections(doc)] == \
            [[0, 1], [2, 3, 4], [5, 6]], core.get_sections(doc)
        # removing twice is harmless
        assert core.remove_plan(doc) == 0
    finally:
        lo.close(doc)


@test
def plan_slides_leave_a_title_slide_without_section_alone():
    """A title slide that belongs to no section stays first; the overview follows it.

    The overview goes in front of the *first section*, not in front of the deck,
    so a leading slide outside every section keeps its place and stays out of the
    section list.  Measured (`dev/debug_ungrouped.py`): only slides before the
    first section can be ungrouped - LibreOffice attaches any later ungrouped
    slide to the section in front of it as soon as the section list is written.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    try:
        # a new Impress document already has one slide: that one is the title slide
        doc.DrawPages.getByIndex(0).Name = "title"
        for name in ("welcome", "agenda-notes", "diagram", "questions"):
            doc.DrawPages.insertNewByIndex(doc.DrawPages.Count).Name = name
        core.set_sections(doc, [("Introduction", ["welcome", "agenda-notes"]),
                                ("Demo", ["diagram", "questions"])])
        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)

        names = core.page_names(doc)
        assert names[0] == "title", names
        assert names[1] == core.OVERVIEW_NAME, names
        assert names[2] == "PlanImpress:Section=1", names
        assert names[3] == "welcome", names
        assert names[-1] == "questions", names
        assert report["inserted"] == 3, report          # 2 sections + the overview
        # the title slide was not pulled into a section, the overview stays out too
        listed = [name for section in core.get_sections(doc) for name in section["slides"]]
        assert "title" not in listed, listed
        assert core.OVERVIEW_NAME not in listed, listed
        # removing the plan slides brings the deck back to exactly what it was
        assert core.remove_plan(doc) == 3
        assert core.page_names(doc) == [
            "title", "welcome", "agenda-notes", "diagram", "questions"], core.page_names(doc)
    finally:
        lo.close(doc)


# --------------------------------------------------------------------------- #
# the section-name box (*Section Titles*)
# --------------------------------------------------------------------------- #


def _section_boxes(doc):
    """``[(page index, page name, [box, ...]), ...]`` for every slide of the deck."""
    pages = doc.DrawPages
    return [(index, str(pages.getByIndex(index).Name),
             core.section_text_shapes(pages.getByIndex(index)))
            for index in range(pages.Count)]


def _style_is_none(value):
    """Whether a ``FillStyle``/``LineStyle`` is ``NONE``.

    pyuno hands an enum back as an object whose ``value`` is the *name* - ``NONE``,
    not 0 - while a plain int is what an older office answers with, so both are
    accepted here rather than the test guessing which one it got.
    """
    name = str(getattr(value, "value", value)).upper()
    return name in ("NONE", "0")


def _only_box(page):
    """The one box a slide is supposed to carry; fails the test if there are others."""
    boxes = core.section_text_shapes(page)
    assert len(boxes) == 1, "expected one section box, found %d" % len(boxes)
    return boxes[0]


def _character_of(value):
    """One character property as something comparable.

    pyuno answers some of them as an ``Enum`` instance whose ``value`` is the **name** -
    ``CharPosture`` written as ``2`` reads back as ``ITALIC`` (fact 92) - so a written
    int compared with a read object is never equal.  Both sides of every comparison
    below go through here.
    """
    return str(getattr(value, "value", value))


def _box_look(box):
    """Everything the copy rule takes from a box: its characters and its anchoring.

    Read as two calls because the two live on different levels of the text object - the
    characters on the portion (fact 95), ``TextVerticalAdjust`` on the shape
    (``SECTION_ANCHOR_ATTRIBUTES``) - but compared as one thing, which is how a user
    judges the result: same font, same size, same place in the box.
    """
    look = core._read_look(box)
    look.update(core._read_anchor(box))
    return look


def _style_box_like_the_editor(box, **attributes):
    """Change a box's characters the way Impress does: on the text **portion**.

    ``box.CharHeight = 28`` is what a macro does, and it only reaches the default
    underneath everything: what the sidebar, the toolbar and ``Ctrl+`` change is the
    portion of the paragraph, and the portion is what the office paints (fact 52's
    ladder, bottom rung).  A copy rule that reads the *shape* therefore passes a test
    that styles the shape and still loses the user's font, size and colour on the
    screen - which is exactly the report this is here for.
    """
    paragraphs = core._paragraphs_of(box)
    assert paragraphs, "the box has no paragraph to style"
    portions = core._portions_of(paragraphs[0])
    assert portions, "the box has no text portion to style"
    for name, value in attributes.items():
        setattr(portions[0], name, value)
    return portions[0]


def _duplicate_page(doc, ctx, index):
    """Duplicate slide ``index`` the way the menu does; returns the copy's index.

    ``.uno:DuplicatePage`` is a dispatch and therefore asynchronous like the move
    commands (fact 14), and it acts on the slide the *view* has selected, so the
    controller is pointed at the source first and the page count is polled.  The
    copy lands directly behind its source.
    """
    pages = doc.DrawPages
    before = pages.Count
    doc.CurrentController.setCurrentPage(pages.getByIndex(index))
    core._dispatch(doc, ".uno:DuplicatePage", ctx)
    if not lo.wait_until(lambda: pages.Count > before, timeout=10.0):
        raise AssertionError("duplicating slide %d added nothing" % index)
    return index + 1


@test
def section_titles_name_every_section_slide():
    """Every slide of a section carries its section's name in a box of its own.

    The command the request asks for: "add the name of the section to each slide".
    The box has to be a plain text box rather than a placeholder, because a
    placeholder is re-dealt and snapped back to the master by the layout (facts 21
    and 53) and this box belongs where the settings put it.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        sections = core.get_sections(doc)
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["created"] == doc.DrawPages.Count, report
        assert report["written"] == doc.DrawPages.Count, report
        assert report["cleared"] == 0, report
        assert [name for name in report["sections"]] == SECTION_NAMES, report

        for index, _name, boxes in _section_boxes(doc):
            assert len(boxes) == 1, "slide %d has %d boxes" % (index, len(boxes))
            box = boxes[0]
            page = doc.DrawPages.getByIndex(index)
            assert str(box.getString()) == str(core.section_of(sections, index)), \
                "slide %d says %r" % (index, box.getString())
            assert str(box.Name).startswith(core.SECTION_TEXT_PREFIX), box.Name
            assert str(box.Name) == core.section_text_name(index), box.Name
            # the tail is the position, not a constant: two slides have to answer with
            # two names, or a macro could not point at one box
            assert str(box.Name).split(":")[-1] == str(index + 1), box.Name
            assert box.supportsService("com.sun.star.drawing.TextShape"), box.ShapeType
            # ... and it is a *plain* box: a presentation placeholder is snapped to the
            # master and re-dealt by the layout (facts 21 and 53), which would move and
            # restyle this box behind the command's back
            assert str(box.ShapeType).endswith(".TextShape"), box.ShapeType
            for service in tuple(core.CONTENT_SERVICES) + (
                    "com.sun.star.presentation.TitleTextShape",):
                assert not box.supportsService(service), \
                    "the box is a %s placeholder: the layout will re-deal it" % service
            # nothing of the slide's own look is inherited into a frame or a fill:
            # the label is drawn over the slide, not on a plate
            assert _style_is_none(box.getPropertyValue("FillStyle")), "the box is filled"
            assert _style_is_none(box.getPropertyValue("LineStyle")), "the box is framed"
            rect = core._box_rect_of(box)
            assert rect[2] > 0 and rect[3] > 0, rect
            # a shape from ``createInstance`` sits at 0,0 until it is told otherwise, so a
            # box that begins there is one whose position was never written
            assert rect[1] > 0, "the box was never moved to where it belongs: %r" % (
                rect,)
            slide_width = int(page.Width)
            assert rect[0] >= 0 and rect[1] >= 0, rect
            assert rect[0] + rect[2] <= slide_width + 100, \
                "the box is wider than the slide: %r in %d" % (rect, slide_width)
            # where it stands is the deck's own margin, not a number made up here
            deck_body = [one for one in core._text_shapes(page)
                         if core._is_content(one)]
            if deck_body:
                assert rect[0] == int(deck_body[0].Position.X), \
                    "slide %d: the box is at x=%d, the deck's content box at %d" % (
                        index, rect[0], deck_body[0].Position.X)
            # the characters are on the paragraph too, or the page style wins
            # (fact 52) and the box is drawn in the deck's body font at its size.
            # Both asked by attribute, the way `core._master_char_height` asks: on a
            # paragraph proxy `getPropertyValue` is the one spelling that answers
            # ``AttributeError`` when the office is under load (fact 60)
            paragraph = core._first_paragraph(box)
            assert paragraph is not None, "the box has no paragraph to paint with"
            shape_size = getattr(box, "CharHeight", None)
            paragraph_size = getattr(paragraph, "CharHeight", None)
            assert shape_size, "the box says nothing about its size: %r" % (shape_size,)
            assert paragraph_size is not None, \
                "the box's paragraph says nothing about its size: the label is drawn " \
                "with the page style's characters, not the ones the command wrote"
            assert paragraph_size == shape_size, \
                "the shape says %s pt and its paragraph %s pt" % (
                    shape_size, paragraph_size)
    finally:
        lo.close(doc)


def _pdf_word_boxes(doc, name, number):
    """``[(word, yMin, yMax)]`` of page ``number`` **as rendered**.

    The same reason :func:`_pdf_page_texts` exists - only the output says what is
    drawn - plus the coordinates: where two text shapes' *bands* overlap, one of
    them is printed through the other, and no property on a shape can show that
    because a presentation placeholder paints its text in the middle of a box that
    is far taller than the line (fact 56).
    """
    folder = os.path.join(ROOT, "out", "tests-pdf")
    os.makedirs(folder, exist_ok=True)
    pdf = os.path.join(folder, "%s.pdf" % name)
    if os.path.exists(pdf):
        os.remove(pdf)
    doc.storeToURL(uno.systemPathToFileUrl(pdf),
                   (lo.pv("FilterName", "impress_pdf_Export"),))
    result = subprocess.run(["pdftotext", "-bbox", "-f", str(number), "-l",
                             str(number), pdf, "-"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise Skip("pdftotext failed: %s" % (result.stderr or "").strip()[:120])
    page = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', result.stdout)
    if page is None:
        raise Skip("pdftotext -bbox printed no page for %s" % pdf)
    return ([(match.group(5), float(match.group(2)), float(match.group(4)))
             for match in re.finditer(
                 r'<word xMin="([\d.]+)" yMin="([\d.]+)" '
                 r'xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', result.stdout)],
            [float(page.group(1)), float(page.group(2))])


@test
def section_titles_are_painted_without_a_plate():
    """No fill, no frame - and a plate that appeared is gone after the next run.

    The office's own default is the reason the code says it: a ``TextShape`` from
    ``createInstance`` answers ``FillStyle = SOLID`` and ``LineStyle = SOLID`` on a
    document that has just been loaded, so a label that was not explicitly flattened is
    drawn on a grey rectangle with a line round it (fact 88).  Impress is known to hand
    a new shape the attributes of the last one created, but that cannot be *set* from
    UNO reliably - both orders of writing a solid shape and then creating another answer
    whatever the office feels like - so the promise is not left to the default: the two
    writes are re-asserted on every run, and this is where that is checked.  The
    re-run half is the deterministic one; the flatness of a freshly created box is the
    same assertion at the moment of creation, where it is a bar and not a witness.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        for index, _name, boxes in _section_boxes(doc):
            box = boxes[0]
            assert _style_is_none(box.getPropertyValue("FillStyle")), \
                "slide %d: the label is drawn on a fill" % index
            assert _style_is_none(box.getPropertyValue("LineStyle")), \
                "slide %d: the label is drawn inside a frame" % index

        # a box that has picked a plate up - a duplicated slide, a template, somebody's
        # edit, the office's own default - has to be flat again after the next run
        dirty = _section_boxes(doc)[0][2][0]
        dirty.setPropertyValue("FillStyle", 1)               # SOLID
        dirty.setPropertyValue("LineStyle", 1)
        assert not _style_is_none(dirty.getPropertyValue("FillStyle")), \
            "a box cannot be given a fill here, so the re-run half proves nothing"
        before = core._box_rect_of(dirty)

        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        again = _section_boxes(doc)[0][2][0]
        assert _style_is_none(again.getPropertyValue("FillStyle")), \
            "the second run left the plate under the label"
        assert _style_is_none(again.getPropertyValue("LineStyle")), \
            "the second run left a frame round the label"
        assert core._box_rect_of(again) == before, \
            "flattening the box moved it: %r -> %r" % (before, core._box_rect_of(again))
    finally:
        lo.close(doc)


@test
def section_titles_do_not_print_through_the_heading():
    """The label paints clear of the slide's own heading, and on the slide.

    The box is a running head, so it has to sit *above* the letters the deck's title
    placeholder paints - not above the top of its box.  Measured with
    ``pdftotext -bbox`` on the fixture (`dev/render_section_titles.py` prints the
    same numbers): the heading paints from 64.7 to 113.8 pt of the page and the
    label from 11.5 to 47.2.  A box placed at the top of the title's *box*, or
    between the heading and the content, lands its band across the heading's and
    the two print on top of each other - which is exactly what the first version
    of ``_section_box_rect`` did.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        # the sections are renamed first because the label is matched in the
        # rendered text by its words: a deck whose heading *is* its section name
        # ("Live Demo" under a section called "Demo") would otherwise have the
        # heading's own word counted as the label
        entries = core.get_sections(doc)
        core.set_sections(doc, [("Section%d" % (number + 1), entry["indexes"])
                                for number, entry in enumerate(entries)])
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        pages = doc.DrawPages
        checked = 0
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            boxes = core.section_text_shapes(page)
            if not boxes:
                continue
            label = str(boxes[0].getString())
            title = core._title_shape(page)
            heading = str(title.getString()).strip() if title is not None else ""
            if not heading or heading == label:
                continue          # nothing to collide with on this slide
            words, size = _pdf_word_boxes(doc, "section-titles", index + 1)
            painted = set(word for word, _top, _bottom in words)
            assert label in painted, "slide %d: %r is not drawn at all" % (index, label)
            assert heading.split()[0] in painted, \
                "slide %d: the heading %r is not drawn" % (index, heading)
            label_band = [(top, bottom) for word, top, bottom in words
                          if word == label]
            heading_band = [(top, bottom) for word, top, bottom in words
                            if word == heading.split()[0]]
            for top, bottom in label_band:
                for head_top, head_bottom in heading_band:
                    overlap = min(bottom, head_bottom) - max(top, head_top)
                    assert overlap <= 1.0, \
                        "slide %d: %r paints %s..%s through its own heading %r " \
                        "%s..%s (by %.1f pt)" % (
                            index, label, top, bottom, heading,
                            head_top, head_bottom, overlap)
                assert top >= 0 and bottom <= size[1] + 1.0, \
                    "slide %d: the label paints off the slide at %s..%s" % (
                        index, top, bottom)
            checked += 1
        assert checked >= 3, "only %d slides could be checked" % checked
    finally:
        lo.close(doc)


@test
def re_running_section_titles_updates_the_boxes_and_adds_none():
    """A second run writes into the boxes it made; it never paints another one.

    "similarly to the plan slides, re-trigger updates the content and do not create
    new textboxes".  Recognition is by the name's prefix, which is why the prefix -
    and not the whole name, whose tail is a page position that moves - is what
    :func:`core._is_section_box` compares.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        before = [(index, [str(b.Name) for b in boxes])
                  for index, _name, boxes in _section_boxes(doc)]
        shapes = [doc.DrawPages.getByIndex(i).Count for i in range(doc.DrawPages.Count)]

        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["created"] == 0, report
        assert report["updated"] == doc.DrawPages.Count, report
        after = [(index, [str(b.Name) for b in boxes])
                 for index, _name, boxes in _section_boxes(doc)]
        assert after == before, "a re-run changed the boxes: %r -> %r" % (before, after)
        # the same *shapes*, not just the same names: a box that was removed and
        # created again would look identical in the list above
        assert [doc.DrawPages.getByIndex(i).Count for i in
                range(doc.DrawPages.Count)] == shapes

        # and a re-run moves the boxes it made.  What moves them is the *first* box:
        # the command copies where that one sits, so moving it by hand and running
        # again moves the deck (the position fields of the option screen are what a
        # deck with no box to copy is drawn with - asserted in
        # section_titles_copy_the_first_box_the_command_sees)
        first = _only_box(doc.DrawPages.getByIndex(0))
        first.Position = core._point(4000, 900)
        first.Size = core._size(18000, 700)
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        for index, _name, boxes in _section_boxes(doc):
            if not boxes:
                continue
            rect = core._box_rect_of(boxes[0])
            assert rect[0] == 4000, \
                "slide %d is still at %r, the first box is at x=4000" % (index, rect)
            assert rect[1] == 900, "slide %d: y is %d, the first box says 900" % (
                index, rect[1])
            assert rect[2] == 18000, "slide %d: the width is %d, not 18000" % (
                index, rect[2])

        # and it follows the sections it was given: rename one, run again
        core.set_sections(doc, [(str(entry["name"]).upper(), entry["indexes"])
                                for entry in core.get_sections(doc)])
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        sections = core.get_sections(doc)
        for index, _name, boxes in _section_boxes(doc):
            assert str(boxes[0].getString()) == str(core.section_of(sections, index)), \
                "slide %d still says %r" % (index, boxes[0].getString())
    finally:
        lo.close(doc)


@test
def section_titles_survive_a_duplicated_slide():
    """A duplicated slide's box is found and rewritten, not left beside a new one.

    The case the request names: "ensure that the name of the section header is still
    detected as such when a slide is duplicated".  A duplicated slide brings a copy
    of every shape it had, **name included** - LibreOffice only appends a counter, so
    ``PlanImpress:SectionText:Slide:1`` comes back as ``PlanImpress:SectionText:
    Slide: 1`` - and a command that recognised its boxes by their exact name would
    not see the copy and would paint a second box over it.  Recognising the prefix
    instead is what makes the copy say the section it now belongs to.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        source = 1                       # "agenda-notes", in Introduction
        copied = _duplicate_page(doc, ctx, source)

        # the copy arrived wearing its source's box, name and all
        boxes = core.section_text_shapes(doc.DrawPages.getByIndex(copied))
        assert len(boxes) == 1, "the copy has %d boxes before the re-run" % len(boxes)
        assert str(boxes[0].Name).startswith(core.SECTION_TEXT_PREFIX), boxes[0].Name
        assert str(boxes[0].getString()) == SECTION_NAMES[0], \
            "the copy still says what its source said: %r" % boxes[0].getString()

        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["created"] == 0, \
            "the copy's box was not recognised, so a second one was made: %r" % report
        page = doc.DrawPages.getByIndex(copied)
        assert len(core.section_text_shapes(page)) == 1, \
            "the copy carries two boxes after the re-run"
        sections = core.get_sections(doc)
        wanted = str(core.section_of(sections, copied))
        assert wanted, "the copy belongs to no section, so the test proves nothing"
        assert str(_only_box(page).getString()) == wanted, \
            "the copy says %r but belongs to %r" % (
                _only_box(page).getString(), wanted)
        assert str(_only_box(page).Name) == core.section_text_name(copied), \
            "the copy's box is still named for its source"
        # and every other slide is still right
        for index, _name, boxes in _section_boxes(doc):
            assert len(boxes) == 1, "slide %d carries %d boxes" % (index, len(boxes))
            assert str(boxes[0].getString()) == str(core.section_of(sections, index)), \
                "slide %d says %r" % (index, boxes[0].getString())
    finally:
        lo.close(doc)


@test
def section_titles_leave_a_slide_without_a_section_alone():
    """No box before the first section - and none left behind when a slide leaves one.

    "each slide except the firsts (without section)": a title slide that leads the
    deck belongs to no section and gets nothing.  The other half matters as much:
    a slide that *used* to be in a section keeps its box through a re-sectioning
    unless the run takes it away, and a deck with a stale label on the cover is
    worse than one with none.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    try:
        doc.DrawPages.getByIndex(0).Name = "title"
        for name in ("welcome", "agenda-notes", "diagram", "questions"):
            doc.DrawPages.insertNewByIndex(doc.DrawPages.Count).Name = name
        core.set_sections(doc, [("Introduction", ["welcome", "agenda-notes"]),
                                ("Demo", ["diagram", "questions"])])
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["skipped_outside"] == 1, report
        assert report["written"] == 4, report
        assert core.section_text_shapes(doc.DrawPages.getByIndex(0)) == [], \
            "the cover slide got a section box"
        for index in range(1, 5):
            assert len(core.section_text_shapes(doc.DrawPages.getByIndex(index))) == 1, \
                "slide %d has no box" % index

        # the cover moves into the first section: it is now a section slide
        core.set_sections(doc, [("Introduction", [0, 1, 2]), ("Demo", [3, 4])])
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["created"] == 1, report
        assert str(_only_box(doc.DrawPages.getByIndex(0)).getString()) == "Introduction"

        # ... and back out again: the box it no longer needs goes with the section
        core.set_sections(doc, [("Introduction", [1, 2]), ("Demo", [3, 4])])
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["cleared"] == 1, report
        assert core.section_text_shapes(doc.DrawPages.getByIndex(0)) == [], \
            "a stale box is left on the slide that left its section"
        assert doc.DrawPages.Count == 5, "the deck lost a slide"
    finally:
        lo.close(doc)


@test
def section_titles_are_not_drawn_on_the_plan_slides():
    """A plan slide names its section in its heading, so it gets no box as well."""
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["skipped_plan"] > 0, report
        assert report["written"] == doc.DrawPages.Count - report["skipped_plan"], report
        pages = doc.DrawPages
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            if core._is_plan_page(page):
                assert core.section_text_shapes(page) == [], \
                    "a plan slide carries a section box"
        # a box that somehow ended up on a plan slide is taken away by the next run
        plan = [pages.getByIndex(i) for i in range(pages.Count)
                if core._is_plan_page(pages.getByIndex(i))][0]
        stray = core._new_section_box(doc, plan, core.section_text_name(0))
        assert stray is not None, "no box could be made to plant"
        assert len(core.section_text_shapes(plan)) == 1
        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["cleared"] >= 1, report
        assert core.section_text_shapes(plan) == [], "the stray box survived"
    finally:
        lo.close(doc)


@test
def remove_section_titles_loses_nothing_of_the_deck():
    """*Remove Section Titles* takes the boxes and nothing else.

    The command has to be safe to run on a deck the user made: the slides they drew
    keep every shape they had, and a deck with no boxes at all is left alone rather
    than rewritten.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        def inventory():
            pages = doc.DrawPages
            return [(str(pages.getByIndex(i).Name),
                     [str(pages.getByIndex(i).getByIndex(j).Name)
                      for j in range(pages.getByIndex(i).Count)])
                    for i in range(pages.Count)]

        before = inventory()
        assert core.remove_section_titles(doc) == 0, "there was nothing to remove"
        assert inventory() == before, "removing nothing changed the deck"

        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert sum(len(boxes) for _i, _n, boxes in _section_boxes(doc)) > 0
        removed = core.remove_section_titles(doc)
        assert removed == doc.DrawPages.Count, removed
        assert sum(len(boxes) for _i, _n, boxes in _section_boxes(doc)) == 0
        assert inventory() == before, "the deck is not what it was: %r" % inventory()
    finally:
        lo.close(doc)


@test
def section_titles_copy_the_first_box_the_command_sees():
    """One box styles them all: the first the command can see is the template.

    "copy the position and formatting of the first section title textbox you see when
    inserting / updating section title".  The rule has no switch: restyle the label on
    one section slide in the editor, run the command, and every other slide is redrawn
    to match it - font, size, weight, colour, the rectangle **and** where the text sits
    in that rectangle.  The four *Default …* settings are therefore inert while such a
    box exists, which is asserted here too, and they come back into play when there is
    nothing to copy - a deck whose boxes have just been removed, which is also the only
    case in which the label is pinned to the top of its box (fact 22).
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    defaults = dict(config.DEFAULTS, section_size=14, section_color=0x00FF00,
                    section_font="Liberation Mono")
    try:
        # nothing to copy yet: the defaults say, and the slides agree with each other
        report = core.apply_section_titles(doc, defaults, ctx)
        assert report["look"] == "the default settings", report
        boxes = _section_boxes(doc)
        assert boxes, "the command wrote no box at all"
        painted = core._box_rect_of(boxes[0][2][0])
        for index, _name, page_boxes in boxes:
            assert core._box_rect_of(page_boxes[0]) == painted, \
                "slide %d sits at %r, slide 0 at %r" % (
                    index, core._box_rect_of(page_boxes[0]), painted)
            look = _box_look(page_boxes[0])
            assert abs(float(look["CharHeight"]) - 14.0) < 0.6, (index, look)
            assert int(look["CharColor"]) & 0xFFFFFF == 0x00FF00, (index, look)
            assert str(look["CharFontName"]) == "Liberation Mono", (index, look)
            # with nobody having aligned anything, the label is drawn at the top of its
            # box (fact 22) - the default the copy rule must not lose, but also must not
            # force over what a user did set
            assert _character_of(
                getattr(page_boxes[0], "TextVerticalAdjust")) == "TOP", (index, look)

        # what the user does in the editor - and the editor writes the characters on
        # the text portion, not on the shape, so this is the case a copy rule that only
        # reads the shape loses (see _style_box_like_the_editor).  The box is made tall
        # and its text aligned to the middle of it: *Format > Align Text*, which is the
        # third thing a hand sets on a label and the one the first version of the copy
        # rule still pulled back to the top
        first = _only_box(doc.DrawPages.getByIndex(0))
        portion = _style_box_like_the_editor(
            first, CharHeight=28, CharColor=0xFF0000, CharFontName="Liberation Serif",
            CharWeight=150, CharPosture=2)
        first.Position = core._point(900, 1200)
        first.Size = core._size(25199, 4000)
        first.TextVerticalAdjust = 1                  # drawing CENTER
        # one slide that was styled *differently*: its own portion says something else,
        # and the run has to overwrite that, not merely the shape above it - the case a
        # duplicated or once-hand-styled slide is
        with_boxes = [page_boxes for _i, _n, page_boxes in _section_boxes(doc)
                      if page_boxes]
        _style_box_like_the_editor(with_boxes[-1][0], CharHeight=9, CharColor=0x00FF00,
                                   CharFontName="DejaVu Sans Mono", CharWeight=100,
                                   CharPosture=0)
        wanted = core._box_rect_of(first)
        look = _box_look(first)
        # the witness that this really is the hard case: what was written is on the
        # portion, and reading the shape or the paragraph would answer something else
        for attribute in ("CharHeight", "CharColor", "CharFontName", "CharWeight",
                          "CharPosture"):
            assert _character_of(look.get(attribute)) == _character_of(
                getattr(portion, attribute)), \
                "reading the styled box answers %s=%r, its own portion says %r" % (
                    attribute, look.get(attribute), getattr(portion, attribute))
        assert _character_of(look.get("TextVerticalAdjust")) == "CENTER", look

        report = core.apply_section_titles(doc, defaults, ctx)
        assert report["look"] == "the first section slide's own box", report
        for index, _name, page_boxes in _section_boxes(doc):
            if not page_boxes:
                continue
            box = page_boxes[0]
            assert core._box_rect_of(box) == wanted, \
                "slide %d sits at %r, not at the first box's %r" % (
                    index, core._box_rect_of(box), wanted)
            other = _box_look(box)
            for attribute in ("CharHeight", "CharColor", "CharFontName", "CharWeight",
                              "CharPosture", "TextVerticalAdjust"):
                assert _character_of(other.get(attribute)) == _character_of(
                    look.get(attribute)), \
                    "slide %d: %s is %r, the first box says %r" % (
                        index, attribute, other.get(attribute), look.get(attribute))
            # and on the level that actually paints: a copy that stopped at the
            # shape would leave this slide's own portion saying what it used to
            target = core._portions_of(core._paragraphs_of(box)[0])[0]
            for attribute in core.SECTION_BOX_ATTRIBUTES:
                if not hasattr(target, attribute):
                    continue        # a portion has no CharStyleName; the value in the
                                    # look came from a higher rung (fact 52)
                assert _character_of(getattr(target, attribute)) == _character_of(
                    look.get(attribute)), \
                    "slide %d paints %s=%r, the first box paints %r" % (
                        index, attribute, getattr(target, attribute),
                        look.get(attribute))

        # and a value typed into the option screen does *not* overrule the box that is
        # there: 14 pt, green and 40 mm across all say so and none of them is obeyed
        report = core.apply_section_titles(
            doc, dict(defaults, section_x=4000, section_y=900), ctx)
        assert report["look"] == "the first section slide's own box", report
        for index, _name, page_boxes in _section_boxes(doc):
            assert core._box_rect_of(page_boxes[0]) == wanted, \
                "slide %d: the settings moved a box the command should have copied" % index
            assert abs(float(core._read_look(page_boxes[0])["CharHeight"]) - 28.0) < 0.6

        # take the boxes away and there is nothing to copy: the defaults speak again
        assert core.remove_section_titles(doc) > 0
        report = core.apply_section_titles(doc, defaults, ctx)
        assert report["look"] == "the default settings", report
        for index, _name, page_boxes in _section_boxes(doc):
            look = core._read_look(page_boxes[0])
            assert abs(float(look["CharHeight"]) - 14.0) < 0.6, (index, look)
            assert int(look["CharColor"]) & 0xFFFFFF == 0x00FF00, (index, look)
            assert str(look["CharFontName"]) == "Liberation Mono", (index, look)
            assert _character_of(getattr(page_boxes[0], "TextVerticalAdjust")) == "TOP",\
                (index, look)
    finally:
        lo.close(doc)


@test
def a_stray_box_cannot_set_the_look_of_the_deck():
    """A box on a slide that is meant to have none is on its way out - and silent.

    The first box the command sees is the template, so a leftover from a deck that was
    re-sectioned must not be allowed to decide what every section slide looks like:
    it is being deleted by this very run.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    try:
        doc.DrawPages.getByIndex(0).Name = "title"
        for name in ("welcome", "agenda-notes", "diagram"):
            doc.DrawPages.insertNewByIndex(doc.DrawPages.Count).Name = name
        core.set_sections(doc, [("Introduction", ["welcome", "agenda-notes"]),
                                ("Demo", ["diagram"])])
        # a hand-styled box on the cover, which belongs to no section
        stray = core._new_section_box(doc, doc.DrawPages.getByIndex(0),
                                      core.section_text_name(0))
        stray.CharHeight = 40
        stray.CharColor = 0xFF0000

        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        assert report["look"] == "the default settings", \
            "the cover slide's stray box set the look of the deck"
        assert core.section_text_shapes(doc.DrawPages.getByIndex(0)) == [], \
            "the stray box survived the run that should have taken it away"
        for index in (1, 2, 3):
            look = core._read_look(_only_box(doc.DrawPages.getByIndex(index)))
            assert int(look["CharColor"]) & 0xFFFFFF != 0xFF0000, (index, look)
    finally:
        lo.close(doc)


@test
def the_section_commands_are_on_the_menu():
    """Both commands are reachable from *Plan*, through the URL a click takes.

    ``addons_registered`` reads the merged menu back out of the configuration, which
    is the only proof that ``Addons.xcu`` was accepted at all (fact 6 fails
    silently); this pins that the two new items are in the file, carry a URL, a
    Title and ``Target=_self`` (fact 7), that each URL names a Job
    ``handler.py`` really registers, and that each has an icon of its own (fact 8).
    """
    import xml.etree.ElementTree as ET
    oor = "{http://openoffice.org/2001/registry}"
    xcu = os.path.join(ROOT, "src", "Addons.xcu")
    handler = os.path.join(ROOT, "src", "handler.py")
    tree = ET.parse(xcu)
    # the *elements* carry no prefix in this file, only the attributes do.  Only a
    # node's **own** props count: the submenu node above the items has all of them
    # as descendants, and taking those would pair one item's URL with the last
    # item's Title - which is exactly what a first version of this test did.
    by_url = {}
    for node in tree.iter("node"):
        props = dict((prop.get(oor + "name"), prop.find("value"))
                     for prop in node.findall("prop"))
        url = props.get("URL")
        if url is not None and str(url.text or "").startswith(
                "service:org.nicolasderumigny.planimpress."):
            by_url.setdefault(str(url.text), []).append(props)
    wanted = {
        # the label is pinned per URL: the report was that the item reads as the
        # command it is, so *Insert Section Titles* names the inserting one and a
        # shared list of both strings would let them be swapped
        "service:org.nicolasderumigny.planimpress.SectionTitles?section_titles":
            "Insert Section Titles",
        "service:org.nicolasderumigny.planimpress.RemoveSectionTitles?remove_section_titles":
            "Remove Section Titles",
    }
    for url, title in wanted.items():
        nodes = by_url.get(url) or []
        assert nodes, "no menu item for %s: %s" % (url, sorted(by_url))
        titled = [props for props in nodes if props.get("Title") is not None]
        assert titled, "%s has no Title, so the menu would show a blank row" % url
        assert str(titled[0]["Title"].text) == title, titled[0]["Title"].text
        assert any(props.get("Target") is not None
                   and str(props["Target"].text) == "_self" for props in nodes), \
            "%s needs Target=_self (fact 7)" % url
    source = open(handler).read()
    for implementation in ("org.nicolasderumigny.planimpress.SectionTitles",
                           "org.nicolasderumigny.planimpress.RemoveSectionTitles"):
        assert implementation in source, "%s is not registered" % implementation
    for command in ("do_section_titles", "do_remove_section_titles"):
        assert "def %s" % command in source, "handler.py has no %s" % command
    # the icons the menu asks for have to be in the package, or the item is blank
    images = [str(value.text) for value in tree.iter("value")
              if str(value.text or "").startswith("%origin%/icons/")]
    for name in ("section_16.png", "section_26.png",
                 "section_remove_16.png", "section_remove_26.png"):
        assert any(image.endswith(name) for image in images), "no icon for %s" % name
        assert os.path.exists(os.path.join(ROOT, "src", "icons", name)), \
            "icons/%s was never generated" % name


@test
def the_section_fields_are_on_the_settings_dialog():
    """The option screen can say everything the box can be told.

    "in the option, adds new field for the font, color, size and coordinate of the
    textbox" - and each of the four is called *Default …* because that is what it is:
    the command copies the position and the look of the first section slide's own box,
    so a field here only speaks when there is nothing to copy.  A toggle for that would
    be a second answer to the same question, so there is none either, which is asserted
    below alongside the labels.  The geometry is checked here rather than in a screenshot
    because the point is which fields exist, that they are laid out apart, and that the
    two that hold a number say what unit they are in: a field called "X" that means
    centimetres while the file stores 1/100 mm is how a label ends up off the slide.
    """
    from plan_impress import dialog
    values = {"MutedColor": "B0B0B0", "TextColor": "000000", "Title": "Plan",
              "master": "Default", "SectionColor": "1F4E79", "SectionFont": "Arial",
              "SectionSize": "18", "SectionX": "1.4", "SectionY": "0.2",
              "SectionWidth": "25.2"}
    specs = dialog._field_specs(values, ["Default"], ["Liberation Sans", "Arial"])
    by_name = {name: (service, dict(props)) for name, service, props in specs}
    for expected in ("labelSectionColor", "SectionColor", "swatchSectionColor",
                     "labelSectionFont", "SectionFont", "labelSectionSize",
                     "SectionSize", "labelSectionX", "SectionX", "SectionY",
                     "SectionWidth"):
        assert expected in by_name, (expected, sorted(by_name))
    assert by_name["SectionFont"][0].endswith("UnoControlComboBoxModel"), \
        "the font field has to be editable: any name can be typed"
    assert by_name["SectionFont"][1]["StringItemList"] == ("Liberation Sans", "Arial")
    assert by_name["SectionFont"][1]["Text"] == "Arial"
    assert by_name["SectionColor"][1]["Text"] == "1F4E79"
    assert by_name["swatchSectionColor"][1]["BackgroundColor"] == 0x1F4E79
    assert by_name["SectionSize"][1]["Text"] == "18"
    # no toggle: copying the first box is the rule, not a choice somebody has to
    # think of turning on
    for name, service, _props in specs:
        assert "CheckBox" not in service, "%s is a check box that should not exist" % name
        assert "FollowFirst" not in name, name
    # ... and the four fields say for themselves that they are only a default, so a
    # value that the copied box overrules does not read as "the option does not work"
    for name in ("labelSectionColor", "labelSectionFont", "labelSectionSize",
                 "labelSectionX"):
        assert "default" in by_name[name][1]["Label"].lower(), \
            "%s says %r" % (name, by_name[name][1]["Label"])
    for name in ("SectionColor", "SectionFont", "SectionSize", "SectionX"):
        assert "copy" in by_name[name][1]["HelpText"].lower(), \
            "%s does not say when its value is used" % name
    # the number fields say what they hold
    assert "cm" in by_name["labelSectionX"][1]["Label"].lower(), \
        by_name["labelSectionX"][1]["Label"]
    assert "pt" in by_name["labelSectionSize"][1]["Label"].lower(), \
        by_name["labelSectionSize"][1]["Label"]
    # laid out like the rest of the form: inside the window and apart from each other
    spots = {}
    for name, _service, props in specs:
        props = dict(props)
        assert props["Width"] > 0 and props["Height"] > 0, (name, props)
        assert props["PositionX"] + props["Width"] <= dialog.DIALOG_WIDTH, \
            "%s is drawn outside the window" % name
        assert props["PositionY"] + props["Height"] <= dialog.DIALOG_HEIGHT, \
            "%s is drawn below the window" % name
        assert props.get("FontHeight", 12) >= dialog._FONT or name.startswith("swatch"),\
            "%s shows words in the toolkit's own small font" % name
        spots.setdefault((props["PositionX"], props["PositionY"]), []).append(name)
    shared = {spot: names for spot, names in spots.items() if len(names) > 1}
    assert not shared, "controls sharing a position: %s" % shared


@test
def the_position_fields_speak_centimetres_and_the_file_does_not():
    """The fields are centimetres, the settings are 1/100 mm, and one line joins them.

    Impress's own *Position and Size* dialog works in centimetres, which is what a
    user reads off it and types in; ``core`` wants the 1/100 mm every geometry
    property in the document model uses (fact 20).  Empty is not zero: it means
    "where the deck's own content box is", so a half-typed or nonsense value must
    not move the label to 0,0.
    """
    from plan_impress import dialog
    assert dialog.cm_to_units("1.4") == 1400
    assert dialog.cm_to_units("25,2") == 25200, "a comma is what a French keyboard types"
    assert dialog.cm_to_units("0") == 0
    assert dialog.cm_to_units("") is None
    assert dialog.cm_to_units("   ") is None
    assert dialog.cm_to_units(None) is None
    assert dialog.cm_to_units("nonsense") is None
    assert dialog.cm_to_units("-3") is None, "a negative box would be off the slide"
    assert dialog.units_to_cm(1400) == "1.4"
    assert dialog.units_to_cm(25200) == "25.2"
    assert dialog.units_to_cm(200) == "0.2"
    assert dialog.units_to_cm(None) == "", "unset has to read as an empty field"
    assert dialog.point_text(0) == "" and dialog.point_text(None) == ""
    assert dialog.point_text(18) == "18" and dialog.point_text(17.5) == "17.5"

    stored = {"section_x": "1400", "section_y": -2, "section_z": 5,
              "section_size": "nonsense", "section_width": 25200.6,
              "section_font": "  Arial  ", "section_color": "zzz"}
    folder = os.path.join(ROOT, "out", "profile-section-coerce")
    os.makedirs(folder, exist_ok=True)
    fake_ctx = FakeContext(folder)
    import json
    with open(config.settings_path(fake_ctx), "w") as handle:
        json.dump(stored, handle)
    settings = config.load(fake_ctx)
    assert settings["section_x"] == 1400, settings
    assert settings["section_y"] is None, "a negative length is not a position"
    assert settings["section_size"] == 0.0, "rubbish is the same as the deck's own"
    assert settings["section_width"] == 25201, settings
    assert settings["section_font"] == "Arial", settings
    assert settings["section_color"] == config.DEFAULT_SECTION_COLOR, settings
    assert config.load(FakeContext(folder))["section_x"] == 1400

    # the loader is the only guard: a hand-edited file can hold anything
    with open(config.settings_path(fake_ctx), "w") as handle:
        json.dump({"section_x": True, "section_y": "1.5", "section_size": -4,
                   "section_width": -2.5}, handle)
    settings = config.load(fake_ctx)
    assert settings["section_x"] is None, "a boolean is not a coordinate"
    assert settings["section_y"] == 2, settings
    assert settings["section_size"] == 0.0, settings
    assert settings["section_width"] is None, "-2.5 in the file is not a width"


@test
def dialog_ok_button_accepts_and_cancel_does_not():
    """Pressing OK must not turn into a silent cancel.

    The button listener used to work out *which* button fired from
    ``event.Source.Model.Name``.  When that lookup failed, OK closed the dialog and
    threw the values away with nothing in the log - the user saw a dialog that
    refused to save.  Firing the installed listeners with an event that has no
    usable source is what catches that.
    """
    from plan_impress import dialog
    ctx = lo.connect()
    window = dialog.SettingsDialog(ctx, dict(config.DEFAULTS, title="Agenda"),
                                   ["Master1"])
    window.build()
    try:
        window._peer()
        window._install_listeners()
        # _listeners is the record of what was attached to the peers: two buttons
        # and one colour watcher per hex field.  (The peer proxy has no
        # getActionListeners(), so this is the only way back to the real objects.)
        listeners = {listener.name: listener
                     for _control, listener in window._listeners
                     if hasattr(listener, "name")}
        # ... plus one swatch listener per colour row: clicking the swatch is
        # how the palette picker is opened.  There are three colour rows now - the
        # two the plan slides use and the section box's - so the count says it.
        assert set(listeners) == {"ok", "cancel", "swatch:MutedColor",
                                  "swatch:TextColor", "swatch:SectionColor"}, listeners
        assert len(window._listeners) == 8, window._listeners
        junk = object()              # no Source, no Model: the listener must not care
        # pressing a swatch opens another window; it must not answer the dialog
        from plan_impress import picker as picker_module
        shown = []
        original = picker_module.pick

        def refuse(ctx, entries, current=0, title="", recent=None):
            shown.append((entries, current, title, recent))
            return None              # as if the user had pressed Cancel

        picker_module.pick = refuse
        try:
            # a colour chip is a label and not a button (fact 77), so the click that
            # opens the picker is a mouse release rather than an action
            listeners["swatch:MutedColor"].mouseReleased(junk)
        finally:
            picker_module.pick = original
        assert not window.accepted and not window.rejected, "a swatch closed the dialog"
        assert shown and shown[0][2] == "Pick a Colour", shown
        assert [name for name, _colours in shown[0][0]], "the picker was opened empty"
        listeners["ok"].actionPerformed(junk)
        assert window.accepted and not window.rejected, "OK did not accept the dialog"
        listeners["cancel"].actionPerformed(junk)
        assert window.rejected and not window.accepted, "Cancel did not reject"
        # and the values that would have been saved are the ones on the controls
        assert window.result() is not None
        assert window.result()["title"] == "Agenda", window.result()
    finally:
        window.dispose()


@test
def insert_plan_without_sections():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    try:
        try:
            core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        except core.PlanError as error:
            assert "section" in str(error).lower(), error
        else:
            raise AssertionError("expected a PlanError for a deck without sections")
    finally:
        lo.close(doc)


@test
def master_slide_is_used():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        masters = doc.MasterPages
        if masters.Count < 2:
            # add a second master so the setting has something to pick
            extra = masters.insertNewByIndex(masters.Count)
            extra.Name = "PlanMaster"
            extra.add(doc.createInstance("com.sun.star.drawing.RectangleShape"))
        settings = dict(config.DEFAULTS)
        settings["master"] = "PlanMaster"
        core.insert_plan(doc, settings, ctx)
        pages = doc.DrawPages
        plan = [pages.getByIndex(i) for i in range(pages.Count)
                if str(pages.getByIndex(i).Name).startswith(core.PLAN_PREFIX)]
        assert plan, core.page_names(doc)
        for page in plan:
            assert page.MasterPage.Name == "PlanMaster", page.MasterPage.Name
        settings["master"] = "DoesNotExist"
        # Not an error, and it must not be: the settings are stored **per profile**,
        # so the master named there was picked in whichever presentation was open
        # last, and a deck without a master of that name is the normal case.  It used
        # to refuse - "Insert Plan Slides does nothing in the second deck until I
        # open Settings", which offered only the masters of the deck in front.
        report = core.insert_plan(doc, settings, ctx)
        assert report["master_named"] is False, report
        pages = doc.DrawPages
        plan = [pages.getByIndex(i) for i in range(pages.Count)
                if str(pages.getByIndex(i).Name).startswith(core.PLAN_PREFIX)]
        assert plan, core.page_names(doc)
        for page in plan:
            # the deck's own master, not the one the other deck called up
            assert page.MasterPage.Name == "Default", (page.Name, page.MasterPage.Name)
        assert report["master"] == "Default", report
    finally:
        lo.close(doc)


@test
def insert_plan_leaves_nothing_behind_when_it_fails():
    """A run that stops half way has to be invisible in the deck afterwards.

    Three places this used to go wrong, all of them *after* the first page existed:
    the move commands give up (and the page they inserted stays in the deck, empty,
    because ``insert_page_at`` raises after ``insertNewByIndex``), a slide cannot be
    filled, and the section list comes back wrong.  Each left generated slides in the
    deck with the section ranges of the deck *without* them, so the sections no longer
    matched the slides and the next run had to clean up a wreck instead of a deck -
    measured as three sections coming back as one, the "inserting into the second deck
    leaves empty slides and loses sections" report (``dev/debug_two_documents.py``).
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    real = (core.insert_page_at, core.build_plan_slide, core._check_sections)
    try:
        names = core.page_names(doc)
        sections = [(s["name"], s["indexes"]) for s in core.get_sections(doc)]

        def check_clean(what):
            assert core.page_names(doc) == names, (what, core.page_names(doc), names)
            back = [(s["name"], s["indexes"]) for s in core.get_sections(doc)]
            assert back == sections, (what, back, sections)
            assert core.remove_plan(doc) == 0, (what, core.page_names(doc))

        # 1. the move commands give up on the second page: that page exists already
        state = {"n": 0}

        def moves_that_give_up(d, index, name, c=None):
            state["n"] += 1
            page = real[0](d, index, name, c)
            if state["n"] == 2:
                raise core.PlanError("simulated: the page stayed where it was")
            return page

        core.insert_page_at = moves_that_give_up
        try:
            core.insert_plan(doc, dict(config.DEFAULTS), ctx)
            raise AssertionError("the move failure was swallowed")
        except core.PlanError as error:
            assert "simulated" in str(error), error
        finally:
            core.insert_page_at = real[0]
        check_clean("move commands gave up")

        # 2. the third slide cannot be built at all
        state = {"n": 0}

        def slide_that_fails(d, page, section_names, current, settings, footer=None,
                             master=None):
            state["n"] += 1
            if state["n"] == 3:
                raise RuntimeError("simulated: the placeholders could not be filled")
            return real[1](d, page, section_names, current, settings, footer, master)

        core.build_plan_slide = slide_that_fails
        try:
            core.insert_plan(doc, dict(config.DEFAULTS), ctx)
            raise AssertionError("the build failure was swallowed")
        except RuntimeError as error:
            assert "simulated" in str(error), error
        finally:
            core.build_plan_slide = real[1]
        check_clean("a slide could not be built")

        # 3. the sections came back wrong, which is reported instead of hidden
        def sections_that_refuse(sections_, expected_, names_):
            raise core.PlanError("simulated: the sections do not match the slides")

        core._check_sections = sections_that_refuse
        try:
            core.insert_plan(doc, dict(config.DEFAULTS), ctx)
            raise AssertionError("the section failure was swallowed")
        except core.PlanError as error:
            assert "simulated" in str(error), error
        finally:
            core._check_sections = real[2]
        check_clean("the sections came back wrong")
    finally:
        core.insert_page_at, core.build_plan_slide, core._check_sections = real
        lo.close(doc)


@test
def remove_plan_loses_no_slide_of_a_half_finished_deck():
    """Removing plan slides from a deck whose section list lost track of them.

    The wreck a failed run used to leave behind: generated slides inside the sections
    while the list still describes the deck without them - here produced on purpose by
    making the run skip the section rewrite, which :func:`insert_plan` no longer can.
    ``remove_plan`` cannot restore boundaries the document no longer has, so what it
    *does* have to guarantee is that nothing else is damaged: every slide of the deck
    survives, every generated slide goes, and what the sections say afterwards is
    still a list of runs inside the deck.
    """
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    real_set, real_check = core.set_sections, core._check_sections
    try:
        names = core.page_names(doc)
        core.set_sections = lambda d, sections: []
        core._check_sections = lambda *args: None      # let the run "succeed"
        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        core.set_sections, core._check_sections = real_set, real_check
        pages = doc.DrawPages
        doomed = [i for i in range(pages.Count) if core._is_plan_page(pages.getByIndex(i))]
        assert doomed, "the wreck was not built: %r" % (core.page_names(doc),)
        assert core.remove_plan(doc) == len(doomed), core.page_names(doc)
        assert core.page_names(doc) == names, (core.page_names(doc), names)
        for section in core.get_sections(doc):
            indexes = section["indexes"]
            assert indexes, (section["name"], core.get_sections(doc))
            assert indexes == list(range(indexes[0], indexes[-1] + 1)), (
                section["name"], indexes)
            assert 0 <= indexes[0] and indexes[-1] < pages.Count, (
                section["name"], indexes)
    finally:
        core.set_sections, core._check_sections = real_set, real_check
        lo.close(doc)


# --------------------------------------------------------------------------- #
# the installed extension: menu registration and the dispatch path
# --------------------------------------------------------------------------- #

IDENTIFIER = "org.nicolasderumigny.planimpress"


def _extension_installed(ctx):
    """Is the extension installed in the development profile?"""
    try:
        provider = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.deployment.PackageInformationProvider", ctx)
        if provider is not None and provider.getPackageInfo(IDENTIFIER):
            return True
    except Exception:
        pass
    cache = os.path.join(lo.PROFILE, "user", "uno_packages")
    for root, _dirs, files in os.walk(cache):
        if any(IDENTIFIER in name or "plan-impress" in name for name in files):
            return True
    return False


def _flatten_config(value, out, depth=0):
    """Collect every string in a configmgr subtree into ``out``.

    Configuration access hands back a shifting mix of ``XNameAccess`` groups,
    ``PropertyValue`` sequences and UNO structs, so walk all three shapes.
    """
    if depth > 14 or len(out) > 4000:
        return
    if isinstance(value, str):
        out.append(value)
        return
    if isinstance(value, (bytes, bool, int, float)) or value is None:
        return
    try:  # a group: XNameAccess
        names = list(value.getElementNames())
    except Exception:
        names = None
    if names is not None:
        for name in names:
            out.append(name)
            try:
                _flatten_config(value.getByName(name), out, depth + 1)
            except Exception:
                pass
        return
    if hasattr(value, "Name") and hasattr(value, "Value"):  # PropertyValue
        out.append(str(value.Name))
        _flatten_config(value.Value, out, depth + 1)
        return
    try:  # sequence or struct
        items = list(value)
    except TypeError:
        return
    for item in items:
        _flatten_config(item, out, depth + 1)


@test
def addons_registered():
    ctx = lo.connect()
    if not _extension_installed(ctx):
        raise Skip("extension not installed (make install)")
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx)
    view = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationAccess",
        (lo.pv("nodepath", "/org.openoffice.Office.Addons/AddonUI"),))
    strings = []
    _flatten_config(view, strings)
    joined = "\n".join(strings)
    for expected in (IDENTIFIER, ".uno:SlideShowMenu", "AddAfter", "AddPath",
                     "com.sun.star.presentation.PresentationDocument",
                     "service:org.nicolasderumigny.planimpress.InsertPlan?insert",
                     "service:org.nicolasderumigny.planimpress.Settings?settings",
                     "service:org.nicolasderumigny.planimpress.RemovePlan?remove",
                     "service:org.nicolasderumigny.planimpress.SectionTitles?section_titles",
                     "service:org.nicolasderumigny.planimpress.RemoveSectionTitles"
                     "?remove_section_titles",
                     "Insert Section Titles", "Remove Section Titles",
                     "icons/section_16.png", "icons/section_remove_26.png",
                     "private:separator", "Plan", "icons/plan_16.png"):
        assert expected in joined, "missing from Addons.xcu: %s" % expected


def _menu_rows():
    """``Addons.xcu``'s own rows of the *Plan* submenu, in the order they are written.

    ``[(name, url, title), ...]``, a separator included as ``url ==
    "private:separator"``.  Only the children of the one ``Submenu`` node count: the
    ``Images`` nodes carry the very same ``URL`` property, and taking those called this
    deck eleven items.
    """
    import xml.etree.ElementTree as ET
    oor = "{http://openoffice.org/2001/registry}"
    tree = ET.parse(os.path.join(ROOT, "src", "Addons.xcu"))
    rows = []
    for submenu in tree.iter("node"):
        if submenu.get(oor + "name") != "Submenu":
            continue
        for node in submenu:
            props = {}
            for prop in node.findall("prop"):
                value = prop.find("value")
                props[prop.get(oor + "name")] = (
                    str(value.text) if value is not None else "")
            rows.append((node.get(oor + "name"), props.get("URL", ""),
                         props.get("Title", "")))
    return rows


@test
def the_menu_groups_the_commands_in_the_order_the_deck_is_worked_in():
    """Three groups of two, in the order the deck is worked in.

    "Reorganise the menu that way: Insert plan slide / Remove plan slides / separator /
    Insert section title / Remove section title / separator / parameter / debug log".
    Each pair is a command and its undo, so they sit together instead of *Settings…*
    splitting *Insert Plan Slides* from *Remove Plan Slides* the way it used to, and the
    two separators are what says which group a row belongs to.

    The file is only half the claim: the office re-sorts the rows by node name (fact
    98).  ``the_menu_rows_come_back_in_the_order_the_file_lists_them`` asks the merged
    configuration for this same list and ``dev/probe_menu_order.py`` photographs the
    popup and matches the air the separators leave against it.
    """
    rows = _menu_rows()
    urls = [url for _name, url, _title in rows]
    assert urls == MENU_ROWS, [url.rsplit(".", 1)[-1] for url in urls]
    for url, _name, title in rows:
        if url in MENU_TITLES:
            assert str(title) == MENU_TITLES[url], \
                "%s reads %r, not %r" % (url, title, MENU_TITLES[url])
    # the two rows a separator is meant to stand in front of: the first of each group
    # after the first, and nothing else.  Counted here rather than left to the list
    # above so a third separator cannot slip in and the message says where it is.
    before = [urls[index + 1].rsplit(".", 1)[-1]
              for index, url in enumerate(urls) if url == "private:separator"]
    assert before == ["SectionTitles?section_titles",
                      "Settings?settings"], before


@test
def toggle_debug_log_is_the_last_row_and_the_tail_is_its_own_group():
    """The last row is *Toggle Debug Log*, and the tail is separated off as a group.

    Two reports, one rule: "put the *toggle debug log* last with a separator in the
    menu", then the order it was asked for - plan, section, then the two that change
    nothing in the deck.  So the separator stands in front of the *pair* the debug
    command belongs to rather than directly in front of the command itself: the last
    three rows are separator, *Settings…*, *Toggle Debug Log*.

    The numbering is part of the menu's look and is pinned here in both spellings of
    the comparison, because the office builds the popup out of the node names the
    configuration answers with and answers them **sorted numerically**, not in the
    order they were written (fact 98): while the section commands were named
    ``mm41``/``mm42`` between ``mm4`` and ``mm5`` they came back after ``mm6``, so
    *Toggle Debug Log* sat in the middle of the menu.
    """
    rows = _menu_rows()
    assert rows, "Addons.xcu has no Submenu"
    names = [name for name, _url, _title in rows]
    assert all(re.match(r"^mm\d+$", name) for name in names), names
    assert len(set(len(name) for name in names)) == 1, \
        "the rows are not one fixed-width sequence, so the two orders can disagree: %s" \
        % names
    assert sorted(names) == names, "the file lists them out of order: %s" % names
    numbers = [int(re.sub(r"\D", "", name) or 0) for name in names]
    assert numbers == sorted(numbers), \
        "the office sorts the rows as %s, which is not the written order" % numbers
    items = [row for row in rows if row[1].startswith("service:")]
    assert len(items) == 6, [row[2] for row in items]
    urls = [url for _name, url, _title in rows]
    assert urls[-1] == DEBUG_URL, "the last row is %r (%s)" % (rows[-1][2], urls[-1])
    assert urls[-3:] == ["private:separator", SETTINGS_SERVICE, DEBUG_URL], \
        "the tail is %s: *Toggle Debug Log* is not the last row of a separated group" \
        % [url.rsplit(".", 1)[-1] for url in urls[-3:]]


@test
def the_menu_rows_come_back_in_the_order_the_file_lists_them():
    """What the merged configuration really hands back for the submenu, row by row.

    ``addons_registered`` proves the file was accepted at all; this proves the
    configuration still answers the rows in the written order - the order the popup is
    built from (fact 98) - and that they are the six commands in the three groups the
    deck is worked in (``MENU_ROWS``).  ``dev/probe_menu_order.py`` is the screenshot
    side of the same claim: a separator draws no line in this theme, so the rows are
    counted and the air between them measured against what the file asks for.
    """
    ctx = lo.connect()
    if not _extension_installed(ctx):
        raise Skip("extension not installed (make install)")
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx)
    view = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationAccess",
        (lo.pv("nodepath", SUBMENU_PATH),))
    names = list(view.getElementNames())
    written = [name for name, _url, _title in _menu_rows()]
    assert names == written, \
        "the office hands the rows back as %s, the file lists %s" % (names, written)
    urls = [str(getattr(view.getByName(name), "URL", "") or "") for name in names]
    assert urls == MENU_ROWS, \
        "the popup is built in the order %s, not the order the deck is worked in" % \
        [url.rsplit(".", 1)[-1] for url in urls]


@test
def menu_dispatch_inserts_slides():
    """The exact path a menu click takes: dispatch the service URL on the frame."""
    ctx = lo.connect()
    if not _extension_installed(ctx):
        raise Skip("extension not installed (make install)")
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        before = core.page_names(doc)
        lo.dispatch(doc, SERVICE)
        # Job dispatch can queue the request, so give the office a moment.
        lo.wait_until(lambda: len(core.page_names(doc)) != len(before))
        names = core.page_names(doc)
        assert len(names) == len(before) + 4, names
        assert names[0] == core.OVERVIEW_NAME, names
    finally:
        lo.close(doc)


@test
def menu_dispatch_writes_section_titles():
    """The path a *Section Titles* click takes, through the installed extension.

    Registering the Job under a second implementation name is the kind of thing that
    can go wrong in silence - a menu item that looks right and does nothing - so this
    dispatches the URL the menu carries and waits for the boxes to appear.
    """
    ctx = lo.connect()
    if not _extension_installed(ctx):
        raise Skip("extension not installed (make install)")
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        assert core.remove_section_titles(doc) == 0, "the deck was not clean"
        lo.dispatch(doc, SECTION_SERVICE)
        pages = doc.DrawPages
        found = lo.wait_until(
            lambda: sum(len(core.section_text_shapes(pages.getByIndex(i)))
                        for i in range(pages.Count)) > 0)
        assert found, "dispatching %s drew nothing" % SECTION_SERVICE
        sections = core.get_sections(doc)
        for index in range(pages.Count):
            boxes = core.section_text_shapes(pages.getByIndex(index))
            assert len(boxes) == 1, "slide %d has %d boxes" % (index, len(boxes))
            assert str(boxes[0].getString()) == str(core.section_of(sections, index))
    finally:
        lo.close(doc)


@test
def settings_job_saves():
    """The Settings job writes the file the next insert_plan reads.

    The dialog itself cannot be driven from here (it is modal), so this checks
    the persistence half of the command.
    """
    ctx = lo.connect()
    if not _extension_installed(ctx):
        raise Skip("extension not installed (make install)")
    path = config.settings_path(ctx)
    backup = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            backup = handle.read()
    try:
        config.save(ctx, dict(config.DEFAULTS, muted_color=0xABCDEF,
                              text_color=0x112233, title="Agenda"))
        desk = lo.desktop(ctx)
        doc = lo.open_doc(desk, FIXTURE, hidden=False)
        try:
            core.remove_plan(doc)
            core.insert_plan(doc, config.load(ctx), ctx)
            pages = doc.DrawPages
            by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                       for i in range(pages.Count)}
            body = core._body_shape(by_name[core.section_page_name(2)])
            colors = _paragraph_colors(body)
            # the saved colours are what ended up on the slide: the third
            # section is the current one on this plan slide
            assert colors[2] == 0x112233, colors
            assert colors[:2] == [0xABCDEF, 0xABCDEF], colors
            assert core._title_shape(by_name[core.OVERVIEW_NAME]).getString() == "Agenda"
        finally:
            lo.close(doc)
    finally:
        if backup is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(backup)


def _run_with_recovery(name, function):
    """Run one test against a live office: ``(outcome, report, restarts)``.

    The office takes the whole document model - and with it the test - down when it
    dies, and a long UI session does kill it now and then: ``free(): invalid
    pointer`` in ``cppu::OWeakAggObject::release`` inside ``libeditenglo``, while
    pyuno lets go of a text object whose document is already gone
    (``out/soffice.log`` keeps the stack).  It is LibreOffice going away under load,
    not the extension refusing - a second pass of this suite over the *committed*
    code does it too, on decks the extension never touched - and without a retry one
    death reads as eighteen failures.  So a test that died with the office gets one
    retry on a fresh one; a test that fails twice has failed.

    ``report`` is the reason for a ``"skip"`` or the ``(error, traceback)`` of a
    ``"fail"``, the text taken here because ``sys.exc_info()`` is empty by the time
    the caller prints it.
    """
    restarts = 0
    for attempt in (0, 1):
        if not lo.is_alive():
            lo.restart()
            restarts += 1
            print("     %s  the office was gone: started a new one%s"
                  % (name, ", trying the test again" if attempt else ""))
        try:
            function()
        except Skip as reason:
            return "skip", reason, restarts
        except Exception as error:
            if attempt == 0 and lo.died():
                continue
            return "fail", (error, traceback.format_exc()), restarts
        return "ok", None, restarts


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    failed = skipped = restarts = 0
    for name, function in RESULTS:
        if only and only not in name:
            continue
        outcome, value, lost = _run_with_recovery(name, function)
        restarts += lost
        if outcome == "skip":
            skipped += 1
            print("SKIP %-38s %s" % (name, value))
        elif outcome == "fail":
            failed += 1
            error, where = value
            print("FAIL %-38s %s" % (name, error))
            print(where)
        else:
            print("ok   %-38s" % name)
    total = len([1 for name, _ in RESULTS if not only or only in name])
    print("\n%d passed, %d failed, %d skipped (of %d)%s"
          % (total - failed - skipped, failed, skipped, total,
             "" if not restarts else ", office restarted %d time(s)" % restarts))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
