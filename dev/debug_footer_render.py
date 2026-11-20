"""Which recipe makes a footer appear on a generated slide - decided by rendering.

    python3 dev/debug_footer_render.py [output-dir]

The switches are page properties, not document ones: a ``DrawPage`` carries
``IsFooterVisible``, ``IsDateTimeVisible``, ``IsPageNumberVisible``,
``FooterText``, ``DateTimeText``, ``DateTimeFormat`` and ``IsDateTimeFixed``
(the ODF ``presentation:display-*`` flags plus ``draw:footer-text``).  So the
question is not how to turn a footer on, it is what a page created by
``insertNewByIndex`` gets and what has to be copied for it to look like the rest
of the deck.  ``pages.getByIndex(0)`` of the fixture prints its own values first.

Six pages are then built side by side and exported; the PNGs next to the PDF are
the answer, because none of this is visible in a property read-back:

  A  a plain new page                       - the control
  B  new page, flags and footer text set
  C  B plus footer/date/number shapes created from the master
  D  B, but the date left as a real date field (``IsDateTimeFixed = False``)
  E  a plan slide from ``core.build_plan_slide``, untouched
  F  a plan slide with the footer settings copied from slide 0
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
FLAGS = ("IsFooterVisible", "IsDateTimeVisible", "IsPageNumberVisible",
         "IsDateTimeFixed", "DateTimeFormat")
TEXTS = ("FooterText", "DateTimeText")
KINDS = ("HeaderShape", "DateTimeShape", "FooterShape", "SlideNumberShape")
FOOTER = "Quarterly Review 2026"


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:60])


def read_flags(page):
    out = []
    for name in FLAGS + TEXTS:
        try:
            value = getattr(page, name)
        except Exception as error:
            out.append("%s -> %s" % (name, detail(error)))
            continue
        out.append("%s=%r" % (name, value))
    return " ".join(out)


def write_flags(page, values):
    for name, value in values.items():
        try:
            setattr(page, name, value)
        except Exception as error:
            print("   %-18s = %r -> %s" % (name, value, detail(error)))


def add_footer_shapes(doc, page, master):
    """Create the master's footer band on ``page``; returns what landed."""
    added = []
    for index in range(master.Count):
        shape = master.getByIndex(index)
        shape_type = str(getattr(shape, "ShapeType", ""))
        kind = next((k for k in KINDS if shape_type.endswith("." + k)), None)
        if kind is None:
            continue
        try:
            fresh = doc.createInstance(shape_type)
            page.add(fresh)
        except Exception as error:
            print("   %s: create/add -> %s" % (kind, detail(error)))
            continue
        fresh.Position = shape.Position
        fresh.Size = shape.Size
        for name in ("CharHeight", "CharColor", "CharHeight Asian", "TextAnchor"):
            try:
                fresh.setPropertyValue(name, shape.getPropertyValue(name))
            except Exception:
                pass
        added.append(kind)
    return added


def label(doc, page, text):
    shape = doc.createInstance("com.sun.star.drawing.TextShape")
    page.add(shape)
    shape.Size = uno.createUnoStruct("com.sun.star.awt.Size", 9000, 1400)
    shape.Position = uno.createUnoStruct("com.sun.star.awt.Point", 400, 400)
    shape.setString(text)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                          else os.path.join(ROOT, "out", "footer-render"))
    os.makedirs(out, exist_ok=True)
    global doc
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        pages = doc.DrawPages
        master = doc.MasterPages.getByIndex(0)
        print("slide 0 flags   : %s" % read_flags(pages.getByIndex(0)))
        print("new page flags  :", end=" ")
        probe = pages.insertNewByIndex(pages.Count)
        print(read_flags(probe))
        pages.remove(probe)

        start = pages.Count
        for name in ("A plain new page", "B flags + footer text",
                     "C + footer shapes from master", "D date as a field"):
            page = pages.insertNewByIndex(pages.Count)
            label(doc, page, name)
            if name.startswith("A"):
                continue
            write_flags(page, {"IsFooterVisible": True, "IsDateTimeVisible": True,
                               "IsPageNumberVisible": True, "FooterText": FOOTER})
            if name.startswith("C"):
                print("C added shapes  : %s" % add_footer_shapes(doc, page, master))
            if name.startswith("D"):
                write_flags(page, {"IsDateTimeFixed": False, "DateTimeText": ""})

        settings = dict(core.DEFAULT_SETTINGS if hasattr(core, "DEFAULT_SETTINGS")
                        else {}, muted_color=0xB0B0B0, text_color=0x000000,
                        title="Plan", master="")
        for name in ("E plan slide", "F plan slide + copied footer"):
            page = pages.insertNewByIndex(pages.Count)
            core.build_plan_slide(doc, page, ["Introduction", "Architecture", "Demo"],
                                  1, settings)
            label(doc, page, name)
            if name.startswith("F"):
                donor = pages.getByIndex(0)
                write_flags(page, dict((flag, getattr(donor, flag))
                                       for flag in FLAGS + TEXTS))
        print("built %d extra pages" % (pages.Count - start))

        for index in range(start, pages.Count):
            print("   final %-32s %s" % (pages.getByIndex(index).Name,
                                         read_flags(pages.getByIndex(index))))

        pdf = os.path.join(out, "footer.pdf")
        doc.storeToURL(uno.systemPathToFileUrl(pdf),
                       (lo.pv("FilterName", "impress_pdf_Export"),))
        odp = os.path.join(out, "footer.odp")
        doc.storeToURL(uno.systemPathToFileUrl(odp), (lo.pv("FilterName", "impress8"),))
        print("pdf             : %s" % pdf)
    finally:
        lo.close(doc)
    subprocess.run(["pdftoppm", "-png", "-r", "80", pdf, os.path.join(out, "page")],
                   check=True)
    print("pngs            : %s" % sorted(f for f in os.listdir(out) if f.startswith("page-")))
    # what the writer kept of the footer settings
    directory = os.path.join(out, "unz")
    subprocess.run(["rm", "-rf", directory])
    subprocess.run(["unzip", "-qo", odp, "content.xml", "-d", directory], check=True)
    xml = open(os.path.join(directory, "content.xml"), encoding="utf-8").read()
    import re
    for match in re.finditer(r'<draw:page [^>]*>', xml):
        tag = match.group(0)
        kept = sorted(set(re.findall(r'(?:draw|presentation|loext):[a-z-]*(?:footer|'
                                     r'date|page-number|decor)[a-z-]*="[^"]*"', tag)))
        name = re.search(r'draw:name="([^"]*)"', tag)
        print("   %-30s %s" % (name.group(1)[:28] if name else "?", kept))


if __name__ == "__main__":
    main()
