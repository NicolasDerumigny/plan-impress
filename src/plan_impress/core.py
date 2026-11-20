"""Document model work for Plan Impress.

Everything here talks to the Impress document model through UNO only; no UI
code and no imports from :mod:`plan_impress.dialog`, so it can be driven from
the test scripts in ``tests/`` against a running LibreOffice.

Two facts about the Impress API shaped this module (both measured against
LibreOffice 26.8, see the ``dev/debug_*.py`` reproducers):

``XDrawPages.insertNewByIndex(k)``
    inserts the new page *after* position ``k``, clamps ``k`` to the page
    count and therefore can never reach index 0.  The container has no
    reorder method either.  :func:`insert_page_at` works around this by
    inserting and then walking the page into place with the
    ``.uno:MovePageUp`` / ``.uno:MovePageDown`` dispatcher commands.

``XImpressDocumentFacade``-style ``SlideSections``
    is a ``sequence<com.sun.star.beans.PropertyValue>`` whose *values* are
    themselves property-value sequences (``Name``, ``Id``, ``SlideNameList``).
    Writing them back only works when the nested values carry an explicit
    ``uno.Any`` type; plain tuples are silently dropped.  Sections are also
    purely positional and are *not* adjusted by ``insertNewByIndex``, so the
    whole section list is rewritten after every insertion.

    The names in ``SlideNameList`` are *not* ``DrawPages`` names either, see the
    note above :func:`get_sections`; everything in this module works on page
    positions internally and only spells names on the way in and out.

Deleting a slide
    a section is anchored on its first slide, so removing a plan slide that
    leads a section leaves the boundaries of the remaining sections wrong.
    :func:`remove_plan_slides` therefore snapshots the cleaned section lists
    before deleting and rewrites them afterwards.
"""

import re
import time

import uno

#: Every slide this extension generates carries this name prefix; it is how a
#: re-run recognises (and regenerates) its own slides.
PLAN_PREFIX = "PlanImpress:"
OVERVIEW_NAME = "PlanImpress:Overview"
SECTION_NAME_TEMPLATE = "PlanImpress:Section=%d"

_PROPERTY_VALUE = "com.sun.star.beans.PropertyValue"

# com.sun.star.awt.FontWeight.BOLD
_FONT_BOLD = 150.0


class PlanError(Exception):
    """User-facing failure: the handler shows the message in a dialog."""


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _prop(name, value):
    struct = uno.createUnoStruct(_PROPERTY_VALUE)
    struct.Name = name
    struct.Value = value
    return struct


def _size(width, height):
    return uno.createUnoStruct("com.sun.star.awt.Size", int(width), int(height))


def _point(x, y):
    return uno.createUnoStruct("com.sun.star.awt.Point", int(x), int(y))


def page_names(doc):
    pages = doc.DrawPages
    return [pages.getByIndex(i).Name for i in range(pages.Count)]


def _is_plan_page(page):
    try:
        return str(page.Name).startswith(PLAN_PREFIX)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
#
# The API exchanges slide *names* but LibreOffice stores a *range of positions*,
# and both directions behave differently from what the property suggests (all of
# this is measured, see ``dev/debug_sections.py``):
#
# * The name a page answers to is its ``LinkDisplayName`` ("Slide 3"), or the
#   value a client last assigned to ``page.Name``.  ``DrawPages`` names are a
#   *different* name and the section code never matches them, so a deck the user
#   created in Impress itself lists its sections as ``Slide 3``, ``Slide 4``, …
#   while ``DrawPages.getByIndex(2).Name`` is ``page3``.
# * On a write, every name is resolved to the position it names *right now*: the
#   first resolvable name fixes the section's start, the section then runs to the
#   next section's start, the last one to the end of the deck, and names that
#   match nothing are dropped in silence.
#
# Positions are therefore the only safe currency: :func:`get_sections` turns the
# reported names into indexes, :func:`set_sections` takes indexes back, and the
# callers compute where the slides must have ended up after an insertion
# (:func:`_section_with_plan`) instead of trying to recognise them again - the
# ``DrawPages`` names are renumbered by position too.

#: The name LibreOffice gives a page that no client has renamed.
_AUTO_PAGE_NAME = re.compile(r"^page\d+$")
#: The default section spelling, "Slide 7"; used as a last resort for a name the
#: document no longer has a page for.
_DISPLAY_PAGE_NAME = re.compile(r"^Slide (\d+)$")


def _display_name(page, index):
    """The name the section API knows ``page`` by: "Slide 3" unless renamed."""
    try:
        value = getattr(page, "LinkDisplayName", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return "Slide %d" % (index + 1)


def _default_section_names(doc):
    """What a page answers to, as far as ``DrawPages`` can tell."""
    pages = doc.DrawPages
    out = []
    for index in range(pages.Count):
        page = name = None
        try:
            page = pages.getByIndex(index)
            name = str(page.Name)
        except Exception:
            pass
        if name and not _AUTO_PAGE_NAME.match(name):
            out.append(name)          # a client renamed this page
        else:
            out.append(_display_name(page, index))
    return out


def _entry_field(entry, field):
    """One field (``Name``, ``Id``, ``SlideNameList``) of a section entry."""
    try:
        for prop in entry.Value:
            if prop.Name == field:
                return prop.Value
    except (TypeError, AttributeError):
        pass
    return None


def _entry_slides(entry):
    """The ``SlideNameList`` of one ``PropertyValue`` section entry, or ``None``."""
    value = _entry_field(entry, "SlideNameList")
    if value is None:
        return None
    return [str(name) for name in value]


def _raw_sections(doc):
    """The section property as LibreOffice hands it out, or ``[]``."""
    try:
        return list(doc.SlideSections)
    except Exception:
        return []


def _section_names(doc):
    """Position -> the name the section API reports for that page.

    The document's own list is the only place those spellings can be read - a
    page renamed to something that looks auto-generated answers to it and to
    nothing :func:`_default_section_names` would guess - so it wins wherever it
    can be anchored.  Anchoring is safe because a section is a contiguous range
    and the list is rendered in page order.
    """
    names = _default_section_names(doc)
    positions = {}
    for index, name in enumerate(names):
        positions.setdefault(name, index)
    for entry in _raw_sections(doc):
        slides = _entry_slides(entry)
        if not slides:
            continue
        start = positions.get(slides[0])
        if start is None or start + len(slides) > len(names):
            continue
        names[start:start + len(slides)] = slides
    return names


def _name_positions(doc):
    """Map every name a page can be listed under onto its position."""
    positions = {}
    for index, name in enumerate(_section_names(doc)):
        positions.setdefault(name, index)
    # A hand-written file may list the DrawPages name instead; accept it too.
    pages = doc.DrawPages
    for index in range(pages.Count):
        try:
            positions.setdefault(str(pages.getByIndex(index).Name), index)
        except Exception:
            continue
    return positions


def get_sections(doc):
    """Return ``[{"name", "slides", "indexes", "start"}]``.

    ``slides`` are the names as the document reports them, ``indexes`` the pages
    they resolve to and ``start`` is ``indexes[0]`` - or ``-1`` when a name
    matches no page, which is how a section pointing at deleted slides shows up.
    """
    positions = _name_positions(doc)
    try:
        total = doc.DrawPages.Count
    except Exception:
        total = 0
    result = []
    for entry in _raw_sections(doc):
        slides = _entry_slides(entry)
        if not slides:
            continue  # LibreOffice keeps empty sections around; ignore them
        indexes = []
        for name in slides:
            index = positions.get(name)
            if index is None:  # a stale "Slide 7" from before a deletion
                match = _DISPLAY_PAGE_NAME.match(name)
                if match:
                    index = int(match.group(1)) - 1
            if index is None or not 0 <= index < total:
                indexes = []      # unresolvable: the caller reports the section
                break
            indexes.append(index)
        result.append({"name": str(_entry_field(entry, "Name") or ""),
                       "id": _entry_field(entry, "Id"),
                       "slides": slides,
                       "indexes": indexes,
                       "start": indexes[0] if indexes else -1})
    return result


def set_sections(doc, sections):
    """Write ``sections``, a list of ``(name, members)`` pairs or dicts.

    ``members`` are page **positions**; a slide name is accepted too but means
    what the section API means by it *now*, which is why the callers here use
    positions.  The ranges are contiguous, so only the first member of a section
    really decides where it starts.  A dict may carry the section's ``id``, which
    the assignment would otherwise lose - other documents refer to a section by
    it.
    """
    spelled = _section_names(doc)
    outer = []
    for index, entry in enumerate(sections):
        ident = None
        if isinstance(entry, dict):
            name = entry.get("name", "")
            members = entry.get("slides", [])
            ident = entry.get("id")
        else:
            name, members = entry
        slides = []
        for member in members:
            if isinstance(member, bool) or not isinstance(member, int):
                slides.append(str(member))
            elif 0 <= member < len(spelled):
                slides.append(spelled[member])
        if not slides:
            continue          # an empty section is invisible and only gets lost
        inner = [
            _prop("Name", uno.Any("string", str(name))),
            _prop("SlideNameList", uno.Any("[]string", tuple(slides))),
        ]
        if ident:
            inner.insert(1, _prop("Id", uno.Any("string", str(ident))))
        outer.append(_prop("Section%d" % index,
                           uno.Any("[]%s" % _PROPERTY_VALUE, tuple(inner))))
    doc.SlideSections = uno.Any("[]%s" % _PROPERTY_VALUE, tuple(outer))
    return get_sections(doc)


def clear_sections(doc):
    set_sections(doc, [])


# --------------------------------------------------------------------------- #
# page insertion / removal
# --------------------------------------------------------------------------- #

def _index_of(pages, page):
    """Position of ``page``; compared by name because UNO proxies are not stable."""
    name = page.Name
    for i in range(pages.Count):
        try:
            if pages.getByIndex(i).Name == name:
                return i
        except Exception:
            continue
    return -1


def _context(doc):
    """The component context to create services in.

    In-process (a Job) this is the document's own context.  Out-of-process test
    scripts must pass the context they connected with, because a remote document
    proxy does not expose ``getComponentContext()``.
    """
    try:
        return doc.getComponentContext()
    except Exception:
        return uno.getComponentContext()


def _dispatch(doc, command, ctx=None):
    ctx = ctx or _context(doc)
    helper = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", ctx)
    controller = doc.CurrentController
    helper.executeDispatch(controller.Frame, command, "", 0, ())


def _wait_for_move(pages, page, previous, timeout=3.0):
    """Poll until the page actually moved; the dispatch is not synchronous."""
    deadline = time.time() + timeout
    current = previous
    while time.time() < deadline:
        current = _index_of(pages, page)
        if current != previous:
            return current
        time.sleep(0.05)
    return current


def insert_page_at(doc, index, name, ctx=None):
    """Insert an empty page and make sure it ends up exactly at ``index``.

    ``insertNewByIndex(k)`` puts the page at ``k + 1`` and cannot reach 0 at
    all, so the page is walked into place with the move commands; those only
    act on the slide the view has selected, hence ``setCurrentPage`` first.  See
    the module docstring and ``dev/debug_move.py``.
    """
    pages = doc.DrawPages
    target = max(0, min(int(index), pages.Count))
    page = pages.insertNewByIndex(max(0, target - 1)) if target \
        else pages.insertNewByIndex(0)
    page.Name = name
    controller = doc.CurrentController
    current = _index_of(pages, page)
    for _round in range(100):
        if current == target:
            return page
        try:
            controller.setCurrentPage(page)
        except Exception:
            pass
        _dispatch(doc, ".uno:MovePageUp" if current > target else ".uno:MovePageDown",
                  ctx)
        moved = _wait_for_move(pages, page, current)
        if moved == current:
            break
        current = moved
    raise PlanError("Could not move the new plan slide to position %d (it stayed at "
                    "%d). Select the slide panel and try again." % (target, current))


def _shifted_down(indexes, removed):
    """``indexes`` as they read after the pages at ``removed`` were deleted.

    ``DrawPages`` names cannot be used to recognise a page across a structural
    change either - LibreOffice renumbers them by position, so deleting one page
    turns ``page4`` into ``page3`` - which leaves arithmetic on positions as the
    only way to say "the same slides" before and after.
    """
    out = []
    for index in indexes:
        if index in removed:
            continue
        out.append(index - len([done for done in removed if done < index]))
    return out


def _section_with_plan(start, end, targets):
    """Positions of the slides ``start``..``end`` occupy, plus a new first one.

    ``targets`` are the positions pages were inserted at (bottom-up, so each was
    still valid when it happened); every insertion at or below a slide pushes it
    one further down.
    """
    span = [index + len([target for target in targets if target <= index])
            for index in range(start, end + 1)]
    return [span[0] - 1] + span        # the plan slide went in front of the first


def _clean_sections(sections, doomed):
    """Sections with this extension's own slides taken out, as positions.

    LibreOffice stores a section as a positional range anchored on its first
    slide, so deleting the plan slide it points at shifts the boundaries and
    leaves the remaining membership wrong (measured: removing the plan slides of
    three sections produced two sections with the wrong slides in them).  Every
    section is therefore rebuilt from this cleaned copy after the pages are
    deleted.
    """
    cleaned = []
    for section in sections:
        if not section["indexes"]:
            # Nothing resolved - a section that points at slides which are gone.
            # Hand its own names back untouched instead of dropping the section.
            slides = [name for name in section["slides"]
                      if not str(name).startswith(PLAN_PREFIX)]
            if slides:
                cleaned.append({"name": section["name"], "id": section.get("id"),
                                "slides": slides})
            continue
        keep = _shifted_down(section["indexes"], doomed)
        if keep:
            cleaned.append({"name": section["name"], "id": section.get("id"),
                            "slides": keep})
    return cleaned


def remove_plan_slides(doc):
    """Delete every slide this extension generated.  Returns how many."""
    pages = doc.DrawPages
    doomed = [i for i in range(pages.Count) if _is_plan_page(pages.getByIndex(i))]
    if not doomed:
        return 0
    cleaned = _clean_sections(get_sections(doc), doomed)
    for index in reversed(doomed):   # bottom-up: the pending indexes stay valid
        try:
            pages.remove(pages.getByIndex(index))
        except Exception:
            pass
    # Restore the boundaries the deletions disturbed.
    set_sections(doc, cleaned)
    return len(doomed)


# --------------------------------------------------------------------------- #
# slide content
# --------------------------------------------------------------------------- #

def _master_page(doc, wanted):
    """The master slide to base plan slides on: by name, else the first one."""
    masters = doc.MasterPages
    if not masters.Count:
        raise PlanError("This presentation has no master slides.")
    if wanted:
        for i in range(masters.Count):
            if masters.getByIndex(i).Name == wanted:
                return masters.getByIndex(i)
        raise PlanError("Master slide '%s' no longer exists." % wanted)
    return masters.getByIndex(0)


def _text_shapes(page):
    out = []
    for i in range(page.Count):
        try:
            shape = page.getByIndex(i)
            if shape.supportsService("com.sun.star.drawing.Text"):
                out.append(shape)
        except Exception:
            continue
    return out


def _is_title(shape):
    """True for a presentation title placeholder.

    ``ShapeType`` cannot be used for this: the body placeholder's type is
    ``...SubtitleTextShape``, which also contains the word "Title".
    """
    try:
        if shape.supportsService("com.sun.star.presentation.TitleTextShape"):
            return True
    except Exception:
        pass
    return str(getattr(shape, "ShapeType", "")).endswith(".TitleTextShape")


def _title_shape(master):
    for shape in _text_shapes(master):
        if _is_title(shape):
            return shape
    return None


def _body_shape(page):
    """The content placeholder: the biggest text shape that is not the title."""
    candidates = [s for s in _text_shapes(page) if not _is_title(s)]
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda s: s.Size.Width * s.Size.Height)
    except Exception:
        return candidates[0]


def _rect(shape, fallback_pos, fallback_size, page_width, page_height):
    """Reuse a master placeholder's rectangle so plan slides match the deck.

    The rectangle is only taken when it actually fits on the page: the default
    Impress master keeps its title placeholder partly *off* the slide (y = -32 mm)
    and two thirds of the page tall, and copying that verbatim renders the
    heading outside the slide, so in that case the computed fallback is used
    instead of a clipped version of it.
    """
    x, y = fallback_pos[0], fallback_pos[1]
    width, height = fallback_size[0], fallback_size[1]
    if shape is not None:
        try:
            px, py = int(shape.Position.X), int(shape.Position.Y)
            pw, ph = int(shape.Size.Width), int(shape.Size.Height)
            if px >= 0 and py >= 0 and px + pw <= page_width and py + ph <= page_height:
                x, y, width, height = px, py, pw, ph
        except Exception:
            pass
    return int(x), int(y), int(width), int(height)


#: Space between baselines, as a multiple of the character height.
_LINE_SPACING = 1.35
#: Fallback character heights, used when the master placeholder does not give a
#: usable one.  ``CharHeight`` is a **point** size; the geometry properties are
#: 1/100 mm, so the two must never be mixed (deriving the size from the page
#: height produced a 260 pt heading).
_TITLE_PT = 32.0
_BODY_PT = 18.0
#: 1 pt in the 1/100 mm units the drawing API uses (1 pt = 0.3527 mm).
_UNITS_PER_POINT = 35.2778


def _master_char_height(shape, fallback):
    """The point size a master placeholder asks for, when it says something sane."""
    value = getattr(shape, "CharHeight", None) if shape is not None else None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if 6.0 < value < 100.0 else fallback


def _fit_point_size(size, box_height, lines):
    """Largest size not above ``size`` whose ``lines`` lines fit in ``box_height``."""
    if lines < 1:
        return size
    per_line = (box_height / _UNITS_PER_POINT) / float(lines) / _LINE_SPACING
    return max(10.0, min(size, per_line))


#: Title placeholder services, best first.
TITLE_SERVICES = (
    "com.sun.star.presentation.TitleTextShape",
    "com.sun.star.drawing.TextShape",
)

#: Body placeholder services, best first.  ``com.sun.star.presentation.
#: SubtitleTextShape`` is *not* registered in LibreOffice 26.x, so the list
#: degrades to the outline shape Impress layouts actually use, and finally to
#: a plain text shape.
BODY_SERVICES = (
    "com.sun.star.drawing.plugin.presentation.SubtitleTextShape",
    "com.sun.star.presentation.SubtitleTextShape",
    "com.sun.star.presentation.OutlinerShape",
    "com.sun.star.drawing.TextShape",
)


def _create_text_shape(doc, page, services):
    for service in services:
        try:
            shape = doc.createInstance(service)
        except Exception:
            continue
        try:
            page.add(shape)
        except Exception:
            continue
        return shape
    raise PlanError("Could not create a text shape on the slide.")


def _make_text_shape(doc, page, services, text, x, y, width, height,
                     char_height, bold=False):
    shape = _create_text_shape(doc, page, services)
    shape.Size = _size(width, height)
    shape.Position = _point(x, y)
    shape.setString(text)
    try:
        shape.CharHeight = float(char_height)
    except Exception:
        pass
    # Presentation placeholders anchor their text in the middle of the box by
    # default, which would float a one-line heading into the body area.
    for name, value in (("TextAnchor", 0),        # com.sun.star.awt.TextAnchor.TOP
                        ("TextAnchorKind", 1)):   # ...drawing.TextAnchorKind.TOP
        try:
            shape.setPropertyValue(name, value)
        except Exception:
            pass
    if bold:
        try:
            shape.CharWeight = _FONT_BOLD
        except Exception:
            pass
    return shape


def _paint_paragraphs(shape, colors):
    """Set one character colour per paragraph (list shorter than the count is fine)."""
    try:
        enum = shape.createEnumeration()
    except Exception:
        return
    index = 0
    while enum.hasMoreElements():
        paragraph = enum.nextElement()
        color = colors[index] if index < len(colors) else colors[-1]
        try:
            paragraph.CharColor = int(color)
        except Exception:
            pass
        index += 1


def _clear_page(page):
    for i in range(page.Count - 1, -1, -1):
        try:
            page.remove(page.getByIndex(i))
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# the footer band
# --------------------------------------------------------------------------- #
#
# Impress keeps the bottom of a slide per *slide*, not per document: the
# ``com.sun.star.presentation.DrawPage`` service that every ``DrawPages`` entry
# supports carries the four ODF ``presentation:display-*`` switches as
# ``IsFooterVisible`` / ``IsDateTimeVisible`` / ``IsPageNumberVisible`` /
# ``IsDateTimeFixed``, plus ``FooterText``, ``DateTimeText`` and
# ``DateTimeFormat``.  Asking the *document* for them raises ``AttributeError``,
# and a page made by ``insertNewByIndex`` starts with all of them empty - which
# is why a generated slide showed no footer while every slide of the deck showed
# one.  ``dev/debug_footer_render.py`` exports the alternatives side by side.
#
# The properties are the whole story for a deck authored in Impress, because
# what draws the text is the master page's own footer placeholders (an empty
# footer shape added to the page draws nothing and hides nothing).  A deck
# written by something else keeps a footer frame on each slide instead, so those
# shapes are recreated as well.

#: the slide properties that make up the footer
FOOTER_PROPERTIES = ("IsFooterVisible", "IsDateTimeVisible", "IsPageNumberVisible",
                     "IsDateTimeFixed", "DateTimeFormat", "FooterText",
                     "DateTimeText")

#: the shapes of that band, matched on the tail of their ``ShapeType``
FOOTER_SHAPE_KINDS = ("HeaderShape", "DateTimeShape", "FooterShape", "SlideNumberShape")

#: character properties worth taking from one of those shapes
FOOTER_STYLE = ("CharHeight", "CharHeight Asian", "CharColor", "CharWeight",
                "CharFontName", "CharPosture", "CharUnderline", "TextAnchor",
                "TextAnchorKind", "ParaAdjust")


def _footer_kind(shape):
    """``'FooterShape'`` and friends for a shape of the bottom band, else None.

    ``supportsService`` does not work here: these shapes report the plain text
    services as well, and ``PresentationShapeType`` is not a property of them.
    """
    shape_type = str(getattr(shape, "ShapeType", ""))
    for kind in FOOTER_SHAPE_KINDS:
        if shape_type.endswith("." + kind):
            return kind
    return None


def _footer_shapes(page):
    """The footer-band shapes a page carries of its own."""
    out = []
    for i in range(page.Count):
        try:
            shape = page.getByIndex(i)
        except Exception:
            continue
        if _footer_kind(shape):
            out.append(shape)
    return out


def _footer_state(page):
    """The slide's footer settings, as far as this build exposes them."""
    state = {}
    for name in FOOTER_PROPERTIES:
        try:
            state[name] = getattr(page, name)
        except Exception:
            continue
    return state


def _footer_prints(state, shapes):
    """Would this footer show anything?

    ``IsFooterVisible`` on its own is not a footer: a slide whose footer is
    switched on but empty prints nothing, so copying it would buy nothing.
    """
    if str(state.get("FooterText") or "").strip():
        return True
    if str(state.get("DateTimeText") or "").strip():
        return True
    if state.get("IsDateTimeVisible") and not state.get("IsDateTimeFixed"):
        return True                                 # the date field prints today
    if state.get("IsPageNumberVisible"):
        return True
    return bool(shapes)


def footer_source(doc):
    """The slide the plan slides should take their footer from, or ``None``.

    The first slide of the deck - generated ones excluded - whose bottom band
    prints something.  ``None`` means the deck has no footer at all, and the plan
    slides must not grow one either.
    """
    pages = doc.DrawPages
    for i in range(pages.Count):
        page = pages.getByIndex(i)
        if _is_plan_page(page):
            continue
        if _footer_prints(_footer_state(page), _footer_shapes(page)):
            return page
    return None


#: the text field each kind of footer shape holds.  A footer shape read out of a
#: file holds a field whose *object* pyuno cannot get at - ``getPropertyValue
#: ("TextField")`` on the portion raises - so it is recreated from the service
#: the master's own field reports (``dev/debug_footer_switches.py`` lists them).
FOOTER_FIELD_SERVICES = {
    "HeaderShape": "com.sun.star.presentation.TextField.Header",
    "DateTimeShape": "com.sun.star.presentation.TextField.DateTime",
    "FooterShape": "com.sun.star.presentation.TextField.Footer",
    "SlideNumberShape": "com.sun.star.text.TextField.PageNumber",
}


def _insert_footer_field(doc, text, cursor, portion, kind):
    """Copy one field of a footer shape into ``text``; True when it worked.

    The field object is inserted as it stands when it can be read - the master's
    page-number field, inserted into another shape, then prints *that* shape's own
    page number, not the donor's (``dev/debug_footer_switches.py``).  When the
    portion will not hand it over, it is created from the service of the same kind
    instead (``dev/debug_footer_saved.py`` prints the services the loaded fields
    report): the shape it lands in is already the right thing for Impress to fill.
    """
    try:
        field = portion.getPropertyValue("TextField")
    except Exception:
        field = None
    if field is None:
        service = FOOTER_FIELD_SERVICES.get(kind)
        if service is None:
            return False
        try:
            field = doc.createInstance(service)
        except Exception:
            return False
    try:
        text.insertTextContent(cursor, field, False)
        return True
    except Exception:
        return False


def _copy_paragraphs(doc, source, target, kind=None):
    """Copy a footer shape's text, its *fields* included.

    The date and the page number of a footer are not characters but text fields:
    copying them as text would freeze whatever the donor happened to print, and
    ``getString()`` of such a portion does not even answer with that - it returns
    the placeholder stored in the file (``<footer>``, ``<number>``).  So the field
    itself travels (:func:`_insert_footer_field`) and only genuine text portions
    are copied as text, which is what a typed footer is.
    """
    text = target.getText()
    cursor = text.createTextCursor()
    cursor.gotoStart(False)
    cursor.gotoEnd(True)
    try:
        text.insertString(cursor, "", True)     # drop what the shape came with
    except Exception:
        pass
    cursor.gotoEnd(False)
    try:
        paragraphs = list(source.createEnumeration())
    except Exception:
        paragraphs = []
    for index, paragraph in enumerate(paragraphs):
        if index:
            text.insertString(cursor, "\n", False)
        try:
            portions = list(paragraph.createEnumeration())
        except Exception:
            continue
        for portion in portions:
            try:
                is_field = portion.getPropertyValue("TextPortionType") == "TextField"
            except Exception:
                is_field = False
            if is_field:
                # whatever happens, the text of a field portion is not copied: it
                # is the placeholder, not what the slide prints
                _insert_footer_field(doc, text, cursor, portion, kind)
                continue
            try:
                string = portion.getString()
            except Exception:
                string = ""
            if string:
                text.insertString(cursor, string, False)


def _copy_style(source, target):
    """Copy the character and anchoring properties a footer shape exposes."""
    for name in FOOTER_STYLE:
        try:
            value = source.getPropertyValue(name)
        except Exception:
            continue
        try:
            target.setPropertyValue(name, value)
        except Exception:
            pass


def _mirror_footer_shapes(doc, page, source_page):
    """Recreate the deck's own footer frames on ``page``; returns the kinds."""
    added = []
    for shape in _footer_shapes(source_page):
        kind = _footer_kind(shape)
        try:
            fresh = doc.createInstance(str(shape.ShapeType))
            page.add(fresh)
        except Exception:
            continue                        # a footer service this build lacks
        try:
            fresh.Position = shape.Position
            fresh.Size = shape.Size
        except Exception:
            pass
        _copy_style(shape, fresh)
        _copy_paragraphs(doc, shape, fresh, kind)
        added.append(kind)
    return added


def apply_footer(doc, page, source_page=None):
    """Give ``page`` the footer the rest of the deck has.

    ``source_page`` is the slide to copy from; ``footer_source(doc)`` when it is
    not given.  Returns what was set - the footer properties and the kinds of
    shape recreated - so callers and tests can see that it did something.
    """
    if source_page is None:
        source_page = footer_source(doc)
    if source_page is None or source_page is page:
        return {}
    done = {}
    for name, value in _footer_state(source_page).items():
        try:
            setattr(page, name, value)
            done[name] = value
        except Exception:
            pass
    done["shapes"] = _mirror_footer_shapes(doc, page, source_page)
    return done


def build_plan_slide(doc, page, section_names, current, settings, footer=None):
    """Fill ``page`` with the heading plus every section name.

    ``current`` is the index of the highlighted section, or ``None`` for the
    overview slide, where all names are drawn in the highlight colour.

    Position and size come from the master's own placeholders where they are
    usable, and the body is additionally sized so the whole list fits between
    the heading and the bottom of the slide.  ``footer`` is the slide to take the
    footer band from (see :func:`apply_footer`); it is looked up once per
    ``insert_plan`` and found here otherwise.
    """
    master = _master_page(doc, settings.get("master", ""))
    page.MasterPage = master
    _clear_page(page)
    apply_footer(doc, page, footer)

    if not section_names:
        raise PlanError("There are no sections to list.")

    width, height = page.Width, page.Height
    highlight = settings["text_color"]
    muted = settings["muted_color"]

    master_title = _title_shape(master)
    tx, ty, tw, th = _rect(master_title, (width * 0.08, height * 0.05),
                           (width * 0.84, height * 0.16), width, height)
    title_pt = _master_char_height(master_title, _TITLE_PT)
    _make_text_shape(doc, page, TITLE_SERVICES, settings.get("title") or "Plan",
                     tx, ty, tw, th, char_height=title_pt, bold=True)

    master_body = _body_shape(master)
    bx, by, bw, bh = _rect(master_body, (width * 0.10, height * 0.24),
                           (width * 0.80, height * 0.66), width, height)
    # the list has to start below the heading, whatever box the master suggests
    below_heading = ty + int(title_pt * _UNITS_PER_POINT * _LINE_SPACING)
    if by < below_heading:
        by = min(below_heading, int(height * 0.7))
        bh = max(int(height * 0.2), height - by - int(height * 0.05))
    body_pt = _fit_point_size(_master_char_height(master_body, _BODY_PT),
                              bh, len(section_names))
    body = _make_text_shape(doc, page, BODY_SERVICES, "\n".join(section_names),
                            bx, by, bw, bh, char_height=body_pt)
    if current is None:
        # the overview: nothing is "current", so nothing is dimmed
        colors = [highlight] * len(section_names)
    else:
        colors = [highlight if i == current else muted
                  for i in range(len(section_names))]
    _paint_paragraphs(body, colors)
    return page


# --------------------------------------------------------------------------- #
# the command
# --------------------------------------------------------------------------- #

def _check_sections(sections, expected, names):
    """Compare the section list the document kept with the one that was asked for.

    Assigning ``SlideSections`` cannot fail: a name that matches nothing is
    dropped, the remaining ranges simply stretch over the gap and the last
    section runs to the end of the deck, so a plan slide that ended up in the
    wrong section is invisible unless the list is read back.

    The comparison is lenient at the *end* of the last section on purpose: the
    API cannot express "this section stops here", so slides that belonged to no
    section get swallowed by it.  What has to hold is that a section starts with
    its own plan slide and still covers the slides it covered before.
    """
    if len(sections) != len(expected):
        raise PlanError(
            "LibreOffice kept %d of the %d sections while the plan slides were "
            "inserted.\n\nUndo and run Plan Impress again; if it keeps happening, "
            "check the sections in the slide panel (Slide > Insert Section)."
            % (len(sections), len(expected)))
    for position, pair in enumerate(zip(expected, sections)):
        want, got = pair
        have = got["indexes"]
        if have[:1] != want[:1] or [index for index in want if index not in have]:
            raise PlanError(
                "The plan slide of section '%s' did not land at the top of its "
                "section: it should cover slides %s, the document says %s."
                "\n\nUndo and run Plan Impress again."
                % (names[position],
                   ", ".join(str(index + 1) for index in want),
                   ", ".join(str(index + 1) for index in have) or "nothing"))


def insert_plan(doc, settings, ctx=None):
    """Insert the overview slide and one plan slide per section.

    Idempotent: previously generated plan slides are removed first, so running
    this twice yields the same document.  ``ctx`` is the component context used
    to run the move commands; in-process callers get the document's own.
    Returns a report dict.
    """
    if not hasattr(doc, "DrawPages"):
        raise PlanError("Open an Impress presentation first.")
    remove_plan_slides(doc)
    sections = get_sections(doc)
    if not sections:
        if doc.DrawPages.Count:
            raise PlanError(
                "This presentation has no sections.\n\n"
                "Select the slides of a group in the slide panel and choose "
                "Slide > Insert Section, then run Plan Impress again.")
        raise PlanError(
            "This presentation has no slides.\n\n"
            "Create slides, group them into sections (Slide > Insert Section), "
            "and run Plan Impress again.")

    names = [s["name"] or "(untitled)" for s in sections]
    for position, section in enumerate(sections):
        if section["start"] < 0:
            raise PlanError(
                "Section '%s' lists slides that are not in this presentation: %s."
                "\n\nSelect the slides of that group in the slide panel and "
                "choose Slide > Insert Section again, then run Plan Impress."
                % (names[position], ", ".join(section["slides"]) or "(none)"))

    # The generated slides belong to the deck, so they carry its footer.  Looked
    # up once, from the deck's own slides, before the generated ones exist.
    footer = footer_source(doc)

    # Insert bottom-up: adding a page shifts every index below it, so starting
    # from the last section keeps the still-pending targets valid.  Where every
    # slide ends up is then plain arithmetic - a page name is no help either,
    # LibreOffice renumbers those by position as soon as the deck changes.
    targets = [section["start"] for section in sections]
    inserted = 0
    for position in range(len(sections) - 1, -1, -1):
        insert_page_at(doc, targets[position], SECTION_NAME_TEMPLATE % position, ctx)
        inserted += 1

    # The overview sits above everything, i.e. before the plan slide of the
    # first section, which is at the first section's start index.
    overview_start = sections[0]["start"]
    insert_page_at(doc, overview_start, OVERVIEW_NAME, ctx)
    targets.append(overview_start)
    inserted += 1

    # Pages are named uniquely; re-read so the shapes go on the right pages.
    pages = doc.DrawPages
    by_name = {pages.getByIndex(i).Name: pages.getByIndex(i) for i in range(pages.Count)}
    build_plan_slide(doc, by_name[OVERVIEW_NAME], names, None, settings, footer)
    for position, section in enumerate(sections):
        page = by_name.get(SECTION_NAME_TEMPLATE % position)
        if page is None:
            raise PlanError("Internal error: plan slide for section '%s' is missing."
                            % names[position])
        build_plan_slide(doc, page, names, position, settings, footer)

    # Rewrite the sections so each plan slide leads its section.  The overview
    # deliberately stays outside of every section, and the ranges are the ones
    # the slides occupy now, not the ones they occupied before the insertions.
    rebuilt, expected = [], []
    for position, section in enumerate(sections):
        positions = _section_with_plan(section["indexes"][0],
                                       section["indexes"][-1], targets)
        rebuilt.append({"name": section["name"], "id": section.get("id"),
                        "slides": positions})
        expected.append(positions)
    final = set_sections(doc, rebuilt)
    _check_sections(final, expected, names)

    return {
        "sections": len(sections),
        "inserted": inserted,
        "overview": OVERVIEW_NAME,
        #: the slide the footer band was taken from, None when the deck has none
        "footer": str(footer.Name) if footer is not None else None,
        "slides": page_names(doc),
        "sections_after": final,
    }


def remove_plan(doc):
    """Remove the plan slides.  Returns how many were deleted."""
    return remove_plan_slides(doc)
