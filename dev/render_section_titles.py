"""Render the deck with *Section Titles* applied, to PDF and PNG.

    python3 dev/render_section_titles.py [output-dir] [follow]

An assertion cannot tell you a section label is drawn in the wrong place, in the
deck's own grey, or on top of the content - so this puts the deck on paper the way
the user will see it: the plan slides first, then the boxes, then a PDF and one PNG
per slide through ``pdftoppm``.  ``follow`` turns on *take the look from the first
section slide*, the toggle whose effect is only visible in the pictures.
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


def main():
    args = [a for a in sys.argv[1:]]
    follow = "follow" in args
    out = os.path.abspath(args[0] if args and not follow == args[0]
                          else os.path.join(ROOT, "out", "section-titles"))
    os.makedirs(out, exist_ok=True)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    settings = dict(config.load(ctx))
    settings["section_follow_first"] = follow
    print("settings  : %s" % {key: value for key, value in settings.items()
                              if key.startswith("section_")})
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        print("plan      : %s" % core.insert_plan(doc, settings, ctx))
        report = core.apply_section_titles(doc, settings, ctx)
        print("sections  : %s" % report)
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
