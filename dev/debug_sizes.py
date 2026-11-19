"""Report the character heights and rectangles of a generated plan slide.

    python3 dev/debug_sizes.py

Prints, for the title and the body of one generated slide, the ``CharHeight``
seen at shape, paragraph and text-portion level plus the rectangle, so the
font sizes can be checked against what the master placeholder provides.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def heights(shape):
    """``CharHeight`` of the shape, then of every paragraph and portion."""
    out = [("shape", getattr(shape, "CharHeight", None))]
    try:
        paragraphs = list(shape.createEnumeration())
    except Exception as error:
        return out + [("paragraphs unavailable", str(error))]
    for index, paragraph in enumerate(paragraphs):
        out.append(("paragraph %d" % index, getattr(paragraph, "CharHeight", None)))
        try:
            for portion_index, portion in enumerate(paragraph.createEnumeration()):
                out.append(("  portion %d.%d" % (index, portion_index),
                            getattr(portion, "CharHeight", None)))
        except Exception:
            pass
    return out


def report(page, label):
    print("%s (%s) size=%dx%d" % (label, page.Name, page.Width, page.Height))
    master = page.MasterPage
    print("  master=%s" % master.Name)
    for shape in [master.getByIndex(i) for i in range(master.Count)]:
        print("    master shape %-58s CharHeight=%s" % (shape.ShapeType,
                                                        getattr(shape, "CharHeight", None)))
    for index in range(page.Count):
        shape = page.getByIndex(index)
        print("  shape %s" % shape.ShapeType)
        for level, value in heights(shape):
            print("      %-14s %s" % (level, value))
        print("      rect           %dx%d at %d,%d" % (shape.Size.Width, shape.Size.Height,
                                                       shape.Position.X, shape.Position.Y))


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xB0B0B0, "text_color": 0x1F6EC8})
    try:
        core.insert_plan(doc, settings, ctx)
        pages = doc.DrawPages
        by_name = {pages.getByIndex(i).Name: pages.getByIndex(i)
                   for i in range(pages.Count)}
        report(by_name[core.OVERVIEW_NAME], "overview")
        report(by_name["PlanImpress:Section=1"], "section plan")
    finally:
        lo.close(doc)


if __name__ == "__main__":
    main()
