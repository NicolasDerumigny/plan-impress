"""Every spelling of ``createMessageBox``, screenshotted one after another.

    python3 dev/probe_message_box.py [spelling ...]

"Toggle Debug Log does nothing" turned out to be ``createMessageBox`` raising
``IllegalArgumentException: expected 5, got 4`` - LibreOffice 26.x exposes it on
``XToolkit2`` with five parameters, ``(XWindowPeer, MessageBoxType, long, string,
string)``, while ``XToolkit`` up to LibreOffice 7.x had four - so the box was built
by a four-argument call that never succeeded and, with no exception crossing the Job
boundary (fact 66), nothing appeared.  Which of the two strings the fifth parameter
is (``text`` then ``title``, or the other way round) and whether an unlabelled box is
this office's own look are both questions a screenshot answers and an assertion does
not, so this prints, for each spelling:

    the arguments it passed, then a screenshot while the box is up, then how the
    office answered.

The box is modal, so the screenshot has to be taken from outside the blocked call:
``scrot`` is run detached and the box is dismissed afterwards by activating the
smallest soffice window (a modal box is the smallest one there is) and pressing
Return.  Run one spelling per office session; ``make install`` between changes.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the box logs through config, which needs a profile to log into, and this script
# runs outside the office where there is no deployment path to read one from
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(ROOT, "loprofile", "user", "planimpress"))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

DOC = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
TEXT = "Debug log enabled, writing to\n%s" % os.path.join(ROOT, "loprofile/x.log")
TITLE = "Plan Impress"
SHOTS = "/tmp/opencode/box-probe"
_OK = 1

SPELLINGS = {
    "5-args text-then-title": (TEXT, TITLE),
    "5-args title-then-text": (TITLE, TEXT),
    "4-args text": (TEXT,),
    # a box that sizes itself to nothing whether the text is one line or forty says
    # the strings are not reaching the dialog at all, which is a different problem
    # from a layout that collapses without a window manager
    "5-args long-text": ("X" * 40 + "\n" + TEXT + "\n" + "Y" * 400, TITLE),
    # ours, for the side by side comparison with the two above
    "our-own box": None,
    "our-own yes-no": None,
}


def show_our_box(ctx, name):
    """Call :func:`plan_impress.dialog.message` and return what it answers."""
    from plan_impress import dialog
    if name == "our-own yes-no":
        return dialog.message(ctx, TEXT, "warning", 5, TITLE)
    return dialog.message(ctx, TEXT, "info", 1, TITLE)


def snapshot_and_dismiss(name):
    """Screenshot the screen, then press Return on the modal box.

    The box blocks this process inside ``execute()``, so both have to happen from
    outside it; the office's modal box is the smallest soffice window on screen.
    """
    script = (
        "sleep 2; scrot -o %s/%s.png; "
        "for w in $(xdotool search --class soffice.bin); do "
        "  read -r w h <<< $(xdotool getwindowgeometry --shell $w | "
        "      sed -n 's/^width=//p;s/^height=//p' | tr '\\n' ' '); "
        "  if [ \"$w\" -lt 700 ] && [ \"$h\" -lt 400 ] && [ \"$w\" -gt 10 ]; then "
        "    xdotool windowactivate --sync $w; sleep 0.4; xdotool key --clearmodifiers Return; "
        "  fi; "
        "done" % (SHOTS, name))
    return subprocess.Popen(["bash", "-c", script])


def main():
    if not os.path.isdir(SHOTS):
        os.makedirs(SHOTS)
    names = sys.argv[1:] or sorted(SPELLINGS)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx)
    doc = lo.open_doc(desk, DOC, hidden=False)
    parent = doc.CurrentController.Frame.ContainerWindow
    print("parent: %s" % ("none" if parent is None else
                          type(parent).__name__))
    try:
        for name in names:
            args = SPELLINGS[name]
            helper = None
            started = time.time()
            if args is None:                       # our own box, not the office's
                print("\n== %s: dialog.message(...)" % name)
                helper = snapshot_and_dismiss(name)
                try:
                    result = show_our_box(ctx, name)
                    print("   message() answered %r after %.1fs"
                          % (result, time.time() - started))
                except Exception as error:
                    print("   message() raised %s: %s"
                          % (type(error).__name__, error))
                finally:
                    helper.communicate(timeout=20)
                print("   screenshot: %s/%s.png" % (SHOTS, name))
                time.sleep(0.5)
                continue
            print("\n== %s: createMessageBox(parent, 0, 1, %s)"
                  % (name, ", ".join(repr(a)[:24] for a in args)))
            try:
                box = toolkit.createMessageBox(parent, 0, _OK, *args)
            except Exception as error:
                print("   createMessageBox raised %s: %s"
                      % (type(error).__name__, error))
                continue
            helper = snapshot_and_dismiss(name.replace(" ", "-").replace("/", "-"))
            started = time.time()
            try:
                result = box.execute()
                print("   execute() answered %d after %.1fs"
                      % (result, time.time() - started))
            except Exception as error:
                print("   execute() raised %s: %s" % (type(error).__name__, error))
            finally:
                helper.communicate(timeout=15)
            print("   screenshot: %s/%s.png" % (SHOTS, name.replace(" ", "-")))
            try:
                box.dispose()
            except Exception:
                pass
            time.sleep(0.5)
    finally:
        lo.close(doc)


main()
