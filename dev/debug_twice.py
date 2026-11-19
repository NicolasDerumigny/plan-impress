"""Trace a double insert_plan run (debug helper).

    python3 dev/debug_twice.py

Runs the idempotency scenario with verbose state so the insert/remove logic can
be followed step by step: what the sections look like before and after each
removal and insertion, and where each new page actually lands.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def dump(doc, label):
    pages = core.page_names(doc)
    print("  %-28s n=%2d %s" % (label, len(pages), pages))
    for section in core.get_sections(doc):
        print("      section %-14s start=%s slides=%s" % (section["name"],
                                                          section["start"],
                                                          section["slides"]))


def describe_body(doc, name):
    pages = doc.DrawPages
    by_name = {pages.getByIndex(i).Name: pages.getByIndex(i) for i in range(pages.Count)}
    page = by_name.get(name)
    if page is None:
        print("      %s: MISSING" % name)
        return
    body = core._body_shape(page)
    print("      %s: master=%s shapes=%s" % (
        name, page.MasterPage.Name,
        [page.getByIndex(i).ShapeType for i in range(page.Count)]))
    if body is None:
        return
    print("        body=%s" % body.ShapeType)
    enum = body.createEnumeration()
    index = 0
    while enum.hasMoreElements():
        paragraph = enum.nextElement()
        info = {"type": type(paragraph).__name__}
        for attribute in ("CharColor", "CharHeight", "String"):
            try:
                info[attribute] = getattr(paragraph, attribute)
            except Exception as error:
                info[attribute] = "ERR %s" % type(error).__name__
        print("        para %d %r" % (index, info))
        index += 1


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xABCDEF, "title": "Agenda"})
    try:
        dump(doc, "loaded")
        core.insert_plan(doc, settings, ctx)
        dump(doc, "after first insert")
        describe_body(doc, core.OVERVIEW_NAME)
        describe_body(doc, "PlanImpress:Section=2")
        removed = core.remove_plan(doc)
        print("  remove_plan returned", removed)
        dump(doc, "after remove")
        core.insert_plan(doc, settings, ctx)
        dump(doc, "after second insert")
        describe_body(doc, "PlanImpress:Section=2")
    finally:
        lo.close(doc)


if __name__ == "__main__":
    main()
