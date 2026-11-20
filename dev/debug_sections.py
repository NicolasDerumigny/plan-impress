"""Print how ``doc.SlideSections`` really behaves (debug).

    python3 dev/debug_sections.py

Four things about that property are worth seeing rather than believing, all of
them measured on LibreOffice 26.8 and all of them load-bearing in
``plan_impress/core.py``:

1. The name a page answers to is its ``LinkDisplayName`` ("Slide 3"), or the
   value a client last assigned to ``page.Name`` - never the ``DrawPages`` name
   ("page3").  A deck the user made in Impress therefore lists its sections as
   ``Slide 3``, ``Slide 4``, … while ``DrawPages.getByIndex(2).Name`` is page3;
   matching one against the other is what made *Insert Plan Slides* refuse to
   work at all.
2. Writing resolves each name to the position it names *now*: unmatched names are
   dropped in silence and the ranges stretch to cover the gap.
3. The last section always runs to the end of the deck - "these slides belong to
   no section" cannot be expressed on a write.
4. Inserting a page renumbers the auto page names, so not even ``DrawPages``
   names identify a page across a structural change.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402

from plan_impress import core  # noqa: E402


def show(doc, label):
    sections = core.get_sections(doc)
    print("  %-38s %s" % (label, [(s["name"], s["slides"], s["indexes"])
                                  for s in sections]))


def fresh(desk, count):
    doc = lo.new_doc(desk, hidden=False)
    while doc.DrawPages.Count < count:
        doc.DrawPages.insertNewByIndex(doc.DrawPages.Count)
    return doc


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)

    doc = fresh(desk, 7)
    print("1. which name does a page answer to?")
    print("  DrawPages names        :", core.page_names(doc))
    print("  LinkDisplayName        :", [core._display_name(doc.DrawPages.getByIndex(i), i)
                                        for i in range(doc.DrawPages.Count)])
    core.set_sections(doc, [("A", [0, 1]), ("B", [2, 3, 4])])
    show(doc, "written by position")
    def section_prop(name, slides):
        return core._prop("Section0", uno.Any("[]com.sun.star.beans.PropertyValue", (
            core._prop("Name", uno.Any("string", name)),
            core._prop("SlideNameList", uno.Any("[]string", tuple(slides))),
        )))

    doc.SlideSections = uno.Any(
        "[]com.sun.star.beans.PropertyValue",
        (section_prop("OnlyPageNames", ("page3", "page4", "page5")),))
    show(doc, "written with DrawPages names")
    print("  -> those names match nothing, so the section swallows the deck;")
    print("     core.set_sections sends the LinkDisplayName instead.")

    print("2. names mean positions, also when they are stale")
    core.set_sections(doc, [("A", [0, 1]), ("B", [2, 3, 4]), ("C", [5, 6])])
    show(doc, "three sections")
    doc.DrawPages.insertNewByIndex(0)             # lands at index 1
    show(doc, "after insertNewByIndex(0)")
    print("     (the ranges did not move: the page inserted at 1 is now in A and")
    print("      C picked up the extra slide at the end - so sections have to be")
    print("      rewritten after every insertion, see core.insert_plan)")

    print("3. a section cannot stop before the end of the deck")
    doc = fresh(desk, 8)
    core.set_sections(doc, [("A", [1, 2])])
    show(doc, "A asked for slides 2-3 only")

    print("4. DrawPages names are renumbered by an insertion")
    doc = fresh(desk, 7)
    print("  before                 :", core.page_names(doc))
    core.insert_page_at(doc, 2, "PlanImpress:Probe", ctx)
    print("  after inserting at 2   :", core.page_names(doc))
    print("     (the slide that was page3 is page4 now: use positions, not names)")
    lo.close(doc)


if __name__ == "__main__":
    main()
