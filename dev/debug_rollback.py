"""Which part of a rolled-back insert takes the office down?

    python3 dev/debug_rollback.py [document]

``insert_plan`` undoes itself when it stops half way (``core._drop_pages``): it
deletes the generated pages and writes the section list back.  Doing that in one
go crashed the office (``Fatal exception: Signal 11``) from the test, so this runs
the three failure points one at a time - the move commands giving up, a slide that
cannot be built, the section check refusing - and prints how far it got and what
the deck says afterwards.  Run it once per case with ``--case`` to see which one
kills the office.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import config, core  # noqa: E402

DOC = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
                      else os.path.join(ROOT, "tests", "fixtures", "sections.odp"))
CASE = None
for index, argument in enumerate(sys.argv):
    if argument == "--case":
        CASE = sys.argv[index + 1]
CTX = lo.connect()
DESK = lo.desktop(CTX)


def step(message):
    print("   %-52s %4.1fs" % (message, 0.0), flush=True)


def run_case(name):
    doc = lo.open_doc(DESK, DOC, hidden=False)
    real = (core.insert_page_at, core.build_plan_slide, core._check_sections)
    try:
        names = core.page_names(doc)
        sections = [(s["name"], s["indexes"]) for s in core.get_sections(doc)]
        state = {"n": 0}

        def moves_that_give_up(d, index, page_name, c=None):
            state["n"] += 1
            page = real[0](d, index, page_name, c)
            if state["n"] == 2:
                raise core.PlanError("simulated: the page stayed where it was")
            return page

        def slide_that_fails(d, page, section_names, current, settings, footer=None,
                             master=None):
            state["n"] += 1
            if state["n"] == 3:
                raise RuntimeError("simulated: the placeholders could not be filled")
            return real[1](d, page, section_names, current, settings, footer, master)

        def sections_that_refuse(sections_, expected_, names_):
            raise core.PlanError("simulated: the sections do not match the slides")

        if name == "moves":
            core.insert_page_at = moves_that_give_up
        elif name == "build":
            core.build_plan_slide = slide_that_fails
        elif name == "check":
            core._check_sections = sections_that_refuse
        else:
            raise SystemExit("unknown case %r" % name)
        step("%s: insert_plan" % name)
        try:
            core.insert_plan(doc, dict(config.DEFAULTS), CTX)
            print("      the run did not fail at all!")
        except Exception as error:
            step("%s: raised %s: %s" % (name, type(error).__name__, error))
        finally:
            core.insert_page_at, core.build_plan_slide, core._check_sections = real
        step("%s: deck now %r" % (name, core.page_names(doc)))
        back = [(s["name"], s["indexes"]) for s in core.get_sections(doc)]
        step("%s: sections now %r" % (name, back))
        step("%s: same slides as before: %s" % (name, core.page_names(doc) == names))
        step("%s: same sections as before: %s" % (name, back == sections))
        step("%s: remove_plan finds %d" % (name, core.remove_plan(doc)))
    finally:
        try:
            lo.close(doc)
        except Exception as error:
            print("      close failed: %s" % error)


for case in ([CASE] if CASE else ["moves", "build", "check"]):
    print("== case %s ==" % case, flush=True)
    run_case(case)
    time.sleep(1.0)
    print("   office alive", flush=True)
