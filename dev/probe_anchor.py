"""Where does a text box keep its **vertical alignment**? (debug)

    python3 dev/probe_anchor.py

The copy rule takes the rectangle and the characters of the first section box; the
vertical anchoring is the third thing a user sets by hand - *Format > Align Text >
Top / Center / Bottom* - and ``_paint_section_box`` used to force it back to TOP on
every run.  Before copying it, three questions have to be answered with measurements:

1. at which level of the text object does the office keep each of ``TextAnchor``
   (awt), ``TextVerticalAdjust`` (awt) and ``TextAnchorKind`` (drawing)?  The
   characters live on the portion (fact 95); an anchor is a property of the text
   object, so it may only exist on the shape, and reading the wrong level would copy
   a default instead of what was set.
2. does writing one of the three move the other two, the way ``SymbolTextDistance``
   mirrors ``FirstLineOffset`` (fact 50)?  If they are mirrors, copying all three can
   fight itself, and the order in which they are written matters.
3. what does a re-run leave behind when it does *not* copy the anchor?  Printed as the
   last section: this is the report "the vertical alignment is not conserved".
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")

#: The three spellings of "where the lines sit in the box", in the order Impress's own
#: object properties list them.  Two are awt (``TOP`` is 0) and one is drawing (``TOP``
#: is 1, fact 22), so their numbers mean different things and cannot be copied across.
ANCHORS = ("TextAnchor", "TextVerticalAdjust", "TextAnchorKind")


def ask(obj, name):
    """One property as the office names it, or ``-``: an enum answers its *name*."""
    if obj is None:
        return "-"
    try:
        value = obj.getPropertyValue(name)
    except Exception as error:
        return type(error).__name__[:18]
    return "%s(%s)" % (value, getattr(value, "value", ""))


def levels(box):
    """``(shape, first paragraph, first portion)``, any of which may be ``None``."""
    paragraph = core._first_paragraph(box)
    portions = core._portions_of(paragraph) if paragraph else []
    return box, paragraph, portions[0] if portions else None


def say_box(tag, box):
    shape, paragraph, portion = levels(box)
    for name in ANCHORS:
        print("  %-22s %-18s shape %-22s paragraph %-22s portion %s"
              % (tag, name, ask(shape, name), ask(paragraph, name), ask(portion, name)))
    print("  %-22s rect %s  grow h=%s w=%s"
          % (tag, core._box_rect_of(box), ask(shape, "TextAutoGrowHeight"),
             ask(shape, "TextAutoGrowWidth")))


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        print("=== the deck's own content placeholder (the anchoring the deck paints "
              "with, fact 22)")
        body = core._section_shapes(doc, core._master_page(doc, ""))
        if body is not None:
            for name in ANCHORS:
                print("  %-18s shape %-22s paragraph %s"
                      % (name, ask(body, name),
                         ask(core._first_paragraph(body), name)))

        core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        boxes = [b for b in (core.section_text_shapes(doc.DrawPages.getByIndex(i))
                             for i in range(doc.DrawPages.Count)) if b]
        first = boxes[0][0]
        print("\n=== a box as the command drew it (it forces TOP today, fact 22)")
        say_box("created", first)

        print("\n=== what *Format > Align Text > Center* leaves behind, tried one at a "
              "time on the first box")
        for name, centre_value in (("TextAnchor", 1),        # awt CENTER
                                   ("TextVerticalAdjust", 1),  # awt CENTER
                                   ("TextAnchorKind", 2)):     # drawing CENTER
            say_box("before " + name, first)
            try:
                first.setPropertyValue(name, centre_value)
                written = str(centre_value)
            except Exception as error:
                written = type(error).__name__
            print("  -> %s = %s answered %s" % (name, written, ask(first, name)))
            say_box("after " + name, first)

        print("\n=== the box the whole deck is to be copied from: all three centred")
        for name, centre_value in (("TextAnchor", 1), ("TextVerticalAdjust", 1),
                                   ("TextAnchorKind", 2)):
            try:
                first.setPropertyValue(name, centre_value)
            except Exception as error:
                print("  %s: %s" % (name, type(error).__name__))
        first.Size = core._size(25199, 4000)   # tall enough that the anchor is visible
        say_box("template", first)

        report = core.apply_section_titles(doc, dict(config.DEFAULTS), ctx)
        print("\n=== after a run that does not copy the anchor: %s" % report)
        for index in (0, 1):
            box = core.section_text_shapes(doc.DrawPages.getByIndex(index))[0]
            say_box("slide %d" % index, box)
        print("  -> the two boxes agree: %s"
              % (core._box_rect_of(core.section_text_shapes(
                    doc.DrawPages.getByIndex(0))[0])
                 == core._box_rect_of(core.section_text_shapes(
                    doc.DrawPages.getByIndex(1))[0])))
    finally:
        lo.close(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
