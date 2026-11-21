"""Render the deck with *Insert Section Titles* applied, to PDF and PNG.

    python3 dev/render_section_titles.py [output-dir] [restyled]

An assertion cannot tell you a section label is drawn in the wrong place, in the
deck's own grey, or on top of the content - so this puts the deck on paper the way
the user will see it: the plan slides first, then the boxes, then a PDF and one PNG
per slide through ``pdftoppm``.  ``restyled`` styles the first box in the editor's own
way - on its **text portion**, which is what the user's formatting changes - so the
pictures show whether the copy rule really took the font, the weight and the colour or
only the position.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402

from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def _restyle_first_box(doc):
    """Style the first box the way the editor does; True when one was found.

    The formatting goes on the box's **text portion**, because that is the level the
    user's size/weight/colour changes reach and the level that paints; setting the
    property on the shape only changes the default underneath.
    """
    for index in range(doc.DrawPages.Count):
        boxes = core.section_text_shapes(doc.DrawPages.getByIndex(index))
        if not boxes:
            continue
        box = boxes[0]
        paragraph = core._first_paragraph(box)
        portions = core._portions_of(paragraph)
        if not portions:
            print("!! slide %d's box has no text portion" % index)
            return False
        portion = portions[0]
        portion.CharHeight = 28
        portion.CharColor = 0xFF0000
        portion.CharFontName = "Liberation Serif"
        portion.CharWeight = 150                      # awt FontWeight.BOLD
        portion.CharPosture = 2                       # awt FontSlant.OBLIQUE
        box.Position = core._point(900, 1200)
        print("restyled : slide %d's box, at its portion" % index)
        return True
    return False


def main():
    args = [a for a in sys.argv[1:]]
    restyled = "restyled" in args
    out = os.path.abspath(args[0] if args and args[0] != restyled
                          else os.path.join(ROOT, "out", "section-titles"))
    os.makedirs(out, exist_ok=True)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    settings = dict(config.load(ctx))
    print("settings  : %s" % {key: value for key, value in settings.items()
                              if key.startswith("section_")})
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        print("plan      : %s" % core.insert_plan(doc, settings, ctx))
        report = core.apply_section_titles(doc, settings, ctx)
        print("sections  : %s" % report)
        if restyled and _restyle_first_box(doc):
            # the user's own case, done the way the editor does it: the formatting goes
            # on the text portion.  Every other box has to come out of the next run
            # looking like *this* one, not just sitting where it does
            report = core.apply_section_titles(doc, settings, ctx)
            print("restyled  : %s" % report)
        pages = doc.DrawPages
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            for shape in core.section_text_shapes(page):
                look = core._read_look(shape)
                print("  %-2d %-22s %-14r at %s  %s pt #%06X %s"
                      % (index, str(page.Name), str(shape.getString()),
                         core._box_rect_of(shape), look.get("CharHeight"),
                         int(look.get("CharColor") or 0) & 0xFFFFFF,
                         look.get("CharFontName")))
        pdf = os.path.join(out, "sections.pdf")
        doc.storeToURL(uno.systemPathToFileUrl(pdf), (lo.pv("FilterName", "impress_pdf_Export"),))
        print("pdf       : %s" % pdf)
    finally:
        lo.close(doc)
    subprocess.call("cd %s && rm -f slide-*.png && pdftoppm -png -r 60 sections.pdf slide"
                    % out, shell=True)
    print("pngs      : %s" % sorted(name for name in os.listdir(out)
                                    if name.endswith(".png")))
    # what the PDF really says, per slide: a field or a shape that is not drawn
    # does not appear here whatever the model claims (fact 41)
    for number in range(1, len(os.listdir(out)) ):
        name = os.path.join(out, "slide-%02d.png" % number)
        if not os.path.exists(name):
            continue
        text = subprocess.check_output(
            ["pdftotext", "-f", str(number), "-l", str(number), pdf, "-"]).decode()
        print("  slide %d text: %s" % (number, " | ".join(
            line.strip() for line in text.splitlines() if line.strip())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
