#!/usr/bin/env python3
"""(Re)create the two documents the tests run against.

    python3 tests/make_fixture.py            # both of them
    python3 tests/make_fixture.py sections   # one of them

``fixtures/sections.odp``
    seven slides in three sections, each slide carrying a footer the way
    "Insert > Header and Footer" leaves it: the switches and the text live on the
    *slide* (``com.sun.star.presentation.DrawPage``), so a deck with a footer has
    them on every slide and the plan slides have to look the same.

``fixtures/sections_no_footer.odp``
    the same deck with the bottom band left alone, which is what a deck looks
    like when nobody ever opened that dialog.  Plan slides must not grow a footer
    in it either, so both variants have to exist.

The fixtures are committed so the tests do not depend on generating them;
``make test`` regenerates them when they are missing.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT)

import lo  # noqa: E402
import uno  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")

SECTIONS = (
    ("Introduction", ["welcome", "agenda-notes"]),
    ("Architecture", ["overview-diagram", "data-model", "apis"]),
    ("Demo", ["live-demo", "questions"]),
)

#: What "Insert > Header and Footer" leaves on every slide.  ``IsDateTimeFixed``
#: False is what makes it a real date field rather than typed text.
FOOTER = {
    "FooterText": "Quarterly Review 2026",
    "IsFooterVisible": True,
    "IsDateTimeVisible": True,
    "IsDateTimeFixed": False,
    "IsPageNumberVisible": True,
}

DECKS = {
    "sections": FOOTER,
    "sections_no_footer": {},           # the band is never touched
}


def build(desk, footer):
    doc = lo.new_doc(desk)
    pages = doc.DrawPages
    titles = [name for _, names in SECTIONS for name in names]
    while pages.Count < len(titles):
        pages.insertNewByIndex(pages.Count)
    for index, title in enumerate(titles):
        page = pages.getByIndex(index)
        page.Name = title
        shape = doc.createInstance("com.sun.star.presentation.TitleTextShape")
        page.add(shape)
        shape.Size = uno.createUnoStruct("com.sun.star.awt.Size",
                                         int(page.Width * 0.8), int(page.Height * 0.2))
        shape.Position = uno.createUnoStruct("com.sun.star.awt.Point",
                                             int(page.Width * 0.1),
                                             int(page.Height * 0.1))
        shape.setString(title.replace("-", " ").title())
        for name, value in footer.items():
            try:
                setattr(page, name, value)
            except Exception as error:            # a build without these properties
                print("warning: %s.%s not set: %s" % (title, name, error))
    # keep the default first (empty) page out of the deck
    while pages.Count > len(titles):
        pages.remove(pages.getByIndex(pages.Count - 1))

    outer = []
    for index, (name, names) in enumerate(SECTIONS):
        def prop(pname, value):
            item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
            item.Name, item.Value = pname, value
            return item
        inner = (prop("Name", uno.Any("string", name)),
                 prop("SlideNameList", uno.Any("[]string", tuple(names))))
        outer.append(prop("Section%d" % index,
                          uno.Any("[]com.sun.star.beans.PropertyValue", inner)))
    doc.SlideSections = uno.Any("[]com.sun.star.beans.PropertyValue", tuple(outer))
    return doc


def write(desk, name, footer):
    path = os.path.join(FIXTURES, "%s.odp" % name)
    doc = build(desk, footer)
    try:
        doc.storeToURL(uno.systemPathToFileUrl(path), (lo.pv("FilterName", "impress8"),))
    finally:
        lo.close(doc)
    print("wrote %s (%s)" % (path, "footer" if footer else "no footer"))


def main():
    os.makedirs(FIXTURES, exist_ok=True)
    wanted = sys.argv[1:] or sorted(DECKS)
    unknown = [name for name in wanted if name not in DECKS]
    if unknown:
        raise SystemExit("unknown deck: %s (have %s)"
                         % (", ".join(unknown), ", ".join(sorted(DECKS))))
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    for name in wanted:
        write(desk, name, DECKS[name])


if __name__ == "__main__":
    main()
