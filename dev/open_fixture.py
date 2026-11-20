"""Open the fixture presentation in the development office and report its window.

    python3 dev/open_fixture.py

Used by the click-by-click check of the settings dialog: it leaves a real
Impress window on the display, prints its geometry and the settings file path,
so the menu can be driven with ``xdotool`` and screenshotted with ``scrot``.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    window = None
    try:
        window = doc.CurrentController.Frame.ContainerWindow
    except Exception as error:
        print("no container window: %s" % error)
    if window is not None:
        for name, value in (("Maximized", True), ("PosSizeMapMode", 0)):
            try:
                window.setPropertyValue(name, value)
                print("ContainerWindow.%s = %s" % (name, value))
            except Exception as error:
                print("ContainerWindow.%s -> %s" % (name, type(error).__name__))
        try:
            window.setVisible(True)
            geometry = window.getPosSize()
            print("frame window: %dx%d at %d,%d"
                  % (geometry.Width, geometry.Height, geometry.X, geometry.Y))
        except Exception as error:
            print("window geometry -> %s" % error)
    print("title     : %s" % doc.Title)
    print("slides    : %d" % doc.DrawPages.Count)
    print("profile   : %s" % os.path.join(ROOT, "loprofile", "user", "planimpress"))
    print("settings  : %s" % os.path.join(ROOT, "loprofile", "user", "planimpress",
                                          "settings.json"))


if __name__ == "__main__":
    main()
