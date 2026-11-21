"""Print what the *Section Titles* command really writes (debug).

    python3 dev/debug_section_titles.py [follow]

Every slide of the fixture is printed before and after: the section its index
belongs to, and one line per box the command drew - its name, its text, its
rectangle and the character properties of the *shape* and of its *first
paragraph*, because the paragraph is what gets painted (fact 52).

The three things the command has to get right are printed in order:

* ``slides before the first section`` and the generated plan slides get no box;
* a second run updates the boxes where they stand instead of adding a second one;
* a slide duplicated *after* the boxes were drawn is recognised by the name's
  prefix, so a re-run makes the copy say the section it now belongs to.
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
            look = core._read_look(shape)
            paragraph = core._first_paragraph(shape)
            para_height = (core._read_look(paragraph).get("CharHeight")
                           if paragraph is not None else None)
            print("       box %-38s %r at %s %s pt colour #%06X font %s"
                  " paragraph %s pt fill=%s line=%s"
                  % (str(shape.Name), str(shape.getString()),
                     (int(shape.Position.X), int(shape.Position.Y),
                      int(shape.Size.Width), int(shape.Size.Height)),
                     look.get("CharHeight"),
                     int(look.get("CharColor") or 0) & 0xFFFFFF,
                     look.get("CharFontName"), para_height,
                     _style_of(shape, "FillStyle"),
                     _style_of(shape, "LineStyle")))


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


def main():
    follow = "follow" in sys.argv[1:]
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, os.path.join(ROOT, "tests", "fixtures",
                         "sections.odp"), hidden=False)
    try:
        settings = dict(config_mod.DEFAULTS)
        settings["section_follow_first"] = follow
        if follow:
            # style the first box by hand, which is the case the toggle is for
            pass

        print("before:")
        describe(doc)

        print("\napply 1:", core.apply_section_titles(doc, settings, ctx))
        describe(doc)

        print("\napply 2 (must update, never add):",
              core.apply_section_titles(doc, settings, ctx))
        describe(doc)

        if follow:
            pages = doc.DrawPages
            first = None
            for index in range(pages.Count):
                if core.section_text_shapes(pages.getByIndex(index)):
                    first = core.section_text_shapes(pages.getByIndex(index))[0]
                    break
            first.CharHeight = 28
            first.CharColor = 0xFF0000
            first.CharFontName = "Liberation Serif"
            first.Position = core._point(900, 1200)
            print("\nfirst box restyled by hand")
            print("apply 3 (follow the first):",
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
