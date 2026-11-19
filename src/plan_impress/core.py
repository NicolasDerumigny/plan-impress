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

Deleting a slide
    a section is anchored on its first slide, so removing a plan slide that
    leads a section leaves the boundaries of the remaining sections wrong.
    :func:`remove_plan_slides` therefore snapshots the cleaned section lists
    before deleting and rewrites them afterwards.
"""

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

def get_sections(doc):
    """Return ``[{"name": str, "slides": [slide name, ...], "start": int}]``.

    ``start`` is derived from the position of the section's first slide: the
    API stores slide *names*, not indexes.
    """
    names = page_names(doc)
    result = []
    try:
        entries = list(doc.SlideSections)
    except Exception:
        entries = []
    for entry in entries:
        inner = {}
        try:
            for prop in entry.Value:
                inner[prop.Name] = prop.Value
        except (TypeError, AttributeError):
            continue
        slides = [str(name) for name in (inner.get("SlideNameList") or ())]
        if not slides:
            continue  # LibreOffice keeps empty sections around; ignore them
        start = names.index(slides[0]) if slides[0] in names else -1
        result.append({"name": str(inner.get("Name", "")), "slides": slides,
                       "start": start})
    return result


def set_sections(doc, sections):
    """Write ``sections`` (a list of ``(name, [slide names])`` pairs)."""
    outer = []
    for index, entry in enumerate(sections):
        if isinstance(entry, dict):
            name, slides = entry.get("name", ""), entry.get("slides", [])
        else:
            name, slides = entry
        inner = (
            _prop("Name", uno.Any("string", str(name))),
            _prop("SlideNameList", uno.Any("[]string", tuple(str(s) for s in slides))),
        )
        outer.append(_prop("Section%d" % index,
                           uno.Any("[]%s" % _PROPERTY_VALUE, inner)))
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


def _clean_sections(sections):
    """Sections with this extension's own slides taken out of the lists.

    LibreOffice stores a section as a positional range anchored on its first
    slide, so deleting the plan slide it points at shifts the boundaries and
    leaves the remaining membership wrong (measured: removing the plan slides of
    three sections produced two sections with the wrong slides in them).  Every
    section list is therefore rebuilt from this cleaned copy after the pages are
    deleted.
    """
    cleaned = []
    for section in sections:
        slides = [name for name in section["slides"]
                  if not str(name).startswith(PLAN_PREFIX)]
        if slides:
            cleaned.append((section["name"], slides))
    return cleaned


def remove_plan_slides(doc):
    """Delete every slide this extension generated.  Returns how many."""
    pages = doc.DrawPages
    doomed = [pages.getByIndex(i) for i in range(pages.Count)
              if _is_plan_page(pages.getByIndex(i))]
    if not doomed:
        return 0
    cleaned = _clean_sections(get_sections(doc))
    for page in doomed:
        try:
            pages.remove(page)
        except Exception:
            pass
    set_sections(doc, cleaned)   # restore the boundaries the deletions disturbed
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


def _geometry(shape, fallback_pos, fallback_size):
    """Reuse a master placeholder's rectangle so plan slides match the deck."""
    if shape is not None:
        try:
            return (shape.Position.X, shape.Position.Y,
                    shape.Size.Width, shape.Size.Height)
        except Exception:
            pass
    return fallback_pos[0], fallback_pos[1], fallback_size[0], fallback_size[1]


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


def build_plan_slide(doc, page, section_names, current, settings):
    """Fill ``page`` with the heading plus every section name.

    ``current`` is the index of the highlighted section, or ``None`` for the
    overview slide, where all names are drawn in the normal colour.
    """
    master = _master_page(doc, settings.get("master", ""))
    page.MasterPage = master
    _clear_page(page)

    width, height = page.Width, page.Height
    highlight = settings["text_color"]
    muted = settings["muted_color"]

    tx, ty, tw, th = _geometry(
        _title_shape(master), (width * 0.08, height * 0.06),
        (width * 0.84, height * 0.14))
    _make_text_shape(doc, page, ("com.sun.star.presentation.TitleTextShape",
                                 "com.sun.star.drawing.TextShape"),
                     settings.get("title") or "Plan",
                     tx, ty, tw, th, char_height=max(18.0, height / 60.0), bold=True)

    if not section_names:
        raise PlanError("There are no sections to list.")
    bx, by, bw, bh = _geometry(
        _body_shape(master), (width * 0.12, height * 0.26),
        (width * 0.76, height * 0.62))
    body = _make_text_shape(doc, page, BODY_SERVICES, "\n".join(section_names),
                            bx, by, bw, bh, char_height=max(12.0, height / 100.0))
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

    # Insert bottom-up: adding a page shifts every index below it, so starting
    # from the last section keeps the still-pending targets valid.
    inserted = 0
    for position in range(len(sections) - 1, -1, -1):
        start = sections[position]["start"]
        if start < 0:
            raise PlanError("Section '%s' refers to slides that no longer exist."
                            % names[position])
        insert_page_at(doc, start, SECTION_NAME_TEMPLATE % position, ctx)
        inserted += 1

    # The overview sits above everything, i.e. before the plan slide of the
    # first section, which is at the first section's start index.
    overview_start = sections[0]["start"]
    overview = insert_page_at(doc, overview_start, OVERVIEW_NAME, ctx)
    inserted += 1

    # Pages are named uniquely; re-read so the shapes go on the right pages.
    pages = doc.DrawPages
    by_name = {pages.getByIndex(i).Name: pages.getByIndex(i) for i in range(pages.Count)}
    build_plan_slide(doc, by_name[OVERVIEW_NAME], names, None, settings)
    for position, section in enumerate(sections):
        page = by_name.get(SECTION_NAME_TEMPLATE % position)
        if page is None:
            raise PlanError("Internal error: plan slide for section '%s' is missing."
                            % names[position])
        build_plan_slide(doc, page, names, position, settings)

    # Rewrite the sections so each plan slide leads its section.  The overview
    # deliberately stays outside of every section.
    rebuilt = []
    for position, section in enumerate(sections):
        rebuilt.append((section["name"],
                        [SECTION_NAME_TEMPLATE % position] + list(section["slides"])))
    final = set_sections(doc, rebuilt)

    return {
        "sections": len(sections),
        "inserted": inserted,
        "overview": OVERVIEW_NAME,
        "slides": page_names(doc),
        "sections_after": final,
    }


def remove_plan(doc):
    """Remove the plan slides.  Returns how many were deleted."""
    return remove_plan_slides(doc)
