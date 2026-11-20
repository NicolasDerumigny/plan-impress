"""Where do the settings dialog's control positions go?

    python3 dev/debug_dialog_geom.py

Prints, for each control, what the **dialog model** holds and what the **peer**
reports, for both ways of giving the dialog a native peer:

  A  ``dialog.createPeer(toolkit, None)``            (no parent window)
  B  ``dialog.createPeer(toolkit, window)``           (our own top-level window)

``XControl::getPosSize`` of the children reported 0,0 for every control in
case A, which is how the dialog ended up as a pile of overlapping widgets in
the top-left corner of the screen.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import config, dialog  # noqa: E402

PROBE = ("labelMutedColor", "MutedColor", "swatchMutedColor", "Master", "ok", "cancel")


def prop(model, name, default=None):
    try:
        return model.getPropertyValue(name)
    except Exception:
        return default


def dump(window, label):
    print("== %s" % label)
    try:
        size = window.dialog.getPosSize()
        print("   dialog peer: %dx%d at %d,%d px" % (size.Width, size.Height,
                                                     size.X, size.Y))
    except Exception as error:
        print("   dialog peer: %s" % type(error).__name__)
    print("   dialog model PosSizeMapMode=%r Title=%r" % (
        prop(window.model, "PosSizeMapMode"), prop(window.model, "Title")))
    for name in PROBE:
        model = window.model.getByName(name)
        control = window.control(name)
        try:
            peer = control.getPosSize()
            peer_text = "%4dx%-4d at %4d,%-4d" % (peer.Width, peer.Height, peer.X, peer.Y)
        except Exception as error:
            peer_text = "no peer (%s)" % type(error).__name__
        print("   %-18s model %4dx%-4d at %4d,%-4d | peer %s" % (
            name,
            prop(model, "Width", -1), prop(model, "Height", -1),
            prop(model, "PositionX", -1), prop(model, "PositionY", -1),
            peer_text))


def build(ctx):
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0x00FF00, "title": "Agenda", "master": "Master2"})
    window = dialog.SettingsDialog(ctx, settings, ["Master1", "Master2"])
    window.build()
    return window


def main():
    ctx = lo.connect()
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx)
    for name in ("getPrimaryScreen", "getScreens", "getScreenPixelsPerMeter"):
        try:
            print("toolkit.%s -> %r" % (name, getattr(toolkit, name)()))
        except Exception as error:
            print("toolkit.%s -> %s" % (name, type(error).__name__))

    window = build(ctx)
    try:
        window.dialog.createPeer(toolkit, None)
        dump(window, "A: createPeer(toolkit, None)")
    finally:
        window.dispose()

    window = build(ctx)
    try:
        descriptor = uno.createUnoStruct("com.sun.star.awt.WindowDescriptor")
        descriptor.Type = 0  # WindowType.TOP
        descriptor.PosSize = 3  # POS | SIZE
        descriptor.X, descriptor.Y = 200, 120
        descriptor.Width, descriptor.Height = 420, 260
        parent = toolkit.createWindow(descriptor)
        window.window = parent
        window.dialog.createPeer(toolkit, parent)
        dump(window, "B: createPeer(toolkit, our top-level window 420x260 px)")
    finally:
        window.dispose()


if __name__ == "__main__":
    main()
