"""Every remaining way to give an AWT control a size - measured, not guessed.

    python3 dev/debug_dialog_size.py

Positions reach the peer via ``XControl::setPosSize``, sizes do not, and
``insertByName`` with a ``PropertyValue[]`` is refused, so the settings dialog
collapses to a pile in the corner.  Each variant is printed with the peer
geometry it produced; the one that reports ``SIZE OK`` is the one to use.
"""
import sys

ROOT = "/tmp/opencode/planimpress/plan-impress"
sys.path.insert(0, ROOT + "/dev")
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
EDIT = "com.sun.star.awt.UnoControlEdit"
EDIT_MODEL = EDIT + "Model"
WANT = (120, 40, 260, 34)


def pvs(pairs):
    return tuple(uno.createUnoStruct("com.sun.star.beans.PropertyValue", Name=n, Value=v)
                 for n, v in pairs)


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:70])


def fresh():
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    return dialog, model


def peer_of(dialog, name):
    try:
        peer = dialog.getControl(name).getPosSize()
        return (peer.X, peer.Y, peer.Width, peer.Height)
    except Exception as error:
        return detail(error)


def report(label, dialog, name, notes=()):
    got = peer_of(dialog, name)
    verdict = ""
    if isinstance(got, tuple):
        ok_pos = got[0] == WANT[0] and got[1] == WANT[1]
        ok_size = got[2] == WANT[2] and got[3] == WANT[3]
        verdict = "POSITION %s, SIZE %s" % ("OK" if ok_pos else "no",
                                            "OK" if ok_size else "no")
    print("%-42s %-34s %s" % (label, got, verdict))
    for note in notes:
        print("      %s" % note)


def insert_object(model, name, service, props=()):
    control_model = MANAGER.createInstanceWithContext(service, CTX)
    notes = []
    for pname, value in props:
        try:
            control_model.setPropertyValue(pname, value)
        except Exception as error:
            notes.append("set %s -> %s" % (pname, detail(error)))
    model.insertByName(name, control_model)
    return notes


def variant_setpossize(flag):
    dialog, model = fresh()
    insert_object(model, "c", EDIT_MODEL, (("Text", "hello"),))
    dialog.createPeer(MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX), None)
    x, y, w, h = WANT
    notes = []
    if flag == 3:
        dialog.getControl("c").setPosSize(x, y, w, h, 3)
    else:
        try:
            dialog.getControl("c").setPosSize(0, 0, w, h, 2)   # SIZE only
        except Exception as error:
            notes.append("SIZE pass -> %s" % detail(error))
        try:
            dialog.getControl("c").setPosSize(x, y, 0, 0, 1)   # POS only
        except Exception as error:
            notes.append("POS pass -> %s" % detail(error))
    report("setPosSize flag=%d" % flag, dialog, "c", notes)
    dialog.dispose()


def variant_setpossize_twice():
    dialog, model = fresh()
    insert_object(model, "c", EDIT_MODEL, (("Text", "hello"),))
    dialog.createPeer(MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX), None)
    x, y, w, h = WANT
    for _round in range(3):
        dialog.getControl("c").setPosSize(x, y, w, h, 3)
    report("setPosSize three times", dialog, "c")
    dialog.dispose()


def variant_control_properties():
    dialog, model = fresh()
    insert_object(model, "c", EDIT_MODEL, (("Text", "hello"),))
    dialog.createPeer(MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX), None)
    x, y, w, h = WANT
    dialog.getControl("c").setPosSize(x, y, w, h, 3)
    notes = []
    for target, label in ((dialog.getControl("c"), "control"),
                          (model.getByName("c"), "child model")):
        for pname, value in (("Width", w), ("Height", h)):
            try:
                target.setPropertyValue(pname, value)
            except Exception as error:
                notes.append("%s.%s -> %s" % (label, pname, detail(error)))
    report("setPosSize + setProperty Width/Height", dialog, "c", notes)
    dialog.dispose()


def variant_create_with_arguments():
    """The container's own factory: it knows how to build a control model."""
    for service in (EDIT, EDIT_MODEL):
        dialog, model = fresh()
        notes = []
        pairs = [("Text", "hello"), ("PositionX", WANT[0]), ("PositionY", WANT[1]),
                 ("Width", WANT[2]), ("Height", WANT[3])]
        child = None
        try:
            child = model.createInstanceWithArguments(service, pvs(pairs))
            notes.append("createInstanceWithArguments ok")
        except Exception as error:
            notes.append("createInstanceWithArguments -> %s" % detail(error))
        if child is not None:
            try:
                model.insertByName("c", child)
            except Exception as error:
                notes.append("insertByName(obj) -> %s" % detail(error))
        else:
            try:
                model.insertByName("c", pvs([("Servicename", service)] + pairs))
                notes.append("insertByName(props) ok")
            except Exception as error:
                notes.append("insertByName(props) -> %s" % detail(error))
        dialog.createPeer(MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX),
                          None)
        report("container factory: %s" % service.split(".")[-1], dialog, "c", notes)
        dialog.dispose()


def variant_layout_container():
    notes = []
    for module, name in (("com.sun.star.awt", "XLayoutContainer"),
                         ("com.sun.star.ui.layout", "XLayoutContainer")):
        try:
            module_object = __import__(module, fromlist=[name])
            interface = getattr(module_object, name)
            notes.append("%s.%s members: %s" % (module, name,
                                                [m for m in dir(interface)
                                                 if not m.startswith("_")][:8]))
        except Exception as error:
            notes.append("%s.%s -> %s" % (module, name, detail(error)))
    print("interface availability for XLayoutContainer:")
    for note in notes:
        print("      %s" % note)


def main():
    variant_setpossize(3)
    variant_setpossize(2)
    variant_setpossize_twice()
    variant_control_properties()
    variant_create_with_arguments()
    variant_layout_container()


if __name__ == "__main__":
    main()
