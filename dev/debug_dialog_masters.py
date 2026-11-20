"""Filling and pre-selecting the master-slide list box, and where settings land.

    python3 dev/debug_dialog_masters.py

Three things the settings dialog needs and that the model alone cannot answer:

* does ``StringItemList`` reach a list box whose model came from the dialog
  model's factory, and does the *selection* survive?  Selecting on the model
  (``SelectedItems``) is what the old code did; ``XItemList.selectItemPos`` needs
  the peer, so both are tried and both are reported.
* what ``_master_names``-style code sees for the fixture document.
* where ``config._profile_dir`` puts its files - the extension must write to the
  profile of the office it runs in, not to a hard-coded default.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import config  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
LISTBOX = "com.sun.star.awt.UnoControlListBoxModel"


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:70])


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=True)
    try:
        masters = doc.MasterPages
        names = [masters.getByIndex(i).Name for i in range(masters.Count)]
        print("document masters      : %s" % names)
    finally:
        lo.close(doc)

    dialog = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialog", ctx)
    model = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    dialog.setModel(model)
    child = model.createInstance(LISTBOX)
    uno.invoke(child, "setPropertyValues",
               (("StringItemList", "Dropdown", "PositionX", "PositionY", "Width", "Height"),
                (uno.Any("[]string", tuple(names)), True, 10, 10, 60, 14)))
    print("StringItemList written  : %s" % detail(Exception("n/a")) if False else "")
    try:
        print("StringItemList read back: %s"
              % (tuple(child.getPropertyValue("StringItemList")),))
    except Exception as error:
        print("StringItemList read back: %s" % detail(error))
    for value in ((0,), (1,)):
        try:
            child.setPropertyValue("SelectedItems", uno.Any("[]short", value))
            print("model SelectedItems=%s : accepted" % (value,))
        except Exception as error:
            print("model SelectedItems=%s : %s" % (value, detail(error)))
    model.insertByName("Master", child)
    model.setPropertyValue("Width", 140)
    model.setPropertyValue("Height", 60)

    toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    control = dialog.getControl("Master")
    for method, args in (("getItemCount", None), ("getSelectedItemPos", None),
                         ("getSelectedItems", None)):
        try:
            print("peer %-19s : %s" % (method, getattr(control, method)(*args or ())))
        except Exception as error:
            print("peer %-19s : %s" % (method, detail(error)))
    for attempt in ("selectItemPos", "selectItems"):
        try:
            if attempt == "selectItemPos":
                control.selectItemPos(0)
            else:
                control.selectItems(uno.Any("[]short", (0,)), False)
            print("peer %-19s : accepted -> selected %s at %s"
                  % (attempt, list(control.getSelectedItems()),
                     list(control.getSelectedItemPos())))
        except Exception as error:
            print("peer %-19s : %s" % (attempt, detail(error)))
    dialog.dispose()

    print("config._profile_dir     : %s" % config._profile_dir(ctx))
    print("   expected              : %s" % os.path.join(ROOT, "loprofile", "user"))


if __name__ == "__main__":
    main()
