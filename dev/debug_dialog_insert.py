"""Every spelling of ``UnoControlDialogModel.insertByName`` that might work.

    python3 dev/debug_dialog_insert.py

``XNameContainer.insertByName`` has two accepted value shapes: an
``XControlModel`` object (works, but the children expose no geometry) and a
``sequence<com.sun.star.beans.PropertyValue>`` carrying a ``Servicename`` (the
documented way, which is the one that raises ``IllegalArgumentException``).
This script walks the spellings - control service vs model service, list vs
tuple vs ``uno.Any`` - and prints the exact failure of each.
"""
import sys

ROOT = "/tmp/opencode/planimpress/plan-impress"
sys.path.insert(0, ROOT + "/dev")
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
FIELDS = ("PositionX", "PositionY", "Width", "Height")


def detail(error):
    parts = [type(error).__name__, repr(str(error)[:70])]
    for attribute in ("Message", "Reason", "PropertyName", "SequenceLength",
                      "SequenceIndex"):
        value = getattr(error, attribute, None)
        if value not in (None, 0, ""):
            parts.append("%s=%r" % (attribute, value))
    return " ".join(parts)


def props(pairs):
    out = []
    for name, value in pairs:
        prop = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        prop.Name = name
        prop.Value = value
        out.append(prop)
    return out


def build(service, extra, peer_first=False):
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    if peer_first:
        # UnoControlContainerModel::insertByName(Sequence<PropertyValue>) has to
        # create the control model through the control implementation, which may
        # need the peer - that is the suspicion being tested here.
        toolkit = MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)
        dialog.createPeer(toolkit, None)
    pairs = [("Servicename", service)] + extra + [
        ("PositionX", 2000), ("PositionY", 1000), ("Width", 6000), ("Height", 900)]
    return dialog, model, pairs


def check(dialog, model, label):
    try:
        child = model.getByName("c")
    except Exception as error:
        print("  %-46s -> no child (%s)" % (label, detail(error)))
        return
    geometry = []
    for name in FIELDS:
        try:
            geometry.append("%s=%s" % (name, child.getPropertyValue(name)))
        except Exception as error:
            geometry.append("%s=%s" % (name, type(error).__name__))
    try:
        peer = dialog.getControl("c").getPosSize()
        peer_text = "peer %dx%d at %d,%d" % (peer.Width, peer.Height, peer.X, peer.Y)
    except Exception as error:
        peer_text = "peer %s" % type(error).__name__
    print("  %-46s -> %s | %s" % (label, " ".join(geometry), peer_text))


def try_props(label, service, extra, wrap=None, peer_first=False):
    dialog, model, pairs = build(service, extra, peer_first=peer_first)
    value = props(pairs)
    if wrap is not None:
        value = wrap(value)
    try:
        model.insertByName("c", value)
    except Exception as error:
        print("  %-46s -> %s" % (label, detail(error)))
    else:
        try:
            dialog.createPeer(MANAGER.createInstanceWithContext(
                "com.sun.star.awt.Toolkit", CTX), None)
        except Exception as error:
            print("  (peer: %s)" % detail(error))
        check(dialog, model, label)
    try:
        dialog.dispose()
    except Exception:
        pass


def try_object(label, service):
    dialog, model, _pairs = build(service, [])
    control = MANAGER.createInstanceWithContext(service, CTX)
    for name, value in (("PositionX", 2000), ("PositionY", 1000),
                        ("Width", 6000), ("Height", 900)):
        try:
            control.setPropertyValue(name, value)
        except Exception as error:
            print("  %-46s set %s -> %s" % (label, name, detail(error)))
    try:
        model.insertByName("c", control)
    except Exception as error:
        print("  %-46s -> %s" % (label, detail(error)))
    else:
        try:
            dialog.createPeer(MANAGER.createInstanceWithContext(
                "com.sun.star.awt.Toolkit", CTX), None)
        except Exception:
            pass
        check(dialog, model, label)
    try:
        dialog.dispose()
    except Exception:
        pass


def main():
    control = "com.sun.star.awt.UnoControlEdit"
    model_service = "com.sun.star.awt.UnoControlEditModel"
    text = [("Text", "hello")]

    print("PropertyValue[] forms:")
    try_props("control service, list", control, text)
    try_props("model service, list", model_service, text)
    try_props("control service, tuple", control, text, wrap=lambda v: tuple(v))
    try_props("model service, tuple", model_service, text, wrap=lambda v: tuple(v))
    try_props("control service, uno.Any seq", control, text,
              wrap=lambda v: uno.Any("[]com.sun.star.beans.PropertyValue", tuple(v)))
    try_props("model service, uno.Any seq", model_service, text,
              wrap=lambda v: uno.Any("[]com.sun.star.beans.PropertyValue", tuple(v)))
    try_props("control service, no geometry", control, text,
              wrap=lambda v: tuple(p for p in v if p.Name not in FIELDS))
    try_props("model service, no geometry", model_service, text,
              wrap=lambda v: tuple(p for p in v if p.Name not in FIELDS))

    print("XControlModel object forms:")
    try_object("model service object, props before insert", model_service)
    try_object("control model service object, no props", "com.sun.star.awt.UnoControlEditModel")

    print("PropertyValue[] forms, peer created first:")
    try_props("control service, list, peer first", control, text, peer_first=True)
    try_props("model service, list, peer first", model_service, text, peer_first=True)
    try_props("control service, uno.Any seq, peer first", control, text,
              wrap=lambda v: uno.Any("[]com.sun.star.beans.PropertyValue", tuple(v)),
              peer_first=True)
    try_props("control service, no geometry, peer first", control, text,
              wrap=lambda v: tuple(p for p in v if p.Name not in FIELDS),
              peer_first=True)


if __name__ == "__main__":
    main()
