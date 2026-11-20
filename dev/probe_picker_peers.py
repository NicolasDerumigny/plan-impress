#!/usr/bin/env python3
"""Model rectangles next to the pixels the peers actually occupy.

The picker is judged by how it looks, and the two can disagree: a control's
rectangle is a *model* property, the peer is what is painted.  This opens the
chooser the way the settings dialog does and prints both, so "the buttons are
not flush with the grid" can be traced to whichever of the two is lying.
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
from plan_impress import palettes, picker  # noqa: E402


def main():
    names = palettes.load_palettes()
    p = picker.ColourPicker(lo.connect(), names, current=0x1F4E79,
                            title="Heading colour",
                            recent=[("#112233", 0x112233)])
    p.build()
    p.show()
    time.sleep(1.0)
    print("%-10s %-24s %s" % ("control", "model (units)", "peer (px)"))
    for name in p.model.ElementNames:
        model = p.model.getByName(name)
        try:
            model_rect = tuple(int(getattr(model, k)) for k in
                               ("PositionX", "PositionY", "Width", "Height"))
        except Exception as error:
            model_rect = str(error)
        try:
            peer = p.control(name).getPeer()
            rect = peer.getPosSize()
            peer_rect = (rect.X, rect.Y, rect.Width, rect.Height)
        except Exception as error:
            peer_rect = "%s: %s" % (type(error).__name__, error)
        print("%-10s %-24s %s" % (name, model_rect, peer_rect))
    try:
        print("window peer: %s" % (p.dialog.getPeer().getPosSize(),))
    except Exception as error:
        print("window peer: %s" % error)
    p.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
