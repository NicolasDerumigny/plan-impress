"""Show the plan slides in the development office, footer included.

    python3 dev/show_plan.py [slide name]

``dev/open_fixture.py`` opens the fixture; this one goes further: it runs
``insert_plan`` the way the menu does and puts the requested slide in front of the
controller, so a screenshot shows what the user would see - which is how the
footer was finally confirmed, after every property-level check had already passed
on a slide that displayed no footer.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else core.OVERVIEW_NAME
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = None
    for index in range(64):                     # reuse the window open_fixture.py left
        try:
            candidate = desk.getByIndex(index)
        except Exception:
            break
        if str(getattr(candidate, "URL", "") or "").endswith(os.path.basename(FIXTURE)):
            doc = candidate
            break
    if doc is None:
        doc = lo.open_doc(desk, FIXTURE, hidden=False)
    print("document  : %s" % getattr(doc, "URL", "?"))

    settings = config.load(ctx)
    report = core.insert_plan(doc, settings, ctx)
    print("inserted  : %d slides, footer from %r"
          % (report["inserted"], report["footer"]))

    pages = doc.DrawPages
    names = [pages.getByIndex(i).Name for i in range(pages.Count)]
    print("slides    : %s" % names)
    if wanted not in names:
        raise SystemExit("no slide %r (have %s)" % (wanted, names))
    page = pages.getByName(wanted)
    doc.CurrentController.setCurrentPage(page)
    print("showing   : %s" % wanted)
    for shape in core._footer_shapes(page):
        position, size = shape.Position, shape.Size
        print("   %-16s %d,%d %dx%d  %s pt"
              % (core._footer_kind(shape), position.X, position.Y, size.Width,
                 size.Height, shape.CharHeight))
    print("settings  : %s" % (config.settings_path(ctx),))


if __name__ == "__main__":
    main()
