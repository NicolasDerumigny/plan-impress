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
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402  (also puts pyuno on sys.path)

from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sections.odp")
SERVICE = "service:org.devsys.planimpress.InsertPlan?insert"

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
                          "title": "Agenda", "master": "Master2"}, result
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
        assert names[1] == "PlanImpress:Section=0", names
        assert names[2] == "welcome", names
        assert names.count(core.OVERVIEW_NAME) == 1
        for index in range(3):
            assert ("PlanImpress:Section=%d" % index) in names, names
        # one plan slide per section, at the top of it
        sections = core.get_sections(doc)
        assert len(sections) == 3, sections
        for index, section in enumerate(sections):
            assert section["slides"][0] == "PlanImpress:Section=%d" % index, section
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
            page = by_name["PlanImpress:Section=%d" % index]
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
        assert names[2] == "PlanImpress:Section=0", names
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
        assert set(listeners) == {"ok", "cancel"}, listeners
        assert len(window._listeners) == 4, window._listeners
        junk = object()              # no Source, no Model: the listener must not care
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
        try:
            core.insert_plan(doc, settings, ctx)
        except core.PlanError as error:
            assert "DoesNotExist" in str(error), error
        else:
            raise AssertionError("expected a PlanError for a missing master page")
    finally:
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
            body = core._body_shape(by_name["PlanImpress:Section=2"])
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


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    failed = skipped = 0
    for name, function in RESULTS:
        if only and only not in name:
            continue
        try:
            function()
        except Skip as reason:
            skipped += 1
            print("SKIP %-38s %s" % (name, reason))
        except Exception as error:
            failed += 1
            print("FAIL %-38s %s" % (name, error))
            traceback.print_exc()
        else:
            print("ok   %-38s" % name)
    total = len([1 for name, _ in RESULTS if not only or only in name])
    print("\n%d passed, %d failed, %d skipped (of %d)"
          % (total - failed - skipped, failed, skipped, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
