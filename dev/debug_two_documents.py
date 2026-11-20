"""What a second document does to *Insert Plan Slides*: the reproducer.

    python3 dev/debug_two_documents.py [document-a] [document-b]

The report this reproduces is "after inserting plan slides in one presentation,
clicking Insert Plan Slides in another one loses sections and leaves empty slides
- and going to Settings makes it work again", so every scenario here opens two
decks in the same office (the extension's settings are per profile, i.e. shared by
both) and inserts into one of them, and then compares what the deck says about
itself before and after:

* ``sections``   the ranges ``SlideSections`` reports, resolved to indexes;
* ``plan``       the generated slides, with what each of them actually holds -
                 a slide whose heading and list are empty is an "empty slide";
* ``masters``    which master the generated slides ended up on.

A scenario is FAILED when the deck is left with fewer sections than it started
with, with a section that swallowed the whole deck, or with a plan slide that has
no heading or no list.  Nothing is ever saved.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

A = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                    else os.path.join(ROOT, "tests", "fixtures", "sections.odp"))
B = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "/tmp/test.odp")
DESK = None


def open_doc(path):
    return lo.open_doc(DESK, path, hidden=False)


def snapshot(doc):
    """What the deck claims about itself, in a form two of them can be compared."""
    pages = doc.DrawPages
    sections = core.get_sections(doc)
    plan = []
    for i in range(pages.Count):
        page = pages.getByIndex(i)
        if not core._is_plan_page(page):
            continue
        title, body = core._title_shape(page), core._body_shape(page)
        plan.append({
            "index": i,
            "name": str(page.Name),
            "master": str(page.MasterPage.Name),
            "shapes": page.Count,
            "title": (str(title.getString()) if title is not None else None),
            "rows": ([p.getString() for p in core._paragraphs_of(body)]
                     if body is not None else None),
        })
    return {"count": pages.Count,
            "masters": [doc.MasterPages.getByIndex(i).Name
                        for i in range(doc.MasterPages.Count)],
            "sections": [(s["name"], s["indexes"]) for s in sections],
            "plan": plan}


def verdict(before, after, label):
    """One line per thing that must not have happened."""
    problems = []
    if len(after["sections"]) < len(before["sections"]):
        problems.append("lost a section: %r -> %r"
                        % (before["sections"], after["sections"]))
    total = after["count"]
    for name, indexes in after["sections"]:
        if indexes and len(indexes) >= total - 1 and len(after["sections"]) > 1:
            problems.append("section %r swallowed the deck: %s" % (name, indexes))
    for slide in after["plan"]:
        if not slide["title"]:
            problems.append("empty plan slide %r (no heading, %d shapes)"
                            % (slide["name"], slide["shapes"]))
        elif not slide["rows"] or any(not r for r in slide["rows"]):
            problems.append("empty plan slide %r (no list: %r)"
                            % (slide["name"], slide["rows"]))
    print("  %-58s %s" % (label, "ok" if not problems else "FAILED"))
    for problem in problems:
        print("      %s" % problem)
    return not problems


def run(label, settings, *docs):
    """Insert into each document in turn, with one shared settings dict."""
    print("\n== %s (master=%r) ==" % (label, settings.get("master")))
    ok = True
    states = [snapshot(doc) for doc in docs]
    for number, (doc, before) in enumerate(zip(docs, states)):
        print("  deck %d: %d slides, masters %r, sections %r"
              % (number, before["count"], before["masters"], before["sections"]))
    for number, doc in enumerate(docs):
        before = states[number]
        try:
            core.insert_plan(doc, dict(settings), CTX)
        except Exception as error:
            print("  %-58s RAISED %s: %s"
                  % ("deck %d: insert_plan" % number, type(error).__name__, error))
            continue
        ok = verdict(before, snapshot(doc), "deck %d: insert_plan" % number) and ok
    return ok


CTX = lo.connect()
DESK = lo.desktop(CTX)


def half_insert(doc, settings, fails_at):
    """A run that stops half way: does the deck come out of it unchanged?

    ``fails_at`` makes the n-th generated slide raise, which is what the move
    commands do when they give up - after the page already exists.  The deck must
    look exactly as it did before: no plan slide left behind, same sections.
    """
    before = snapshot(doc)
    real = core.build_plan_slide
    state = {"n": 0}

    def exploding(d, page, names, current, s, footer=None, master=None):
        state["n"] += 1
        if state["n"] == fails_at:
            raise RuntimeError("simulated: the move commands gave up")
        return real(d, page, names, current, s, footer, master)

    core.build_plan_slide = exploding
    try:
        core.insert_plan(doc, dict(settings), CTX)
        outcome = "did not fail at all"
    except Exception as error:
        outcome = "%s: %s" % (type(error).__name__, error)
    finally:
        core.build_plan_slide = real
    after = snapshot(doc)
    same = (after["count"] == before["count"]
            and after["sections"] == before["sections"]
            and not after["plan"])
    print("  %-58s %s" % ("deck stops at plan slide %d of the insert" % fails_at,
                          "ok" if same else "FAILED"))
    print("      %s" % outcome)
    if not same:
        print("      slides: %d -> %d   %r" % (before["count"], after["count"],
                                               [p["name"] for p in after["plan"]]))
        print("      sections: %r -> %r" % (before["sections"], after["sections"]))
    return same


def main():
    saved = config.load(CTX)
    results = []
    a, b = open_doc(A), open_doc(B)
    try:
        results.append(run("both decks, the settings say nothing about a master",
                           dict(config.DEFAULTS), a, b))
        # the same deck twice: the second run sees the first one's plan slides
        before = snapshot(a)
        core.insert_plan(a, dict(config.DEFAULTS), CTX)
        core.insert_plan(a, dict(config.DEFAULTS), CTX)
        results.append(verdict(before, snapshot(a), "deck a: insert twice in a row"))
        # a master picked in one deck, used in the other: that is the report
        for name in (snapshot(a)["masters"][0], snapshot(b)["masters"][0]):
            settings = dict(config.DEFAULTS)
            settings["master"] = name
            results.append(run("the settings name the master %r of the other deck" % name,
                               settings, a, b))
        # a run that stops half way must leave the deck as it found it
        core.remove_plan(a)
        for number in (1, 2, 4):
            results.append(half_insert(a, dict(config.DEFAULTS), number))
    finally:
        core.remove_plan(a)
        core.remove_plan(b)
        lo.close(a)
        lo.close(b)
        print("\nsettings left as they were: %r" % (saved,))
    print("%d of %d scenarios clean" % (sum(1 for r in results if r), len(results)))


main()
