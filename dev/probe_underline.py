"""Why does the read-out underline one of its letters, and the captions not?

    DISPLAY=:98 python3 dev/probe_underline.py

The picker's read-out ("#1F4E79") is drawn with a short stroke under one letter,
which reads as a missing glyph.  There is no ``Mnemonic`` or ``Decorative`` property
on a control model built from a dialog model (``dev/probe_mnemonic.py`` prints the
exceptions), so what draws it has to be found by putting candidates next to each
other in a dialog that looks like the picker and photographing the result.

Six rows, each a label plus what follows it, so the comparison is one picture:

1. the read-out as the picker has it - a label directly before the hex field;
2. the same, with an empty label in between: if the office underlines the label *of*
   an edit field - the way a form does - the stroke moves to the empty one;
3. the same, with a space as the empty label, in case an empty label is skipped;
4. the read-out before a button instead of an edit;
5. the read-out alone, nothing after it;
6. a group caption ("Recently used") before the hex field, which the picker shows
   with no stroke at all - the control that says the rule is not "every label".

``scrot`` must run next door and the shot is taken synchronously (fact 74).
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("PLAN_IMPRESS_DATA_DIR",
                      os.path.join(BASE, "loprofile", "user", "planimpress"))

import dev.lo as lo  # noqa: E402

READOUT = " #1F4E79"
CAPTION = "Recently used"
FONT = 12
ROWS = [
    ("before an edit", [(READOUT, "fixed"), ("", "edit")]),
    ("empty label between", [(READOUT, "fixed"), ("", "fixed"), ("", "edit")]),
    ("space label between", [(READOUT, "fixed"), (" ", "fixed"), ("", "edit")]),
    ("before a button", [(READOUT, "fixed"), ("OK", "button")]),
    ("nothing after", [(READOUT, "fixed")]),
    ("caption before an edit", [(CAPTION, "fixed"), ("", "edit")]),
]


def add(model, name, service, props):
    control = model.createInstance("com.sun.star.awt.UnoControl%sModel" % service)
    for property_name, value in props:
        try:
            control.setPropertyValue(property_name, value)
        except Exception as error:
            print("%s.%s: %s" % (name, property_name, error.__class__.__name__))
    model.insertByName(name, control)


def main():
    shot = os.environ.get("PROBE_SHOT", "/tmp/opencode/underline-candidates.png")
    ctx = lo.connect()
    mgr = ctx.ServiceManager
    win = mgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = mgr.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    win.setModel(model)
    y = 4
    for index, (_heading, row) in enumerate(ROWS):
        add(model, "h%d" % index, "FixedText", [
            ("Label", "%d." % (index + 1)), ("PositionX", 2), ("PositionY", y + 3),
            ("Width", 6), ("Height", 9), ("FontHeight", FONT)])
        x = 12
        for order, (text, kind) in enumerate(row):
            name = "r%dc%d" % (index, order)
            props = [("PositionX", x), ("PositionY", y), ("Height", 14),
                     ("FontHeight", FONT)]
            if kind == "fixed":
                props += [("Label", text), ("Width", 34), ("Border", 0)]
            elif kind == "edit":
                props += [("Text", "B0B0B0"), ("Width", 22)]
            else:
                props += [("Label", text), ("Width", 22)]
            add(model, name, {"fixed": "FixedText", "edit": "Edit",
                              "button": "Button"}[kind], props)
            x += 26
        y += 20
    add(model, "ok", "Button", [("Label", "OK"), ("PositionX", 12), ("PositionY", y),
                                ("Width", 26), ("Height", 14),
                                ("FontHeight", FONT), ("DefaultButton", True)])
    add(model, "cancel", "Button", [("Label", "Cancel"), ("PositionX", 42),
                                    ("PositionY", y), ("Width", 26), ("Height", 14),
                                    ("FontHeight", FONT)])
    for name, value in (("Width", 110), ("Height", y + 22)):
        model.setPropertyValue(name, value)
    toolkit = mgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    win.createPeer(toolkit, None)
    win.setTitle("mnemonic candidates")
    win.setVisible(True)
    time.sleep(1.5)
    directory = os.path.dirname(shot)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    log = os.path.join(directory, "scrot.log")
    code = os.spawnv(os.P_WAIT, "/usr/bin/sh",
                     ["/usr/bin/sh", "-c",
                      "scrot -o %s 2>>%s" % (shot, log)])
    for index, (heading, row) in enumerate(ROWS):
        print("%d. %-24s %s" % (index + 1, heading,
                                " + ".join("%s:%r" % (kind, text)
                                           for text, kind in row)))
    print("shot %s -> %d" % (shot, code))
    win.setVisible(False)
    win.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
