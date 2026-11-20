"""What the deck paints with, and where the generated slides put themselves.

    python3 dev/debug_style_source.py [document] [page ...]

The generated slides copy their look from the deck's own slides - their boxes,
their point size, their font - and fall back to the master page only where no
slide has anything to copy.  That distinction is invisible in the model unless it
is printed side by side, because the three levels a character height can live on
disagree with each other: on the deck this was measured on, the title placeholder
of the *master* answers 32 pt as a shape and 31 pt as its first paragraph (a
master's content placeholder keeps one paragraph per outline level), and every
title of the *deck* is drawn at 31 pt in a box 26 units higher than the master's.

The plan slides are generated but never stored; the document is not saved.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import config, core  # noqa: E402

DEFAULT = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
ATTRIBUTES = ("CharHeight", "CharFontName", "CharWeight", "CharColor",
              "TextVerticalAdjust", "TextFitToSize", "TextAutoGrowHeight")


def describe(shape):
    """``rect`` plus the character properties, as shape and as first paragraph."""
    bits = ["%6d,%6d %6dx%-6d" % (shape.Position.X, shape.Position.Y,
                                  shape.Size.Width, shape.Size.Height)]
    for name in ATTRIBUTES:
        try:
            value = shape.getPropertyValue(name)
            bits.append("%s=%s" % (name, getattr(value, "value", value)))
        except Exception:
            pass
    paragraph = core._first_paragraph(shape)
    if paragraph is not None:
        for name in ("CharHeight", "CharWeight", "ParaLeftMargin",
                     "ParaFirstLineIndent"):
            try:
                bits.append("p0.%s=%s" % (name, paragraph.getPropertyValue(name)))
            except Exception:
                pass
    return " ".join(bits)


def dump(container, label, only=None):
    print("== %s ==" % label)
    for index in range(container.Count):
        page = container.getByIndex(index)
        if only and index not in only:
            continue
        try:
            master = " master=%r layout=%s" % (str(page.MasterPage.Name), page.Layout)
        except Exception:
            master = ""
        print("%2d %-26r%s" % (index, str(page.Name), master))
        for kind, wanted in (("title", core._is_title), ("body", core._is_content)):
            for i in range(page.Count):
                shape = page.getByIndex(i)
                try:
                    if wanted(shape):
                        print("   %-5s %-16s %s"
                              % (kind, str(shape.ShapeType).split(".")[-1],
                                 describe(shape)))
                except Exception:
                    continue


def main():
    document = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, document, hidden=False)
    try:
        dump(doc.MasterPages, "masters")
        dump(doc.DrawPages, "the deck's own slides")
        master = core._master_page(doc, "")
        title, body = core._style_source(doc, master)
        print("== what the plan slides copy (master %r) ==" % str(master.Name))
        print("   title %s" % (describe(title) if title is not None else None))
        print("   body  %s" % (describe(body) if body is not None else None))
        print("   painted title size %s pt, painted body size %s pt"
              % (core._master_char_height(title, 0.0),
                 core._master_char_height(body, 0.0)))
        report = core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        print("== generated (%d slides, footer from %r) =="
              % (report["inserted"], report["footer"]))
        pages = doc.DrawPages
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            if not core._is_plan_page(page):
                continue
            print("   %-24r layout=%s" % (str(page.Name), page.Layout))
            for kind, wanted in (("title", core._is_title), ("body", core._is_content)):
                for i in range(page.Count):
                    shape = page.getByIndex(i)
                    if wanted(shape):
                        print("     %-5s %-16s %s"
                              % (kind, str(shape.ShapeType).split(".")[-1],
                                 describe(shape)))
                        if kind == "body":
                            print("           the heading paints down to %d; the list "
                                  "starts at %d"
                                  % (core._heading_bottom(
                                      core._title_shape(page).Position.Y,
                                      core._title_shape(page).Size.Height,
                                      core._title_shape(page).CharHeight,
                                      core._text_anchor(core._title_shape(page))),
                                      shape.Position.Y))
    finally:
        lo.close(doc)


main()
