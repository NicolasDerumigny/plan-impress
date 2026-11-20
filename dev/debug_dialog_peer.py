"""Positioning the settings dialog through ``XControl.setPosSize`` (debug helper).

    python3 dev/debug_dialog_peer.py            # measure only
    python3 dev/debug_dialog_peer.py show 6     # stay visible for 6 s (screenshot it)

``XNameContainer.insertByName`` on an ``UnoControlDialogModel`` keeps the
control-specific properties (``Text``, ``Label``, ``StringItemList``) but the
children expose no ``PositionX``/``Width`` at all, so every control lands at
0,0.  ``XControl::setPosSize`` works on the peer instead, in **pixels**; this
script checks that the geometry then really reaches the screen.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
from plan_impress import config, dialog  # noqa: E402

POS_SIZE = 3  # com.sun.star.awt.PosSize.POS | SIZE

# Pixel layout of the same form the dialog shows.
LAYOUT = {
    "labelMutedColor": (14, 14, 200, 18),
    "MutedColor": (222, 12, 70, 22),
    "swatchMutedColor": (300, 12, 40, 22),
    "labelTextColor": (14, 44, 200, 18),
    "TextColor": (222, 42, 70, 22),
    "swatchTextColor": (300, 42, 40, 22),
    "labelTitle": (14, 74, 200, 18),
    "Title": (222, 72, 118, 22),
    "labelMaster": (14, 104, 200, 18),
    "Master": (222, 102, 118, 24),
    "ok": (150, 150, 90, 28),
    "cancel": (248, 150, 90, 28),
}


def main():
    show_for = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "show" else 0.0
    ctx = lo.connect()
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx)
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0x00FF00, "text_color": 0x1F6EC8,
                     "title": "Agenda", "master": "Master2"})
    window = dialog.SettingsDialog(ctx, settings, ["Master1", "Master2"])
    window.build()
    try:
        window.dialog.createPeer(toolkit, None)
        window.dialog.setTitle("Plan Impress")
        try:
            window.dialog.setPosSize(120, 90, 400, 205, POS_SIZE)
            print("dialog.setPosSize ok")
        except Exception as error:
            print("dialog.setPosSize FAILED: %s" % error)
        for name, (x, y, width, height) in LAYOUT.items():
            control = window.control(name)
            try:
                control.setPosSize(x, y, width, height, POS_SIZE)
            except Exception as error:
                print("%-18s setPosSize FAILED %s" % (name, error))
                continue
            got = control.getPosSize()
            ok = (got.X, got.Y, got.Width, got.Height) == (x, y, width, height)
            print("%-18s want %-22s got %-22s %s" % (
                name, "%d,%d %dx%d" % (x, y, width, height),
                "%d,%d %dx%d" % (got.X, got.Y, got.Width, got.Height),
                "OK" if ok else "MISMATCH"))
        size = window.dialog.getPosSize()
        print("dialog peer: %dx%d at %d,%d" % (size.Width, size.Height, size.X, size.Y))
        if show_for:
            window.dialog.setVisible(True)
            print("visible for %g s" % show_for)
            time.sleep(show_for)
    finally:
        window.dispose()


if __name__ == "__main__":
    main()
