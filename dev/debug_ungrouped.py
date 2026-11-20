"""Can slides stay outside every section, and where?

    python3 dev/debug_ungrouped.py

Sections are stored as lists of slide names, so ungrouped slides are
representable - but the office may normalise them.  This script writes a deck
with a leading, a middle and a trailing ungrouped slide and prints what came
back, then does the same again through ``insert_plan`` to show what the
extension leaves behind.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

NAMES = ["s%d" % i for i in range(6)]


def show(doc, label):
    print("== %s" % label)
    print("   order   : %s" % ", ".join(core.page_names(doc)))
    for section in core.get_sections(doc):
        print("   %-12s: %s" % (section["name"], section["slides"]))
    listed = [n for s in core.get_sections(doc) for n in s["slides"]]
    print("   outside : %s" % (", ".join(n for n in core.page_names(doc)
                                         if n not in listed) or "(none)"))


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.new_doc(desk, hidden=False)
    try:
        doc.DrawPages.getByIndex(0).Name = NAMES[0]
        for name in NAMES[1:]:
            doc.DrawPages.insertNewByIndex(doc.DrawPages.Count).Name = name
        core.set_sections(doc, [("A", ["s1", "s2"]), ("B", ["s4"])])
        show(doc, "sections set by hand: s0 leading, s3 middle, s5 trailing")

        core.insert_plan(doc, dict(config.DEFAULTS), ctx)
        show(doc, "after insert_plan")
    finally:
        lo.close(doc)


if __name__ == "__main__":
    main()
