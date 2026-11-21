"""What it takes to give a generated slide the deck's footer.

    python3 dev/debug_footer.py [document]

The plan slides get a heading and a section list and nothing else, so a deck
whose slides carry a footer (or a date, or a page number) shows those on every
slide *except* the generated ones.  Four things have to be measured before that
can be fixed:

1. which shapes the real slides and the master actually have;
2. which placeholder services can be created at all - `SubtitleTextShape` is not
   registered (AGENTS.md 18), so the footer services may or may not be;
3. whether the presentation document exposes the footer switches;
4. whether a shape can be **copied** to another page, because `XShapes.add()` of
   a shape that already lives on a page moves it, which would steal the footer
   from a real slide.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
PLACEHOLDER_SERVICES = (
    "com.sun.star.presentation.FooterTextShape",
    "com.sun.star.presentation.HeaderTextShape",
    "com.sun.star.presentation.DateTextShape",
    "com.sun.star.presentation.SlideNumberTextShape",
    "com.sun.star.presentation.TitleTextShape",
    "com.sun.star.presentation.SubtitleTextShape",
    "com.sun.star.presentation.OutlinerShape",
)
DOCUMENT_FLAGS = ("HeaderIsOn", "FooterIsOn", "DateIsOn", "PageNumberIsOn",
                  "IsHandout", "StartPage", "EndPage")


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:60])


def printed(shape):
    """What the shape is made of, per portion.

    ``getString()`` of a shape holding fields is not the text on the slide: it
    answers with the placeholder stored in the file (``<footer>``, ``<number>``) or
    with whatever the last layout pass painted.  The portions tell the truth about
    the *kind* of content, and the PDF about the text.
    """
    pieces = []
    try:
        paragraphs = list(shape.createEnumeration())
    except Exception:
        return "?"
    for paragraph in paragraphs:
        try:
            portions = list(paragraph.createEnumeration())
        except Exception:
            continue
        for portion in portions:
            try:
                kind = portion.getPropertyValue("TextPortionType")
            except Exception:
                kind = "?"
            if kind == "TextField":
                try:
                    services = portion.getPropertyValue(
                        "TextField").getSupportedServiceNames()
                    pieces.append("{" + (services[-1] if services else "field") + "}")
                    continue
                except Exception:
                    pieces.append("{field}")
                    continue
            try:
                pieces.append(repr(portion.getString()))
            except Exception:
                pieces.append("?")
    return " ".join(pieces)


def describe(shape):
    try:
        text = shape.getString().replace("\n", "\\n")
    except Exception:
        text = "?"
    try:
        pos, size = shape.Position, shape.Size
        rect = "%d,%d %dx%d" % (pos.X, pos.Y, size.Width, size.Height)
    except Exception:
        rect = "?"
    try:
        height = shape.CharHeight
    except Exception:
        height = "?"
    return "%-46s %-16s %5s  %-22r %s" % (getattr(shape, "ShapeType", "?"), rect,
                                          height, text[:20], printed(shape))


def main():
    path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else FIXTURE)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, path, hidden=False)
    try:
        print("== document %s" % os.path.basename(path))
        for flag in DOCUMENT_FLAGS:
            try:
                print("   %-14s = %s" % (flag, getattr(doc, flag)))
            except Exception as error:
                print("   %-14s -> %s" % (flag, detail(error)))

        print("== master pages")
        masters = doc.MasterPages
        for m in range(masters.Count):
            master = masters.getByIndex(m)
            print("   master %r (%d shapes)" % (master.Name, master.Count))
            for i in range(master.Count):
                print("      %s" % describe(master.getByIndex(i)))

        print("== slides")
        pages = doc.DrawPages
        for i in range(min(pages.Count, 3)):
            page = pages.getByIndex(i)
            print("   slide %r (%d shapes)" % (page.Name, page.Count))
            for k in range(page.Count):
                print("      %s" % describe(page.getByIndex(k)))

        print("== creatable placeholder services")
        for service in PLACEHOLDER_SERVICES:
            try:
                shape = doc.createInstance(service)
            except Exception as error:
                print("   %-52s -> %s" % (service.rsplit(".", 1)[-1], detail(error)))
                continue
            page = pages.getByIndex(0)
            before = page.Count
            try:
                page.add(shape)
                added = "%d -> %d shapes" % (before, page.Count)
            except Exception as error:
                added = "add -> %s" % detail(error)
            print("   %-52s created, %s" % (service.rsplit(".", 1)[-1], added))

        print("== can a shape be copied to another page?")
        source_page = pages.getByIndex(0)
        target = pages.insertNewByIndex(pages.Count)
        try:
            donor = None
            for i in range(source_page.Count):
                candidate = source_page.getByIndex(i)
                if candidate.getString():
                    donor = candidate
                    break
            if donor is None:
                print("   no shaped text to copy")
            else:
                print("   copying %r from %r to a new page"
                      % (donor.getString()[:20], source_page.Name))
                try:
                    target.add(donor)
                    print("   target.add(donor): target has %d shapes, source has %d"
                          % (target.Count, source_page.Count))
                except Exception as error:
                    print("   target.add(donor) -> %s" % detail(error))
                try:
                    clone = donor.createClone()
                    target.add(clone)
                    print("   createClone(): target %d, source %d, text %r"
                          % (target.Count, source_page.Count, clone.getString()))
                except Exception as error:
                    print("   createClone() -> %s" % detail(error))
        finally:
            pages.remove(target)
    finally:
        lo.close(doc)


if __name__ == "__main__":
    main()
