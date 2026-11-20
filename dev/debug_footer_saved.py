"""A deck that *comes from a file* with footer frames on its slides.

    python3 dev/debug_footer_saved.py [output-dir]

Footer frames are usually something a deck *comes with* (PowerPoint writes a
``presentation:class="footer"`` frame per slide), and that is the case the extension
has to survive: this builds such a deck, saves it, reopens it, and prints for the
footer shapes of the saved slide what a portion reports
(``TextPortionType``, ``getString()`` - the stored placeholder, not what is drawn -
and whether ``TextField`` can be read; it can, so the service-named recreation in
``core.FOOTER_FIELD_SERVICES`` is insurance rather than the usual path), and then
what the plan slides end up with: the kinds, rectangles and character height of the
donor's band, and the text of every page of the exported PDF, which is the only
place a footer can actually be seen.
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
FIELDS = {"FooterShape": "com.sun.star.presentation.TextField.Footer",
          "DateTimeShape": "com.sun.star.text.TextField.DateTime",
          "SlideNumberShape": "com.sun.star.text.TextField.PageNumber"}
FOOTER_TEXT = "Quarterly Review 2026"


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:60])


def install(doc, page, master):
    """The bottom band as PowerPoint writes it: a frame per slide, with fields."""
    made = []
    for shape in core._footer_shapes(master):
        kind = core._footer_kind(shape)
        if kind not in FIELDS:
            continue
        fresh = doc.createInstance("com.sun.star.presentation.%s" % kind)
        page.add(fresh)
        fresh.Position = shape.Position
        fresh.Size = shape.Size
        fresh.CharHeight = shape.CharHeight
        text = fresh.getText()
        cursor = text.createTextCursor()
        cursor.gotoStart(False)
        cursor.gotoEnd(True)
        text.insertString(cursor, "", True)              # it arrives with a field
        text.insertTextContent(text.createTextCursor(),
                               doc.createInstance(FIELDS[kind]), False)
        made.append(kind)
    return made


def dump_portions(shape, label):
    for paragraph in shape.createEnumeration():
        for portion in paragraph.createEnumeration():
            try:
                kind = portion.getPropertyValue("TextPortionType")
            except Exception as error:
                kind = detail(error)
            try:
                string = portion.getString()
            except Exception as error:
                string = detail(error)
            try:
                field = portion.getPropertyValue("TextField")
                services = field.getSupportedServiceNames()
                names = "field %s" % (services[-1] if services else "?")
            except Exception as error:
                names = "TextField -> %s" % detail(error)
            print("      %-16s %-10s %-14r %s" % (label, kind, string[:14], names))


def band(page):
    out = {}
    for shape in core._footer_shapes(page):
        position, size = shape.Position, shape.Size
        out[core._footer_kind(shape)] = (position.X, position.Y, size.Width,
                                         size.Height, getattr(shape, "CharHeight", None))
    return out


def page_texts(doc, pdf):
    texts = []
    for number in range(1, doc.DrawPages.Count + 1):
        result = subprocess.run(
            ["pdftotext", "-f", str(number), "-l", str(number), pdf, "-"],
            capture_output=True, text=True)
        texts.append(result.stdout)
    return texts


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                          else os.path.join(ROOT, "out", "footer-saved"))
    os.makedirs(out, exist_ok=True)
    deck = os.path.join(out, "deck-with-footers.odp")
    ctx = lo.connect()
    desk = lo.desktop(ctx)

    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        master = doc.MasterPages.getByIndex(0)
        print("== installed on slide 0 : %s" % install(doc, doc.DrawPages.getByIndex(0),
                                                       master))
        doc.storeToURL(uno.systemPathToFileUrl(deck), (lo.pv("FilterName", "impress8"),))
    finally:
        lo.close(doc)

    doc = lo.open_doc(desk, deck, hidden=False)
    try:
        print("== the saved deck, slide 0")
        slide = doc.DrawPages.getByIndex(0)
        for shape in core._footer_shapes(slide):
            dump_portions(shape, core._footer_kind(shape))
        donor = band(slide)
        print("   band                : %s" % sorted(donor))

        report = core.insert_plan(doc, {"muted_color": 0xB0B0B0, "text_color": 0,
                                        "title": "Plan", "master": ""}, ctx)
        print("== inserted            : %d slides, footer from %r"
              % (report["inserted"], report["footer"]))
        problems = []
        for index, page in [(i, doc.DrawPages.getByIndex(i))
                            for i in range(doc.DrawPages.Count)
                            if str(doc.DrawPages.getByIndex(i).Name)
                            .startswith(core.PLAN_PREFIX)]:
            got = band(page)
            print("   page %2d %-24s %s" % (index + 1, page.Name, sorted(got)))
            for kind, wanted in sorted(donor.items()):
                if kind not in got:
                    problems.append("%s: no %s" % (page.Name, kind))
                    continue
                for position, name in ((0, "x"), (1, "y"), (2, "width")):
                    if got[kind][position] != wanted[position]:
                        problems.append("%s: %s %s %r, donor %r"
                                        % (page.Name, kind, name, got[kind][position],
                                           wanted[position]))
                if abs(got[kind][3] - wanted[3]) > 60:
                    problems.append("%s: %s height %r, donor %r"
                                    % (page.Name, kind, got[kind][3], wanted[3]))
                if got[kind][4] != wanted[4]:
                    problems.append("%s: %s CharHeight %r, donor %r"
                                    % (page.Name, kind, got[kind][4], wanted[4]))
                for shape in core._footer_shapes(page):
                    if core._footer_kind(shape) == kind:
                        dump_portions(shape, kind)
        print("== problems           : %s" % (problems or "none"))

        pdf = os.path.join(out, "saved.pdf")
        doc.storeToURL(uno.systemPathToFileUrl(pdf),
                       (lo.pv("FilterName", "impress_pdf_Export"),))
        texts = page_texts(doc, pdf)
        print("== rendered footers")
        for index, page in [(i, doc.DrawPages.getByIndex(i))
                            for i in range(doc.DrawPages.Count)]:
            tail = " | ".join(line.strip() for line in
                              texts[index].splitlines() if line.strip())
            print("   page %2d %-24s %s" % (index + 1, page.Name, tail[:110]))
        for index, page in [(i, doc.DrawPages.getByIndex(i))
                            for i in range(doc.DrawPages.Count)
                            if str(doc.DrawPages.getByIndex(i).Name)
                            .startswith(core.PLAN_PREFIX)]:
            assert FOOTER_TEXT in texts[index], (page.Name, texts[index])
            assert str(index + 1) in texts[index], (page.Name, texts[index])
        print("== every plan page shows the footer and its own number")
    finally:
        lo.close(doc)
    subprocess.run(["pdftoppm", "-png", "-r", "80", pdf, os.path.join(out, "slide")],
                   check=True)
    print("== pngs               : %s"
          % sorted(f for f in os.listdir(out) if f.startswith("slide-")))


if __name__ == "__main__":
    main()
