"""Print what the *Insert Section Titles* command really writes (debug).

    python3 dev/debug_section_titles.py

Every slide of the fixture is printed before and after: the section its index
belongs to, and one line per box the command drew - its name, its text, its
rectangle - plus its characters at **all three** levels of fact 52's ladder: the
shape, its first *paragraph* and that paragraph's first *portion*.  The third one is
what the office paints and what the user's formatting changes, so it is the level a
box has to be copied *from* and written *to*; printing all three side by side is how
"the position copies but the font does not" was told from a copy that never ran.

The four things the command has to get right are printed in order:

* ``slides before the first section`` and the generated plan slides get no box;
* a second run updates the boxes where they stand instead of adding a second one;
* the first box, styled in the editor the way a user styles text, decides what every
  other box looks like and where it sits;
* a slide duplicated *after* the boxes were drawn is recognised by the name's
  prefix, so a re-run makes the copy say the copy's own section.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

from plan_impress import config as config_mod  # noqa: E402
from plan_impress import core  # noqa: E402


def _style_of(shape, name):
    """``FillStyle``/``LineStyle`` as the office names them (fact 92).

    Printed because they decide whether the label is painted over the slide or on a grey
    plate with a line round it: the office's own default for a created ``TextShape`` is
    ``SOLID`` for both (fact 88), which the command has to switch off again.
    """
    try:
        value = shape.getPropertyValue(name)
    except Exception as error:
        return type(error).__name__
    return str(getattr(value, "value", value))


def _ask(obj, name):
    """One property of one level, as the office answers it; ``?`` when it has none.

    Printed per attribute because the levels do not have the same set: a paragraph or a
    portion has no ``CharStyleName`` at all (fact 52), and asking the whole level in one
    go would report the *exception* instead of the four properties it does answer.
    """
    try:
        return str(obj.getPropertyValue(name))
    except Exception:
        return "?"


def _level_of(obj):
    """One level of fact 52's ladder, as the office answers it; ``-`` if no object."""
    if obj is None:
        return "-"
    colour = _ask(obj, "CharColor")
    try:
        colour = "#%06X" % (int(colour) & 0xFFFFFF)
    except ValueError:
        pass                                    # an office that answers a word
    return "%s pt %s %s/%s w%s" % (
        _ask(obj, "CharHeight"), colour, _ask(obj, "CharFontName"),
        _ask(obj, "CharStyleName"), _ask(obj, "CharWeight"))


def describe(doc):
    pages = doc.DrawPages
    sections = core.get_sections(doc)
    for index in range(pages.Count):
        page = pages.getByIndex(index)
        boxes = core.section_text_shapes(page)
        plan = core._is_plan_page(page)
        name = core.section_of(sections, index)
        print("  %-2d %-8s section=%-14s %s"
              % (index, str(page.Name), str(name),
                 "PLAN" if plan and not boxes else ""))
        for shape in boxes:
            # the three levels of fact 52's ladder, printed next to each other: what
            # ``_read_look`` answers has to be what the *portion* says, because the
            # portion is what the office paints and what the user's formatting changes
            look = core._read_look(shape)
            paragraph = core._first_paragraph(shape)
            portions = core._portions_of(paragraph) if paragraph else []
            print("       box %-38s %r at %s fill=%s line=%s"
                  % (str(shape.Name), str(shape.getString()),
                     (int(shape.Position.X), int(shape.Position.Y),
                      int(shape.Size.Width), int(shape.Size.Height)),
                     _style_of(shape, "FillStyle"),
                     _style_of(shape, "LineStyle")))
            print("       shape | paragraph | portion ->  %s" % "  |  ".join(
                (_level_of(shape), _level_of(paragraph),
                 _level_of(portions[0] if portions else None))))
            print("       _read_look            %s pt #%06X %s/%s w%s"
                  % (look.get("CharHeight"),
                     int(look.get("CharColor") or 0) & 0xFFFFFF,
                     look.get("CharFontName"), look.get("CharStyleName"),
                     look.get("CharWeight")))


def duplicate(doc, ctx, index):
    """Duplicate page ``index`` the way the menu does; the new page or None."""
    pages = doc.DrawPages
    before = pages.Count
    doc.CurrentController.setCurrentPage(pages.getByIndex(index))
    core._dispatch(doc, ".uno:DuplicatePage", ctx)
    for _ in range(100):
        if pages.Count > before:
            return pages.getByIndex(before)
        time.sleep(0.05)
    return None


def _restyle_like_the_editor(box):
    """Change a box's characters the way Impress does: on the **text portion**.

    ``box.CharHeight = 28`` is what a macro does, and it only touches the default
    underneath everything; what the sidebar and the toolbar change is the portion, and
    that is what gets painted.  This is therefore the case the copy rule has to survive.
    """
    paragraph = core._first_paragraph(box)
    portions = core._portions_of(paragraph)
    if not portions:
        print("  !! the box has no text portion to style")
        return None
    portion = portions[0]
    portion.CharHeight = 28
    portion.CharColor = 0xFF0000
    portion.CharFontName = "Liberation Serif"
    portion.CharWeight = 150          # awt FontWeight.BOLD
    portion.CharPosture = 2           # awt FontSlant.OBLIQUE
    box.Position = core._point(900, 1200)
    return portion


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, os.path.join(ROOT, "tests", "fixtures",
                         "sections.odp"), hidden=False)
    try:
        settings = dict(config_mod.DEFAULTS)

        print("before:")
        describe(doc)

        print("\napply 1:", core.apply_section_titles(doc, settings, ctx))
        describe(doc)

        print("\napply 2 (must update, never add):",
              core.apply_section_titles(doc, settings, ctx))
        describe(doc)

        pages = doc.DrawPages
        first = None
        for index in range(pages.Count):
            if core.section_text_shapes(pages.getByIndex(index)):
                first = core.section_text_shapes(pages.getByIndex(index))[0]
                break
        if _restyle_like_the_editor(first) is not None:
            print("\nfirst box restyled in the editor (28 pt bold oblique serif,"
                  " red, moved to 9,12 mm)")
            describe(doc)
            print("apply 3 (every box must become that):",
                  core.apply_section_titles(doc, settings, ctx))
            describe(doc)

        print("\nduplicate the first slide that has a box:")
        pages = doc.DrawPages
        for index in range(pages.Count):
            if core.section_text_shapes(pages.getByIndex(index)):
                new_page = duplicate(doc, ctx, index)
                print("  page %d duplicated -> %s"
                      % (index, new_page is not None and new_page.Name or "FAILED"))
                break
        describe(doc)
        print("apply 4 (the copy must say its own section):",
              core.apply_section_titles(doc, settings, ctx))
        describe(doc)

        print("\nremove:", core.remove_section_titles(doc))
        describe(doc)
        print("\nslides left:", doc.DrawPages.Count)
    finally:
        lo.close(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
