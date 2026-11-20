"""Where do control positions have to be set for the settings dialog to lay out?

    python3 dev/debug_dialog_layout.py

Variants, each building the same two-control dialog and printing the peer
geometry:

  1  properties on the control model **before** ``insertByName``
  2  properties on the model **after** ``insertByName`` (what Basic does)
  3  ``insertByName`` with a ``sequence<PropertyValue>`` incl. ``Servicename``
  4  like 2, plus ``PosSizeMapMode`` = MAP_PIXEL on the dialog model
  5  like 2, with a parent window created from a WindowDescriptor
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
EDIT = "com.sun.star.awt.UnoControlEditModel"
BUTTON = "com.sun.star.awt.UnoControlButtonModel"
GEOMETRY = (("PositionX", 3000), ("PositionY", 2000), ("Width", 5000), ("Height", 800))


def new_dialog():
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    return dialog, model


def pvs(pairs):
    return tuple(uno.createUnoStruct("com.sun.star.beans.PropertyValue", Name=n, Value=v)
                 for n, v in pairs)


def describe(error):
    return "%s: %s" % (type(error).__name__, str(error)[:90])


def report(dialog, model, label, notes):
    print("== %s" % label)
    for note in notes:
        print("   %s" % note)
    try:
        size = dialog.getPosSize()
        print("   dialog peer %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
    except Exception as error:
        print("   dialog peer %s" % describe(error))
    for name in ("e1", "b1"):
        try:
            child = model.getByName(name)
            props = []
            for pname in ("PositionX", "PositionY", "Width", "Height"):
                try:
                    props.append("%s=%s" % (pname, child.getPropertyValue(pname)))
                except Exception as error:
                    props.append("%s=%s" % (pname, type(error).__name__))
            print("   %-3s model %s" % (name, " ".join(props)))
        except Exception as error:
            print("   %-3s model missing (%s)" % (name, describe(error)))
        try:
            peer = dialog.getControl(name).getPosSize()
            print("       peer  %dx%d at %d,%d" % (peer.Width, peer.Height, peer.X, peer.Y))
        except Exception as error:
            print("       peer  %s" % describe(error))


def make_control(service, props, before=True):
    model = MANAGER.createInstanceWithContext(service, CTX)
    if before:
        for name, value in props:
            model.setPropertyValue(name, value)
    return model


def variant_1():
    dialog, model = new_dialog()
    notes = []
    for name, service, text in (("e1", EDIT, "hello"), ("b1", BUTTON, "OK")):
        control = make_control(service, GEOMETRY + (("Text" if service == EDIT else "Label", text),))
        try:
            model.insertByName(name, control)
        except Exception as error:
            notes.append("insertByName %s -> %s" % (name, describe(error)))
    report(dialog, model, "1: properties before insertByName", notes)
    dialog.dispose()


def variant_2():
    dialog, model = new_dialog()
    notes = []
    for name, service, text in (("e1", EDIT, "hello"), ("b1", BUTTON, "OK")):
        control = make_control(service, ())
        try:
            model.insertByName(name, control)
        except Exception as error:
            notes.append("insertByName -> %s" % describe(error))
            continue
        child = model.getByName(name)
        for pname, value in GEOMETRY:
            try:
                child.setPropertyValue(pname, value)
            except Exception as error:
                notes.append("%s.%s -> %s" % (name, pname, describe(error)))
        try:
            child.setPropertyValue("Text" if service == EDIT else "Label", text)
        except Exception as error:
            notes.append("%s.text -> %s" % (name, describe(error)))
    report(dialog, model, "2: properties after insertByName", notes)
    dialog.dispose()


def variant_3():
    dialog, model = new_dialog()
    notes = []
    for name, service, text in (("e1", EDIT, "hello"), ("b1", BUTTON, "OK")):
        pairs = [("Servicename", service[:-5]),
                 (("Text" if service == EDIT else "Label"), text)]
        pairs += list(GEOMETRY)
        try:
            model.insertByName(name, pvs(pairs))
        except Exception as error:
            notes.append("insertByName(props) -> %s" % describe(error))
    report(dialog, model, "3: insertByName with PropertyValue[]", notes)
    dialog.dispose()


def variant_4():
    dialog, model = new_dialog()
    notes = []
    try:
        model.setPropertyValue("PosSizeMapMode", 0)  # com.sun.star.map.MapMode.NONE
    except Exception as error:
        notes.append("PosSizeMapMode -> %s" % describe(error))
    for name, service, text in (("e1", EDIT, "hello"), ("b1", BUTTON, "OK")):
        control = make_control(service, ())
        model.insertByName(name, control)
        child = model.getByName(name)
        for pname, value in GEOMETRY:
            try:
                child.setPropertyValue(pname, value)
            except Exception as error:
                notes.append("%s.%s -> %s" % (name, pname, describe(error)))
    report(dialog, model, "4: after-insert + PosSizeMapMode", notes)
    dialog.dispose()


def variant_5():
    dialog, model = new_dialog()
    notes = []
    descriptor = uno.createUnoStruct("com.sun.star.awt.WindowDescriptor")
    notes.append("WindowDescriptor fields: %s" %
                 [f for f in dir(descriptor) if not f.startswith("_")])
    descriptor.Type = 0
    try:
        descriptor.Rect = uno.createUnoStruct("com.sun.star.awt.Rectangle",
                                              200, 100, 700, 500)
    except Exception as error:
        notes.append("Rect -> %s" % describe(error))
    try:
        descriptor.PosSize = 3
    except Exception as error:
        notes.append("PosSize -> %s" % describe(error))
    toolkit = MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)
    try:
        parent = toolkit.createWindow(descriptor)
    except Exception as error:
        notes.append("createWindow -> %s" % describe(error))
        report(dialog, model, "5: with parent window", notes)
        dialog.dispose()
        return
    for name, service, text in (("e1", EDIT, "hello"), ("b1", BUTTON, "OK")):
        control = make_control(service, ())
        model.insertByName(name, control)
        child = model.getByName(name)
        for pname, value in GEOMETRY:
            try:
                child.setPropertyValue(pname, value)
            except Exception as error:
                notes.append("%s.%s -> %s" % (name, pname, describe(error)))
    try:
        dialog.createPeer(toolkit, parent)
    except Exception as error:
        notes.append("createPeer(parent) -> %s" % describe(error))
    report(dialog, model, "5: properties after insert + our parent window", notes)
    dialog.dispose()
    try:
        parent.dispose()
    except Exception:
        pass


def main():
    variant_1()
    variant_2()
    variant_3()
    variant_4()
    variant_5()


if __name__ == "__main__":
    main()
