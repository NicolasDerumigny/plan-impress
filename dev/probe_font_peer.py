"""Where exactly the font list can be asked for, and when it must not be.  (debug)

    DISPLAY=:98 python3 dev/probe_font_peer.py

The five steps of :func:`plan_impress.dialog.installed_fonts` - create the dialog,
create its model, ``setModel``, ``createPeer``, ``getFontDescriptors`` - are printed
one per line with a wall-clock time against each, three times: with no document, with
one open, and after it has been closed.  All three answer 4701 descriptors in about
0.1 s, so the hang the settings dialog once showed before it ever appeared is **not**
in these lines: it is in *when* the peer is created.  A second top-level window while
a menu popup holds the pointer grab wedges the client, which is what
``dev/measure_text.py`` (it opens the *Plan* menu first) died on - see
``dev/probe_font_menu.py`` for that one.  ``SettingsDialog._fill_fonts`` is the
version that asks the dialog's own peer; ``dev/probe_font_items.py`` is its measure.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

START = time.time()


def say(*args):
    print("%6.1fs %s" % ((time.time() - START) % 100000,
                         " ".join("%s" % item for item in args)), flush=True)


def build_with(tools, label, with_document):
    ctx = tools["ctx"]
    manager = ctx.ServiceManager
    say(label, "createInstance dialog")
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    say(label, "createInstance model")
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    say(label, "setModel")
    dialog.setModel(model)
    # (a model.setPropertyValue("Visible", False) here is what hung the client:
    # see the note in plan_impress/dialog.py::installed_fonts)
    say(label, "createPeer")
    dialog.createPeer(tools["toolkit"], None)
    say(label, "getPeer")
    peer = dialog.getPeer()
    say(label, "getFontDescriptors")
    descriptors = peer.getFontDescriptors()
    say(label, "->", len(descriptors), "descriptors")
    say(label, "dispose")
    dialog.dispose()
    say(label, "disposed")


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx)
    tools = {"ctx": ctx, "toolkit": toolkit}
    build_with(tools, "[no document]", False)

    doc = lo.open_doc(desk, os.path.join(ROOT, "tests", "fixtures", "sections.odp"),
                      hidden=False)
    say("document open:", doc.DrawPages.Count, "slides")
    build_with(tools, "[document open]", False)
    lo.close(doc)
    say("document closed")
    build_with(tools, "[after close]", False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
