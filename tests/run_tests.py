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
import time
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
SERVICE = "service:org.devsys.planimpress.InsertPlan?insert"
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
    """The grid is sixty buttons: they must not land on top of each other."""
    from plan_impress import picker
    colours = [("c%d" % index, index * 1000) for index in range(25)]
    specs = picker._field_specs(["Standard", "Custom"], colours, 0, 3, 0x123456)
    spots = {}
    for name, _service, props in specs:
        props = dict(props)
        assert props["Width"] > 0 and props["Height"] > 0, (name, props)
        assert props["PositionX"] + props["Width"] <= picker.DIALOG_WIDTH, name
        assert props["PositionY"] + props["Height"] <= picker.DIALOG_HEIGHT, name
        spots.setdefault((props["PositionX"], props["PositionY"]), []).append(name)
    shared = {spot: names for spot, names in spots.items() if len(names) > 1}
    assert not shared, "controls sharing a position: %s" % shared
    cells = {name: dict(props) for name, _service, props in specs
             if name.startswith("cell")}
    assert len(cells) == picker.CELLS, len(cells)
    for index in range(len(colours)):
        assert cells["cell%d" % index]["BackgroundColor"] == colours[index][1]
        assert cells["cell%d" % index]["HelpText"] == colours[index][0], \
            "a cell without its colour name says nothing on hover"
    for index in range(len(colours), picker.CELLS):
        assert cells["cell%d" % index]["HelpText"] == "", "an empty cell looks pickable"


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

    def answer(ctx, entries, current=0, title="", parent_window=None):
        seen.append((entries, current))
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
        offered = [name for name, _colours in seen[0][0]]
        assert "Recently used" in offered, offered[:4]
        assert "standard" in [name.lower() for name in offered], offered[:4]
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
                          "recent_colors": []}, result
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
        # how the palette picker is opened
        assert set(listeners) == {"ok", "cancel", "swatch:MutedColor",
                                  "swatch:TextColor"}, listeners
        assert len(window._listeners) == 6, window._listeners
        junk = object()              # no Source, no Model: the listener must not care
        # pressing a swatch opens another window; it must not answer the dialog
        from plan_impress import picker as picker_module
        shown = []
        original = picker_module.pick

        def refuse(ctx, entries, current=0, title="", parent_window=None):
            shown.append((entries, current, title))
            return None              # as if the user had pressed Cancel

        picker_module.pick = refuse
        try:
            listeners["swatch:MutedColor"].actionPerformed(junk)
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

IDENTIFIER = "org.devsys.planimpress"


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
                     "service:org.devsys.planimpress.InsertPlan?insert",
                     "service:org.devsys.planimpress.Settings?settings",
                     "service:org.devsys.planimpress.RemovePlan?remove",
                     "private:separator", "Plan", "icons/plan_16.png"):
        assert expected in joined, "missing from Addons.xcu: %s" % expected


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
