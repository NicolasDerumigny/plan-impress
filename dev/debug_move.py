"""Compare ways of selecting the current slide before MovePageUp/Down (debug).

    python3 dev/debug_move.py

The plan slides have to be moved to exact positions after insertion, which the
``.uno:MovePageUp`` / ``.uno:MovePageDown`` commands do - but only for the slide
the view currently has selected.  This script shows which selection call makes
the command work from an out-of-process test.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")

STRATEGIES = ("none", "setCurrentPage", "select", "both")


def names(pages):
    return [pages.getByIndex(i).Name for i in range(pages.Count)]


def run(desk, strategy):
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    pages = doc.DrawPages
    controller = doc.CurrentController
    helper = doc.getComponentContext().ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", doc.getComponentContext()) \
        if hasattr(doc, "getComponentContext") else None
    if helper is None:
        ctx = lo.connect()
        helper = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", ctx)
    frame = controller.Frame

    page = pages.insertNewByIndex(0)          # lands at index 1
    page.Name = "MOVED"
    start = names(pages).index("MOVED")
    for _attempt in range(10):
        current = names(pages).index("MOVED")
        if current == 0:
            break
        if strategy in ("setCurrentPage", "both"):
            try:
                controller.setCurrentPage(page)
            except Exception as error:
                print("   setCurrentPage error:", error)
        if strategy in ("select", "both"):
            try:
                controller.select(page)
            except Exception as error:
                print("   select error:", error)
        helper.executeDispatch(frame, ".uno:MovePageUp", "", 0, ())
        time.sleep(0.2)
    landed = names(pages).index("MOVED")
    print("%-16s inserted at %d -> landed at %d  %s" % (strategy, start, landed,
                                                        "OK" if landed == 0 else "FAIL"))
    lo.close(doc)


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    for strategy in STRATEGIES:
        run(desk, strategy)


if __name__ == "__main__":
    main()
