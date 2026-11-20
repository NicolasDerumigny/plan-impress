"""Is the plan slide in the right place, and did the view follow it?  Repeatedly.

    python3 dev/debug_move_race.py [document] [other-document] [--rounds n]

``insert_page_at`` (fact 14) selects the page with ``setCurrentPage`` and then
dispatches ``.uno:MovePageUp`` - two operations the office performs on its own
schedule.  The report "inserting into the second deck leaves empty slides and loses
sections, and going to Settings fixes it" smells like the two getting out of step:
the dispatch runs while the view still has the *previous* page selected, so it moves
the wrong slide or none at all, and the deck is left with an orphan page and section
ranges that no longer match.

This inserts and removes the plan slides of one deck over and over - with a second
deck open, as in the report - and prints, for every page, how many dispatch rounds
it took, what the view had selected at each round, and how long each step waited.
A round that needed more than one dispatch, or dispatched at all while the view had
not caught up, is printed as such.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

A = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                    else os.path.join(ROOT, "tests", "fixtures", "sections.odp"))
B = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "/tmp/test.odp")
ROUNDS = 6
if "--rounds" in sys.argv:
    ROUNDS = int(sys.argv[sys.argv.index("--rounds") + 1])
CTX = lo.connect()
DESK = lo.desktop(CTX)
STATS = {"rounds": 0, "stale-selection": 0, "lost-move": 0, "failures": 0}


def view_page(controller):
    """What the view has selected right now; ``None`` when it will not say."""
    try:
        return controller.getCurrentPage()
    except Exception:
        return None


def traced_insert_page_at(doc, index, name, ctx=None):
    """A copy of core.insert_page_at that says what the view was doing."""
    pages = doc.DrawPages
    controller = doc.CurrentController
    target = max(0, min(int(index), pages.Count))
    page = pages.insertNewByIndex(max(0, target - 1)) if target \
        else pages.insertNewByIndex(0)
    page.Name = name
    current = core._index_of(pages, page)
    rounds = 0
    for _round in range(100):
        if current == target:
            break
        rounds += 1
        try:
            controller.setCurrentPage(page)
        except Exception:
            pass
        selected = view_page(controller)
        followed = selected is not None and str(selected.Name) == str(name)
        command = ".uno:MovePageUp" if current > target else ".uno:MovePageDown"
        if not followed:
            STATS["stale-selection"] += 1
        core._dispatch(doc, command, ctx)
        moved = core._wait_for_move(pages, page, current)
        if moved == current:
            STATS["lost-move"] += 1
            print("      %s at %d: %s did nothing (view=%r, followed selection=%s)"
                  % (name, current, command,
                     getattr(selected, "Name", None), followed))
            break
        if not followed or rounds > 1:
            print("      %s: round %d moved %d -> %d with %s (view had %r)"
                  % (name, rounds, current, moved, command,
                     getattr(selected, "Name", None)))
        current = moved
    STATS["rounds"] = max(STATS["rounds"], rounds)
    if current != target:
        STATS["failures"] += 1
    return page


def main():
    a = lo.open_doc(DESK, A, hidden=False)
    b = lo.open_doc(DESK, B, hidden=False)
    real = core.insert_page_at
    core.insert_page_at = traced_insert_page_at
    try:
        for number in range(ROUNDS):
            started = time.time()
            try:
                core.insert_plan(a, dict(config.DEFAULTS), CTX)
                outcome = "ok"
            except Exception as error:
                outcome = "%s: %s" % (type(error).__name__, error)
                STATS["failures"] += 1
            removed = core.remove_plan(a)
            pages = a.DrawPages
            print("round %d  %-46s %4.1fs  %d slides, %d removed"
                  % (number, outcome, time.time() - started, pages.Count, removed))
            if pages.Count != 7:
                print("      LEFTOVER SLIDES: %s"
                      % [str(pages.getByIndex(i).Name) for i in range(pages.Count)])
    finally:
        core.insert_page_at = real
        try:
            core.remove_plan(a)
        except Exception:
            pass
        lo.close(b)
        lo.close(a)
    print("worst case %d dispatch rounds, %d dispatches with the view not caught up, "
          "%d lost moves, %d failures"
          % (STATS["rounds"], STATS["stale-selection"], STATS["lost-move"],
             STATS["failures"]))


main()
