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
#: The plan slide of a section is named after the section's number *in the deck*,
#: so it counts from 1 like the slide numbers the user sees, not from 0 like the
#: Python list :func:`insert_plan` walks.
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


def _drop_pages(doc, sections):
    """Delete every slide this extension made and put ``sections`` back.

    Only used to undo a run that stopped half way, which otherwise leaves the deck
    with plan slides in it and the section ranges that described the deck *without*
    them: empty slides the audience has to skip, and sections that no longer match
    the slides - the report "inserting into the second deck leaves empty slides and
    loses sections".  Every plan slide in the deck came from the failed run, because
    :func:`insert_plan` deleted the older ones before it started; and it has to be
    every one of them, not just the ones that were reported inserted: the move
    commands fail *after* the page exists, which is precisely the case this undoes.
    After this the deck is as it was before the run started.
    """
    pages = doc.DrawPages
    doomed = [i for i in range(pages.Count) if _is_plan_page(pages.getByIndex(i))]
    for index in reversed(doomed):
        try:
            pages.remove(pages.getByIndex(index))
        except Exception:
            pass
    try:
        set_sections(doc, sections)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# slide content
# --------------------------------------------------------------------------- #

def _default_master(doc):
    """The master the deck's own slides use - the template's content look.

    ``MasterPages.getByIndex(0)`` is usually the *title* master, whose
    placeholders are laid out for a cover slide, so basing the plan slides on it
    produced a heading and a list that looked like nothing else in the deck.
    """
    counts = {}
    pages = doc.DrawPages
    for i in range(pages.Count):
        try:
            page = pages.getByIndex(i)
            if _is_plan_page(page):
                continue            # a previous run's slides are not the deck's own
            name = str(page.MasterPage.Name)
        except Exception:
            continue
        counts[name] = counts.get(name, 0) + 1
    masters = doc.MasterPages
    if counts:
        wanted = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for i in range(masters.Count):
            if masters.getByIndex(i).Name == wanted:
                return masters.getByIndex(i)
    return masters.getByIndex(0)


def _master_page(doc, wanted):
    """The master slide to base plan slides on: by name, else the deck's own.

    A name that this deck has no master for means "the deck's own", like the empty
    setting does.  It is *not* an error: the settings are stored **per profile**, so
    the master picked while working on one presentation is what every other
    presentation in this LibreOffice is asked for, and a deck without a master of
    that name is the normal case.  Refusing there is the report "Insert Plan Slides
    does nothing in the second deck until I open Settings" - Settings offered only
    the masters of the deck in front, so saving there is what made it work.
    """
    masters = doc.MasterPages
    if not masters.Count:
        raise PlanError("This presentation has no master slides.")
    if wanted:
        for i in range(masters.Count):
            if masters.getByIndex(i).Name == wanted:
                return masters.getByIndex(i)
    return _default_master(doc)


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


def _paragraphs_of(shape):
    """The paragraphs of a text shape, as a list."""
    if shape is None:
        return []
    try:
        return list(shape.createEnumeration())
    except Exception:
        return []


def _first_paragraph(shape):
    """The first paragraph of a text shape, or ``None``.

    A master's content placeholder keeps **one paragraph per outline level**, so its
    first paragraph is how the template paints level-1 text and the shape's own
    character properties are only the default underneath it - which is why the
    character properties have to be asked for twice, from both (see
    :func:`_make_text_shape`).
    """
    for paragraph in _paragraphs_of(shape):
        return paragraph
    return None


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


#: What the content placeholder of a master or layout answers to, best first.
#: ``CustomShape`` and plain ``TextShape`` are deliberately *not* in here: a
#: master drawn by a designer usually has a full-page background ``CustomShape``
#: that supports text, and picking that as "the content area" put the list at
#: the left edge of the slide in the template's small-text style.
CONTENT_SERVICES = (
    "com.sun.star.presentation.SubtitleTextShape",
    "com.sun.star.presentation.OutlinerShape",
)


def _is_content(shape):
    """True for the shape a master uses for the body text of its slides."""
    if _is_title(shape):
        return False
    for service in CONTENT_SERVICES:
        try:
            if shape.supportsService(service):
                return True
        except Exception:
            continue
    return False


def _body_shape(page):
    """The content placeholder of ``page``: the box the deck's own text goes in.

    The placeholder is asked, not measured - the biggest text shape on a master
    is usually its full-page background shape, which supports text and would win
    any size contest.  Only a master that uses no presentation placeholder at all
    falls back to the largest text shape.
    """
    shapes = _text_shapes(page)
    for shape in shapes:
        if _is_content(shape):
            return shape
    candidates = [s for s in shapes if not _is_title(s)]
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda s: s.Size.Width * s.Size.Height)
    except Exception:
        return candidates[0]


def _placeholder_key(shape):
    """What makes two placeholders "the same box, in the same look".

    The vote that picks which of the deck's own placeholders to copy groups on this:
    same rectangle and same characters, so a slide whose title was moved or resized
    apart from the rest of the deck is simply outvoted.
    """
    return (int(shape.Position.X), int(shape.Position.Y),
            int(shape.Size.Width), int(shape.Size.Height),
            round(float(getattr(shape, "CharHeight", 0) or 0), 2),
            str(getattr(shape, "CharFontName", "")),
            round(float(getattr(shape, "CharWeight", 0) or 0), 1))


def _deck_placeholder(doc, master, wanted):
    """The placeholder the deck's own slides use for ``wanted``; None if none do.

    A slide keeps the box and the characters it was given, so the slides of a real
    deck routinely disagree with the master page: the deck this was measured on
    titles its slides at ``y = 1474`` in **31 pt** while its master placeholder says
    ``y = 1500`` in **32 pt**, and its body text is 21 pt semi-bold where the master
    asks for 20 pt regular.  The audience sees the slides, so the slides are the
    template and the master is the fallback - what a deck with no slide of that
    master to compare with has to fall back on.

    The value the slides agree on wins: every placeholder of the kind is counted per
    rectangle-and-look and the most common one is used, so a single hand-edited
    slide - or a cover slide, which is usually the first and the most different -
    cannot move the generated slides somewhere else.
    """
    counted = {}
    pages = doc.DrawPages
    for i in range(pages.Count):
        try:
            page = pages.getByIndex(i)
            same_master = str(page.MasterPage.Name) == str(master.Name)
        except Exception:
            continue
        if not same_master or _is_plan_page(page):
            continue
        for shape in _text_shapes(page):
            try:
                if not wanted(shape):
                    continue
                key = _placeholder_key(shape)
            except Exception:
                continue
            if key not in counted:
                counted[key] = [1, shape]
            else:
                counted[key][0] += 1
    if not counted:
        return None
    return max(counted.values(), key=lambda entry: entry[0])[1]


def _style_source(doc, master):
    """The two shapes the generated slides copy their look from: ``(title, body)``.

    The deck's own slides first - see :func:`_deck_placeholder` - and the master's
    placeholders only where no slide has anything to copy.  Both can be ``None`` for
    a master that draws no placeholder of that kind, which is what the fallbacks in
    :func:`build_plan_slide` are for.
    """
    title = _deck_placeholder(doc, master, _is_title)
    if title is None:
        title = _title_shape(master)
    body = _deck_placeholder(doc, master, _is_content)
    if body is None:
        body = _body_shape(master)
    return title, body


def _text_anchor(shape):
    """How a placeholder anchors its text in its box: "top", "centre" or "bottom".

    Read back from the shape that was just built, so it is what the generated slide
    really does: the value comes from the template through :func:`_make_text_shape`,
    and only when the template said nothing at all does that function fall back to
    top anchoring.
    """
    try:
        value = str(getattr(shape.TextVerticalAdjust, "value", "")).lower()
    except Exception:
        return "top"
    if value in ("center", "middle", "centered"):
        return "centre"
    if value == "bottom":
        return "bottom"
    return "top"


def _heading_bottom(top, height, point_size, anchor):
    """The lowest point the heading paints, in 1/100 mm.

    The list has to start below that, and *painting* is not the bottom of the box:
    a presentation placeholder anchored in the middle puts its one line in the
    middle of the template's box, so a box twice as tall as the text leaves the text
    - and the list that has to clear it - in the middle of the box.  The default
    Impress template asks for that, which is how a plan slide came to have its list
    a few millimetres inside the heading.
    """
    line = int(point_size * _UNITS_PER_POINT * _LINE_SPACING)
    if anchor == "bottom":
        return top + height
    if anchor == "centre":
        return top + (height + line) // 2
    return top + line


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
    """The point size the template paints with, when it says something sane.

    The **first paragraph** wins over the shape: a master's content placeholder keeps
    one paragraph per outline level and the slides are drawn with that level, so the
    shape's own ``CharHeight`` is only the default underneath it.  Measured on a deck
    off the disk: its title placeholder answers 32 pt as a shape and 31 pt as a
    paragraph, and every title of the deck is drawn at 31 pt - taking the shape's
    value put a heading a point larger next to the deck's own.
    """
    for source in (_first_paragraph(shape), shape):
        value = getattr(source, "CharHeight", None) if source is not None else None
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if 6.0 < value < 100.0:
            return value
    return fallback


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


def _ensure_placeholder(doc, page, services, wanted):
    """The page's placeholder ``wanted``, created when the layout has none.

    ``page.Layout`` does not always bring the placeholders with it (measured on a
    freshly inserted page), so they are reused when they are there and created
    when they are not; creating one that the layout has already added would put
    two lists on the slide.
    """
    for shape in _text_shapes(page):
        try:
            if wanted(shape):
                return shape
        except Exception:
            continue
    return _create_text_shape(doc, page, services)


def _make_text_shape(doc, page, services, wanted, text, x, y, width, height,
                     char_height, bold=False, char_color=None, mirror=None):
    shape = _ensure_placeholder(doc, page, services, wanted)
    # before anything else: what the template says wins, and the properties set
    # below are the deliberate exceptions to it.  The characters come from the
    # template placeholder's *first paragraph* where it has one: that is the
    # outline level the template paints with, and it disagrees with the shape's own
    # values on a real master (31 pt Light against 32 pt Roman on the heading)
    mirror_text = _first_paragraph(mirror)
    if mirror_text is None:
        mirror_text = mirror
    copied = _mirror_characters(mirror, shape)
    shape.Size = _size(width, height)
    shape.Position = _point(x, y)
    shape.setString(text)
    # and the paragraphs of it: a paragraph of a new outline placeholder takes its
    # characters from the *page style's* outline level - bold 150 in the default
    # template - which overrides whatever the shape says, so the template's own
    # first paragraph has to be mirrored down to them as well
    for paragraph in _paragraphs_of(shape):
        _mirror_characters(mirror_text, paragraph, PARAGRAPH_ATTRIBUTES)
    try:
        shape.CharHeight = float(char_height)
    except Exception:
        pass
    if char_color is not None:
        # the base colour of everything in the box, including the list numbers
        try:
            shape.CharColor = int(char_color)
        except Exception:
            pass
    # A shape with nothing to inherit from has to be told: presentation
    # placeholders anchor their text in the middle of the box, which would float a
    # one-line heading into the body area.  When the master's placeholder carried
    # its own anchoring, that is the template's and is left alone.
    if "TextVerticalAdjust" not in copied:
        for name, value in (("TextAnchor", 0),      # com.sun.star.awt.TextAnchor.TOP
                            ("TextAnchorKind", 1)):  # ...drawing.TextAnchorKind.TOP
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


def section_page_name(index):
    """The name of the plan slide that belongs to section ``index`` (from 0)."""
    return SECTION_NAME_TEMPLATE % (index + 1)


def _numbering_rules(shape):
    """The list style of a master placeholder, or ``None`` when it has none."""
    if shape is None:
        return None
    try:
        return shape.NumberingRules
    except Exception:
        return None


def _level_value(rules, name, default=None):
    """One property of the first list level, or ``default``."""
    if rules is None:
        return default
    try:
        for entry in rules.getByIndex(0):
            if entry.Name == name:
                return entry.Value
    except Exception:
        pass
    return default


def _numbering_constant(name, fallback):
    """One ``com.sun.star.style.NumberingType`` constant as the integer it is.

    The numbers are worth nothing to read (``ARABIC`` is 4, ``CHARS_LOWER_LETTER``
    1, ``CHAR_SPECIAL`` 6, ``NUMBER_NONE`` 5 - and ``CHARS_UPPER_LETTER`` 0, which
    nevertheless paints no label at all), the constants are only loaded inside the
    office, and a value pyuno marshals from a *string* arrives as 0, so every
    caller takes them from the constants where they are there and from the
    measured integer otherwise.
    """
    try:
        from com.sun.star.style import NumberingType
        return int(getattr(NumberingType, name))
    except Exception:
        return fallback


def _numbering_type_arabic():
    """``NumberingType.ARABIC``, taken from the constants when they are loaded.

    The value is 4 in this LibreOffice (``dir(NumberingType)`` lists it); 1 is
    ``CHARS_LOWER_LETTER``, which is what the list rendered the first time the
    label was guessed at.  It has to be an ``int``: a string is stored as 0,
    which draws no number at all and leaves only the literal prefix behind.
    """
    return _numbering_constant("ARABIC", 4)


#: Character *and* text-box attributes copied from the master's placeholder onto
#: the shape this extension adds.  A shape made with ``createInstance()`` gets the
#: page style's characters and its own text-box settings instead: the heading came
#: out in the master's cover title font, at a point size of its own, vertically
#: centred in a box that auto-grew - which is what made a generated slide look
#: re-created rather than edited (``dev/debug_numbering.py``, variant "no mirror").
CHAR_ATTRIBUTES = ("CharFontName", "CharStyleName", "CharHeight", "CharWeight",
                   "CharPosture", "CharKerning", "CharCaseMap", "CharColor",
                   "CharUnderline", "CharStrikeout", "CharRelief", "CharShadowed",
                   "ParaAdjust", "ParaLeftMargin", "ParaRightMargin",
                   "ParaFirstLineIndent", "ParaTopMargin", "ParaBottomMargin",
                   "ParaLineSpacing", "TextAutoGrowHeight", "TextAutoGrowWidth",
                   "TextContourFrame", "TextVerticalAdjust", "TextLeftDistance",
                   "TextRightDistance")


#: The part of ``CHAR_ATTRIBUTES`` that belongs on a *paragraph* (``CharStyleName``
#: is a shape property, a paragraph has ``CharFontStyleName`` instead).
#: ``CharHeight`` and ``CharColor`` are deliberately left out: the point size is the
#: one the list was fitted to and the colour is what tells the current section from
#: the others.
PARAGRAPH_ATTRIBUTES = ("CharFontName", "CharWeight", "CharPosture",
                        "CharKerning", "CharCaseMap", "CharUnderline",
                        "CharStrikeout", "CharRelief", "CharShadowed")


def _mirror_characters(source, target, names=CHAR_ATTRIBUTES):
    """Copy the template's character look onto one of our shapes.

    Returns the names that actually came over; the caller does not have to guess
    about a property the master never answered for.
    """
    copied = set()
    if source is None or target is None:
        return copied
    for name in names:
        try:
            value = source.getPropertyValue(name)
        except Exception:
            continue
        try:
            target.setPropertyValue(name, value)
            copied.add(name)
        except Exception:
            pass
    return copied


def _copy_numbering(doc, template_rules):
    """A rules object carrying the master's list style (all ten levels)."""
    rules = doc.createInstance("com.sun.star.text.NumberingRules")
    if template_rules is not None:
        try:
            for index in range(min(rules.Count, template_rules.Count)):
                rules.replaceByIndex(index, uno.Any(
                    "[]%s" % _PROPERTY_VALUE,
                    tuple(list(template_rules.getByIndex(index)))))
        except Exception:
            pass
    return rules


def _patch_level(rules, overrides):
    """Change single properties of the first level; everything else is kept.

    The level has to go back as one typed sequence (a plain tuple is refused),
    and only the properties named in ``overrides`` are touched, so what the
    template says about the bullet font, its size and the indentation survives.
    """
    level = list(rules.getByIndex(0))
    seen = set()
    for entry in level:
        if entry.Name in overrides:
            entry.Value = overrides[entry.Name]
            seen.add(entry.Name)
    for name in sorted(overrides):
        if name not in seen:
            entry = uno.createUnoStruct(_PROPERTY_VALUE)
            entry.Name, entry.Value = name, overrides[name]
            level.append(entry)
    rules.replaceByIndex(0, uno.Any("[]%s" % _PROPERTY_VALUE, tuple(level)))
    return rules


#: ``NumberingType`` values whose label is a *character* the template chose
#: (``CHAR_SPECIAL`` and ``BITMAP``).  Their ``BulletRelSize`` sizes that glyph.
CHARACTER_LABELS = (6, 8)


def _uncounted_labels():
    """The label styles a plan list cannot copy, because they do not count.

    ``CHAR_SPECIAL`` and ``BITMAP`` draw the glyph the template picked - a bullet
    says nothing about which of seven sections the audience is in - ``PAGE_DESCRIPTOR``
    prints the *slide's* number on every row, ``NUMBER_NONE`` draws no label and 0
    paints nothing although the constants call it ``CHARS_UPPER_LETTER``.
    """
    return tuple(CHARACTER_LABELS) + (
        0,
        _numbering_constant("NUMBER_NONE", 5),
        _numbering_constant("PAGE_DESCRIPTOR", 7))


def _counts_labels(value):
    """True when a ``NumberingType`` counts (digits, roman, letters) rather than
    drawing a glyph or nothing (see :func:`_uncounted_labels`)."""
    try:
        return int(value) not in _uncounted_labels()
    except (TypeError, ValueError):
        return False


def _list_label_type(rules):
    """How one list level labels its rows: ``(NumberingType, substituted)``.

    The level's own style wins wherever it counts, so a deck whose outline says
    ``I. II. III.`` numbers its plan rows with roman numerals and one that says
    ``a) b) c)`` with letters: the label is the one thing on the slide the deck
    already has a style for, and digits next to a deck's own roman list is what made
    the slide look re-created.  ``(ARABIC, True)`` comes back when the level draws a
    bullet or nothing at all - a digit then has to be invented, and the two properties
    that size and place *a glyph* have to be re-asked for, because they were tuned for
    a small decorative character and not for a number (see :func:`_number_list`).
    """
    wanted = _level_value(rules, "NumberingType")
    if _counts_labels(wanted):
        return int(wanted), False
    return _numbering_type_arabic(), True


def _label_sources(doc, master, body):
    """The placeholders whose first level says how the deck numbers its items.

    A content placeholder is not where a template keeps its numbering format: the deck
    this was measured on draws an OpenSymbol arrow (``CHAR_SPECIAL``) in its content
    placeholder while its **title** placeholder counts ``I. II. III.`` - so copying the
    content level alone put arabic digits on a deck that does not use them anywhere.
    The deck's own slides are asked before the master page, as always.
    """
    out = []
    for shape in (_deck_placeholder(doc, master, _is_content),
                  _deck_placeholder(doc, master, _is_title),
                  _body_shape(master), _title_shape(master)):
        if shape is not None:
            out.append(shape)
    return out


def _template_label(doc, master, body):
    """The label style of the plan list: ``(NumberingType, overrides, substituted)``.

    First the level the list is drawn with, if it counts; then the first level of the
    deck's own placeholders that does count (:func:`_label_sources`) - taking its
    ``Prefix`` and ``Suffix`` with it, because the literal text around the number is as
    much the deck's format as the numerals are; and only when nothing in the deck
    counts at all, plain digits.  ``substituted`` says a digit was invented for a
    glyph, which is when :func:`_number_list` corrects the size and the column of the
    label.
    """
    label, substituted = _list_label_type(_numbering_rules(body))
    if not substituted:
        return label, {}, substituted
    for shape in _label_sources(doc, master, body):
        rules = _numbering_rules(shape)
        wanted = _level_value(rules, "NumberingType")
        if _counts_labels(wanted):
            return int(wanted), {
                "Prefix": _level_value(rules, "Prefix", ""),
                "Suffix": _level_value(rules, "Suffix", ""),
            }, True
    return _numbering_type_arabic(), {}, True


def _number_list(doc, shape, template_rules=None, bullet_colors=None, label=None,
                 label_overrides=None, substituted=None):
    """Draw the paragraphs of ``shape`` as the master's first list level.

    The master's own level is copied and only the label is replaced - with the style
    the deck counts with (:func:`_template_label`), or with digits where nothing in the
    deck counts at all - so the number comes in the template's bullet font, with its
    indentation, its ``Prefix``/``Suffix``, its tab stops and its label colour:
    measured in ``dev/debug_numbering.py``, a rules object built from scratch gave the
    digits a font, a size, a gap and a colour of their own, which is what made the list
    look foreign on the slide.  Three things about these rules are measured there
    as well: ``NumberingType`` has to be an **integer** (a value pyuno marshals from
    a string arrives as 0, i.e. no number at all, and ``1`` is
    ``CHARS_LOWER_LETTER``, which is the "a. b. c." the first attempt rendered), a
    level is written back as one typed sequence, and ``Prefix`` is literal text
    (asking for ``"%1."`` prints ``%1.``).

    The properties that cannot be inherited are the ones describing a *glyph* the
    template drew and we replaced: such a level sizes that character (the fixture's
    master asks for 45 % of the text height, which makes an unreadable digit) and
    pulls it into the margin with a ``FirstLineOffset`` tuned for it, which leaves a
    digit glued to the text ("1Introduction", ``dev/debug_numbering.py``).  The size
    is re-asked for - never smaller than the text it numbers - and the label is given
    a column of its own at the level's ``LeftMargin``.  Neither is touched when the
    template's own label is kept: then its size and its column are the target.  That
    column has to be asked for on the *paragraph*: two slides whose level read
    exactly the same (``LeftMargin`` 1200, ``FirstLineOffset`` -1200) rendered with
    and without a gap, and what separated them was the paragraph's
    ``ParaLeftMargin`` / ``ParaFirstLineIndent`` - the level's margins alone are only
    what the template's own bullets need.  ``SymbolTextDistance`` cannot be used for
    the gap either: writes to it are ignored, it mirrors ``FirstLineOffset``.

    ``bullet_colors`` optionally gives one colour per paragraph.  The label is
    painted with the level's ``BulletColor`` - which the template sets to its own
    accent colour, so one copy of the rules per paragraph differing in that one
    property is what dims the numbers of the sections that are not the current
    one.  Different rules objects per paragraph do not restart the count: the
    list still runs 1, 2, 3 (``dev/debug_numbering.py``).

    Returns whether the label could be installed; without it the list is still
    readable, just unnumbered.
    """
    if label is None:
        label, label_overrides, substituted = _list_label_type(template_rules), {}, True
    if substituted is None:
        substituted = True
    overrides = dict(label_overrides or {})
    overrides["NumberingType"] = int(label)
    try:
        left = int(_level_value(template_rules, "LeftMargin", 0))
        offset = int(_level_value(template_rules, "FirstLineOffset", 0))
    except (TypeError, ValueError):
        left = offset = 0
    if substituted:
        # the relative size describes the character the template draws, and the
        # 45 % of the text height that makes a small dot makes an unreadable
        # digit: a number is text, so it is never smaller than the text it numbers
        inherited = _level_value(template_rules, "BulletRelSize", 100)
        try:
            overrides["BulletRelSize"] = max(int(inherited), 100)
        except (TypeError, ValueError):
            pass
        # and the negative first-line offset that pulls that character into the
        # margin leaves a digit glued to the text, so the label goes to the left
        # edge of the block instead and the text keeps its indent
        if left > 0 and offset > -left:
            overrides["FirstLineOffset"] = -left
            offset = -left
    try:
        shape.NumberingRules = _patch_level(_copy_numbering(doc, template_rules),
                                            overrides)
    except Exception:
        return False
    paragraphs = _paragraphs_of(shape)
    if not paragraphs:
        return False
    if bullet_colors:
        for index, paragraph in enumerate(paragraphs):
            color = bullet_colors[index] if index < len(bullet_colors) \
                else bullet_colors[-1]
            if color is None:
                continue
            try:
                copy = _copy_numbering(doc, template_rules)
                _patch_level(copy, dict(overrides, BulletColor=int(color)))
                paragraph.NumberingRules = copy
            except Exception:
                pass
    numbered = 0
    for paragraph in paragraphs:
        # The label's column has to be asked for on the paragraph as well: two
        # slides whose level read identically (LeftMargin 1200, FirstLineOffset
        # -1200) rendered with and without a gap between the number and the text,
        # and what separated them was the paragraph's own ParaLeftMargin /
        # ParaFirstLineIndent (the "core" and "core, no paragraph indent" slides of
        # dev/debug_numbering.py).  The level's margins alone are what the
        # template's own bullets need, not what a digit needs.
        try:
            if left > 0:
                if int(paragraph.ParaLeftMargin or 0) < left:
                    paragraph.ParaLeftMargin = left
                if int(paragraph.ParaFirstLineIndent or 0) > -left:
                    paragraph.ParaFirstLineIndent = -left
        except Exception:
            pass
        try:
            paragraph.NumberingLevel = 0
            paragraph.NumberingIsNumber = True
            numbered += 1
        except Exception:
            pass
    return numbered > 0


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


#: ``com.sun.star.presentation.PageLayout.OutlineText``: the title-plus-content
#: layout, i.e. the one whose boxes the master slide actually styles.
_LAYOUT_OUTLINE = 2


def build_plan_slide(doc, page, section_names, current, settings, footer=None,
                     master=None):
    """Fill ``page`` with the heading plus every section name.

    ``current`` is the index of the highlighted section, or ``None`` for the
    overview slide, where all names are drawn in the highlight colour.

    The heading and the list go into the master's own placeholders, so they get
    the template's position, font, colour and list indentation: the layout is
    chosen *before* the shapes exist, the rectangles come from the template where
    they fit on the page, and the point size is the one the template paints with
    (shrunk only when the list would not fit under the heading).  Overview and
    plan slides run through this one function with the same section list, which
    is what keeps their size and colours equal; what differs is only which
    paragraph is highlighted.

    ``footer`` is the slide to take the footer band from (see
    :func:`apply_footer`), and ``master`` the master to put the slide on: both are
    looked up once per :func:`insert_plan` and passed down, so a run cannot fail on
    one of them after the deck has already been changed.  Found here otherwise.
    """
    if master is None:
        master = _master_page(doc, settings.get("master", ""))
    page.MasterPage = master
    _clear_page(page)
    # before adding anything: afterwards the page keeps the rectangles it already
    # gave the shapes and stays on its old layout (measured: still 20)
    try:
        page.Layout = _LAYOUT_OUTLINE
    except Exception:
        pass
    apply_footer(doc, page, footer)

    if not section_names:
        raise PlanError("There are no sections to list.")

    width, height = page.Width, page.Height
    highlight = settings["text_color"]
    muted = settings["muted_color"]

    # what the deck's own slides are drawn in, with the master page underneath as
    # the fallback - the two disagree on decks authored in Impress
    template_title, template_body = _style_source(doc, master)

    tx, ty, tw, th = _rect(template_title, (width * 0.08, height * 0.05),
                           (width * 0.84, height * 0.16), width, height)
    title_pt = _master_char_height(template_title, _TITLE_PT)
    title = _make_text_shape(doc, page, TITLE_SERVICES, _is_title,
                             settings.get("title") or "Plan",
                             tx, ty, tw, th, char_height=title_pt,
                             bold=template_title is None, mirror=template_title)

    bx, by, bw, bh = _rect(template_body, (width * 0.10, height * 0.24),
                           (width * 0.80, height * 0.66), width, height)
    # the list has to start below the text of the heading, whatever box the
    # template suggests - and where that text is depends on how the box anchors it
    below_heading = _heading_bottom(ty, th, title_pt, _text_anchor(title))
    if by < below_heading:
        by = min(below_heading, int(height * 0.7))
        bh = max(int(height * 0.2), height - by - int(height * 0.05))
    body_pt = _fit_point_size(_master_char_height(template_body, _BODY_PT),
                              bh, len(section_names))
    body = _make_text_shape(doc, page, BODY_SERVICES, _is_content,
                            "\n".join(section_names), bx, by, bw, bh,
                            char_height=body_pt, char_color=highlight,
                            mirror=template_body)

    if current is None:
        # the overview: nothing is "current", so nothing is dimmed
        colors = [highlight] * len(section_names)
    else:
        colors = [highlight if i == current else muted
                  for i in range(len(section_names))]
    # the number is painted with the level's BulletColor, so a dimmed section has
    # to dim its number separately; the current one keeps the colour the template
    # chose for its bullets (and a template that fixes none follows the text)
    rules = _numbering_rules(template_body)
    template_bullet = _level_value(rules, "BulletColor")
    try:
        template_bullet = int(template_bullet)
    except (TypeError, ValueError):
        template_bullet = -1
    if template_bullet < 0:
        template_bullet = highlight
    bullets = [template_bullet if color == highlight else muted
               for color in colors]
    # the deck's own first list level, with the label style the deck counts in
    # (roman where it counts roman) and one colour per row
    label, label_overrides, substituted = _template_label(doc, master, template_body)
    _number_list(doc, body, rules, bullets, label, label_overrides, substituted)
    # last: the paragraph colour is what the text is drawn in, and with a level
    # that fixes no bullet colour it is what the number follows as well
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

    The run is all-or-nothing.  Everything that can refuse is settled *before* the
    deck is changed, and a failure after that takes the inserted pages out again and
    writes the section list back the way it was: a deck left half-inserted has empty
    slides in it and sections that no longer match its slides, and the next run then
    has to clean up a wreck instead of a deck (``dev/debug_two_documents.py`` showed
    both, including three sections coming back as one).

    Returns a report dict.
    """
    if not hasattr(doc, "DrawPages"):
        raise PlanError("Open an Impress presentation first.")

    # The master is the one thing the settings say about the deck that may not exist
    # in it - the settings are per profile, so its name usually comes from another
    # presentation - and it used to be resolved once per generated slide, i.e. only
    # after the pages had been inserted.  Once, up front, and passed down.
    master = _master_page(doc, settings.get("master", ""))

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
    # ... and so is the state to go back to if anything below still fails.
    try:
        restored = get_sections(doc)
    except Exception:
        restored = []

    inserted = 0
    try:
        # Insert bottom-up: adding a page shifts every index below it, so starting
        # from the last section keeps the still-pending targets valid.  Where every
        # slide ends up is then plain arithmetic - a page name is no help either,
        # LibreOffice renumbers those by position as soon as the deck changes.
        targets = [section["start"] for section in sections]
        for position in range(len(sections) - 1, -1, -1):
            insert_page_at(doc, targets[position], section_page_name(position), ctx)
            inserted += 1

        # The overview sits above everything, i.e. before the plan slide of the
        # first section, which is at the first section's start index.
        overview_start = sections[0]["start"]
        insert_page_at(doc, overview_start, OVERVIEW_NAME, ctx)
        targets.append(overview_start)
        inserted += 1

        # Pages are named uniquely; re-read so the shapes go on the right pages.
        pages = doc.DrawPages
        by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                   for i in range(pages.Count)}
        build_plan_slide(doc, by_name[OVERVIEW_NAME], names, None, settings,
                         footer, master)
        for position, section in enumerate(sections):
            page = by_name.get(section_page_name(position))
            if page is None:
                raise PlanError("Internal error: plan slide for section '%s' is "
                                "missing." % names[position])
            build_plan_slide(doc, page, names, position, settings, footer, master)

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
    except Exception:
        _drop_pages(doc, restored)
        raise

    asked = str(settings.get("master") or "")
    return {
        "sections": len(sections),
        "inserted": inserted,
        "overview": OVERVIEW_NAME,
        #: the slide the footer band was taken from, None when the deck has none
        "footer": str(footer.Name) if footer is not None else None,
        #: the master the plan slides went on, and whether the settings named one
        #: this deck has (they are per profile, so it usually names another deck's)
        "master": str(master.Name),
        "master_named": bool(asked) and str(master.Name) == asked,
        "slides": page_names(doc),
        "sections_after": final,
    }


def remove_plan(doc):
    """Remove the plan slides.  Returns how many were deleted."""
    return remove_plan_slides(doc)


# --------------------------------------------------------------------------- #
# the section-name box
# --------------------------------------------------------------------------- #
#
# ``*Section Titles*`` writes the name of a slide's section into a text box on that
# slide.  The box is drawn on a slide the *user* made, so two things matter:
#
# * it has to be recognisable afterwards, because the command is meant to be run
#   again after the sections are renamed, moved or - the case that really happens -
#   after a slide has been duplicated, and a re-run updates the boxes it made rather
#   than painting another one over them; and
# * nothing else on the slide may be touched, and nothing may be invented: the deck's
#   own slides are the template (fact 54) and the box is given the deck's look.
#
# Recognition is by the shape's **name**, and by prefix only.  A duplicated slide
# brings a copy of every shape it had, name included, so the box on the copy is found
# by the same prefix - which is the behaviour the test
# ``section_titles_survive_a_duplicated_slide`` pins: add the boxes, duplicate a
# slide, run again, and the copy says the name of the section it now belongs to
# instead of keeping the one it was copied with.  The page position is part of the
# name (``...Slide:4``) so a log or a macro can point at one box, but it is never
# *compared*: positions move, the prefix does not.

#: Every box this command draws starts its name with this.
SECTION_TEXT_PREFIX = PLAN_PREFIX + "SectionText:Slide:"

#: A box is a plain ``com.sun.star.drawing.TextShape``: a presentation placeholder
#: would be re-dealt by the layout and snapped back to the master (facts 21 and 53),
#: and this box belongs where the user - or these settings - put it.
SECTION_BOX_SERVICE = "com.sun.star.drawing.TextShape"

#: The character properties the box copies from the deck's own body text, and the
#: three the settings are allowed to overrule.
SECTION_BOX_ATTRIBUTES = ("CharFontName", "CharFamily", "CharStyleName",
                          "CharHeight", "CharWeight", "CharPosture", "CharColor")

#: Air between the box and whatever is above it, and under the first row of the
#: content placeholder, in 1/100 mm: two millimetres.
_SECTION_GAP = 200
#: How far from the top of the slide a box may be pushed at most when the deck's own
#: content starts that high: 1/100 mm.
_SECTION_MIN_Y = 200


def section_text_name(index):
    """The name a section box carries: ``PlanImpress:SectionText:Slide:4``.

    ``index`` is the page position, and the name counts from 1 like the slide numbers
    on the screen.  It is what a macro or a log line points at; the code recognises a
    box by :data:`SECTION_TEXT_PREFIX` alone, because the position moves.
    """
    return "%s%d" % (SECTION_TEXT_PREFIX, int(index) + 1)


def _is_section_box(shape):
    """True for a box this command drew: its name says so, and nothing else does."""
    try:
        return str(shape.Name).startswith(SECTION_TEXT_PREFIX)
    except Exception:
        return False


def section_text_shapes(page):
    """Every section box on ``page``, in the order the slide keeps them.

    More than one is possible - a slide duplicated from a slide whose box was copied
    by hand, or two runs before this recognised the copy - and they all get the same
    text, because a slide has one section and they are stacked on the same rectangle.
    """
    out = []
    try:
        count = page.Count
    except Exception:
        return out
    for i in range(count):
        try:
            shape = page.getByIndex(i)
        except Exception:
            continue
        if _is_section_box(shape):
            out.append(shape)
    return out


def section_of(sections, index):
    """The name of the section page ``index`` belongs to, or ``None``.

    What the section list *means* is a contiguous range of positions (fact 12), so a
    slide belongs to the last section that starts at or before it - and to none at all
    before the first section starts, which is the "except the firsts (without
    section)" of the request: a title slide that leads the deck stays untouched.
    """
    named = [entry for entry in (sections or [])
             if entry.get("indexes") and entry.get("start", -1) >= 0]
    if not named:
        return None
    named.sort(key=lambda entry: entry["start"])
    if index < named[0]["start"]:
        return None
    name = None
    for entry in named:
        if entry["start"] <= index:
            name = entry["name"]
    return name


def _section_shapes(doc, master):
    """The two shapes the box copies its look from: the deck's body and its title."""
    title, body = _style_source(doc, master)
    return body if body is not None else title


def _portions_of(paragraph):
    """The text portions of a paragraph; ``[]`` when it will not enumerate."""
    try:
        return list(paragraph.createEnumeration())
    except Exception:
        return []


def _look_sources(shape):
    """What ``shape``'s characters may be asked of, **deepest level first**.

    A text shape paints with the properties of its **text portion**: what the user
    changes in the sidebar, the toolbar or with ``Ctrl+`` is written onto the portion,
    while the paragraph keeps the values the last run gave it and the shape only the
    default underneath (fact 52 and 55 are the same ladder seen from the top).  That is
    why copying the first box copied its rectangle - geometry really does live on the
    shape - and not the characters: asked at shape or paragraph level, a box the user
    made 28 pt bold red still answered what the run that created it had written.
    ``dev/debug_section_titles.py`` prints the three levels side by side.
    """
    sources = []
    paragraph = _first_paragraph(shape)
    if paragraph is not None:
        sources.extend(_portions_of(paragraph)[:1])
        sources.append(paragraph)
    if shape is not None:
        sources.append(shape)
    return sources


def _read_look(shape):
    """The character properties ``shape`` paints with.

    Asked of the deepest level that answers, because that is the level that paints:
    see :func:`_look_sources`.  An attribute nothing will answer is simply absent, so a
    caller can tell "the shape does not have it" from "it says 0".
    """
    sources = _look_sources(shape)
    look = {}
    for name in SECTION_BOX_ATTRIBUTES:
        for source in sources:
            try:
                value = source.getPropertyValue(name)
            except Exception:
                continue
            if value is None:
                continue
            look[name] = value
            break
    return look


def _heading_top(shape, point_size):
    """The highest point a heading paints, or ``None`` when it will not say.

    The counterpart of :func:`_heading_bottom`, and needed for the same reason:
    text is anchored in the *middle* of a presentation placeholder's box, so the
    top of the box is not where the letters are (fact 56).  Putting the section
    label at the top of the title's box rather than above its letters is what made
    it print through the slide's own heading.
    """
    if shape is None:
        return None
    try:
        top = int(shape.Position.Y)
        height = int(shape.Size.Height)
    except Exception:
        return None
    line = int(point_size * _UNITS_PER_POINT * _LINE_SPACING)
    anchor = _text_anchor(shape)
    if anchor == "bottom":
        return max(top, top + height - line)
    if anchor == "centre":
        return max(top, top + (height - line) // 2)
    return top


def _section_box_rect(doc, master, settings, point_size):
    """``(x, y, width, height)`` for a box, in 1/100 mm.

    The left margin and the width come from the deck's own content placeholder -
    that is the "top-left of the slide, at the deck's own content margin" the box
    is meant to sit at - and the settings overrule any of the three that says a
    number.  The height is one line of the text plus the air, because the box is
    one line long by construction.

    Vertically it goes **above the heading the slide already has**, because a
    section name is the running head of the slide.  Measured with
    ``pdftotext -bbox`` on the fixture (`dev/render_section_titles.py` prints it):
    the heading paints from 2282 to 4015 while a box put between the heading and
    the content paints from 1988 to 3249 - the two bands overlap, and only the
    fixture's *centred* heading kept them from landing on each other's glyphs.
    Below the heading is the fallback for a deck whose heading already starts at
    the top of the slide.
    """
    height = int(round(point_size * _UNITS_PER_POINT * _LINE_SPACING)) + 100
    title, body = _style_source(doc, master)
    if body is None:
        body = title                          # a template with one placeholder only
    x = width = y = None
    if body is not None:
        try:
            x = int(body.Position.X)
            width = int(body.Size.Width)
        except Exception:
            x = width = None
        head_point = _master_char_height(title, _TITLE_PT) if title is not None \
            else _TITLE_PT
        above = _heading_top(title, head_point)
        below = _heading_bottom(
            int(title.Position.Y), int(title.Size.Height), head_point,
            _text_anchor(title)) if title is not None else None
        if above is not None and above - height - _SECTION_GAP >= _SECTION_MIN_Y:
            y = above - height - _SECTION_GAP     # the running head, above the title
        elif below is not None:
            y = below + _SECTION_GAP              # no room: under the heading
        else:
            try:
                y = int(body.Position.Y) - height - _SECTION_GAP
            except Exception:
                y = None
    if x is None:                             # a master with nothing to copy
        # the page's own size is ``page.Width``/``page.Height`` - a DrawPage has no
        # ``Size`` property, unlike the shapes on it
        try:
            page_width = int(doc.DrawPages.getByIndex(0).Width)
            x, width = int(page_width * 0.05), int(page_width * 0.9)
        except Exception:
            x, width = 2000, 21400
        y = _SECTION_MIN_Y
    settings_values = ((settings.get("section_x"), "x"),
                       (settings.get("section_y"), "y"),
                       (settings.get("section_width"), "width"))
    for value, which in settings_values:
        length = config_length(value)
        if length is None:
            continue
        if which == "x":
            x = length
        elif which == "y":
            y = length
        else:
            width = length
    return x, max(_SECTION_MIN_Y, int(y)), int(width), height


def config_length(value):
    """A length from the settings as an int, or ``None`` for "ask the deck".

    Lives here rather than in :mod:`plan_impress.config` because :mod:`core` must not
    import the UI half but may read what it was handed; ``config.load`` sanitises the
    same values on the way in, and this is the belt for a caller that built the
    dictionary itself.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        length = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None


def _apply_look(target, look):
    """Write character properties onto one target; what it refuses is skipped.

    Paragraphs have no ``CharStyleName`` and a shape may refuse a family name, so
    refusing is the normal case here and not an error (fact 52 is the same rule read
    the other way round: the properties have to be written on the shape *and* on the
    paragraphs, because a paragraph of a text shape takes its characters from the
    page style's outline level and overrides the shape).
    """
    for attribute, value in sorted(look.items()):
        if value is None:
            continue
        try:
            target.setPropertyValue(attribute, value)
        except Exception:
            continue


def _paint_section_box(shape, name, look, rect):
    """One box: its look, its text, its place.  Everything the command writes."""
    x, y, width, height = rect
    # the look goes on the shape *before* the text: the paragraph ``setString``
    # creates inherits from the shape, and after it as well, because a paragraph of a
    # text shape may take its characters from the page style instead (fact 52)
    _draw_flat(shape)                     # never on a plate, every run (fact 88)
    _apply_look(shape, look)
    shape.setString(str(name))
    for paragraph in _paragraphs_of(shape):
        _apply_look(paragraph, look)
        # and onto the portions: they are what paints (fact 52's ladder, bottom rung),
        # so a box that was styled by hand - or duplicated from one that was - would
        # otherwise keep its own size, weight and colour under a shape and a paragraph
        # that both say something else
        for portion in _portions_of(paragraph):
            _apply_look(portion, look)
    # measured once, on a box of a slide whose neighbour had just been duplicated:
    # the paragraph enumeration answered nothing at all, in which case the shape is
    # the only thing that can still be told - ask it again after the text is in
    if not _paragraphs_of(shape):
        _apply_look(shape, look)
    try:
        shape.Size = _size(width, height)
        shape.Position = _point(x, y)
    except Exception:
        pass
    for attribute, value in (("TextAutoGrowHeight", False),
                             ("TextAutoGrowWidth", False),
                             ("TextWordWrap", True),
                             ("TextAnchor", 0),        # awt TOP, fact 22
                             ("TextAnchorKind", 1)):   # drawing TOP
        try:
            shape.setPropertyValue(attribute, value)
        except Exception:
            pass
    return shape


#: What has to be switched off for the label to be painted over the slide instead of
#: on a plate.  Measured on a clean office: a ``TextShape`` from ``createInstance``
#: answers ``FillStyle = SOLID`` and ``LineStyle = SOLID``, and Impress hands a new shape
#: the attributes of the *last shape created in that office session* - so on a deck where
#: somebody last drew a filled box, the section name would arrive on a grey rectangle.
#: The two are therefore written on every run, not only at creation: a box that picked a
#: fill up (from a duplicated slide, a template, or that last-used look) is flat again
#: after the next *Section Titles*, which is what makes the command idempotent.
_FLAT_DRAWING = (("FillStyle", 0), ("LineStyle", 0),
                 ("Shadow", False), ("ClickThrough", True))


def _draw_flat(shape):
    """Give ``shape`` no fill, no frame and no shadow; what it refuses is skipped."""
    for attribute, value in _FLAT_DRAWING:
        try:
            shape.setPropertyValue(attribute, value)
        except Exception:
            continue


def _new_section_box(doc, page, name):
    """A fresh text box on ``page``, with nothing on it yet, or ``None``.

    A plain ``TextShape`` is created with a fill and a frame, which would put a grey
    rectangle behind the section name, so both are switched off - and a box that
    cannot be switched off is not drawn at all rather than drawn wrong.
    """
    try:
        shape = doc.createInstance(SECTION_BOX_SERVICE)
    except Exception:
        return None
    try:
        page.add(shape)
    except Exception:
        return None
    _draw_flat(shape)
    try:
        shape.Name = name
    except Exception:
        pass
    return shape


def apply_section_titles(doc, settings, ctx=None):
    """Write each slide's section name into a box on that slide; returns a report.

    The slides before the first section get nothing (they have no section), and
    neither do the generated plan slides (they name their section already, in the
    heading).  A box that is there is updated where it stands - position, size,
    characters and text - and no second box is created beside it, which is what
    "similarly to the plan slides, re-trigger updates the content and do not create
    new textboxes" asks for.  A box on a slide that has *lost* its section, or on a
    plan slide, is taken away: a re-run leaves nothing of the old layout behind.

    The **first box the command can see** - the first slide that has one and is meant
    to have one - is the template for every other one: "copy the position and
    formatting of the first section title textbox you see when inserting / updating
    section title".  Rectangle and characters come from it, so a label styled by hand
    on one slide styles the deck.  A box found on a title slide or a plan slide cannot
    set the pattern: it is on its way out, and letting it decide the look would let a
    leftover dictate the whole deck.  Only where no slide has a box to copy do the
    ``section_*`` settings say what the box looks like - which is why the dialog calls
    them *Default …* and why there is no toggle for the choice.
    """
    pages = doc.DrawPages
    sections = get_sections(doc)
    if not [entry for entry in sections if entry.get("indexes")]:
        raise PlanError("This presentation has no sections, so there is no section "
                        "name to write.  Add one with Slide > Insert Section first.")
    master = _master_page(doc, settings.get("master"))

    report = {"written": 0, "created": 0, "updated": 0, "cleared": 0,
              "skipped_plan": 0, "skipped_outside": 0,
              "sections": [entry["name"] for entry in sections
                           if entry.get("indexes")],
              "master": str(master.Name), "look": "the default settings"}

    # the slide whose box decides the look of every one: the first that has a box and
    # is meant to have one, so a hand-styled header propagates and a stray box on a
    # title slide cannot set the pattern
    template_box = None
    for index in range(pages.Count):
        try:
            page = pages.getByIndex(index)
        except Exception:
            continue
        if _is_plan_page(page) or section_of(sections, index) is None:
            continue
        boxes = section_text_shapes(page)
        if boxes:
            template_box = boxes[0]
            report["look"] = "the first section slide's own box"
            break

    deck_body = _section_shapes(doc, master)
    deck_look = _read_look(deck_body) if deck_body is not None else {}

    for index in range(pages.Count):
        try:
            page = pages.getByIndex(index)
        except Exception:
            continue
        name = section_of(sections, index)
        boxes = section_text_shapes(page)
        if _is_plan_page(page) or name is None:
            # nothing belongs on this slide: a box it carries is left over from a run
            # before the slide moved out of its section
            for shape in boxes:
                _drop_shape(page, shape)
                report["cleared"] += 1
            if _is_plan_page(page):
                report["skipped_plan"] += 1
            else:
                report["skipped_outside"] += 1
            continue

        if template_box is not None:
            # the first box says what every box looks like, right down to where it
            # sits: one slide is styled by hand and the rest follow it.  Its own
            # rectangle is used as it stands; only a box that will not say where it
            # is falls back on where a box is computed to go
            look = _read_look(template_box)
            rect = _box_rect_of(template_box) or _section_box_rect(
                doc, master, settings, look.get("CharHeight") or _BODY_PT)
        else:
            look = dict(deck_look)
            size = float(settings.get("section_size") or 0)
            if not size:
                size = _master_char_height(deck_body, _BODY_PT)
            look["CharHeight"] = size
            colour = settings.get("section_color")
            if colour is not None:
                look["CharColor"] = int(colour) & 0xFFFFFF
            font = str(settings.get("section_font") or "").strip()
            if font:
                look["CharFontName"] = font
            rect = _section_box_rect(doc, master, settings, size)

        if not boxes:
            shape = _new_section_box(doc, page, section_text_name(index))
            if shape is None:
                continue
            report["created"] += 1
        else:
            shape = boxes[0]
            report["updated"] += 1
            for extra in boxes[1:]:            # a copied slide can bring a second one
                _drop_shape(page, extra)
                report["cleared"] += 1
        try:
            shape.Name = section_text_name(index)
        except Exception:
            pass
        _paint_section_box(shape, name, look, rect)
        report["written"] += 1
        if template_box is None:
            # the deck had nothing to copy, so the box just written - drawn from the
            # defaults - is what every later slide copies.  Without this the second
            # slide would be computed again from the settings and the two could drift
            template_box = shape
    return report


def _box_rect_of(shape):
    """A box's own rectangle, or ``None`` if it will not say."""
    try:
        return (int(shape.Position.X), int(shape.Position.Y),
                int(shape.Size.Width), int(shape.Size.Height))
    except Exception:
        return None


def _drop_shape(page, shape):
    try:
        page.remove(shape)
        return True
    except Exception:
        return False


def remove_section_titles(doc):
    """Take every section-name box out of the deck; returns how many were deleted.

    Every page is walked, plan slides included: the command is "get rid of what
    *Section Titles* drew", and a box left on a slide that has just lost its section
    is the kind of thing that makes the next run look broken.
    """
    pages = doc.DrawPages
    removed = 0
    for index in range(pages.Count):
        try:
            page = pages.getByIndex(index)
        except Exception:
            continue
        for shape in section_text_shapes(page):
            if _drop_shape(page, shape):
                removed += 1
    return removed
