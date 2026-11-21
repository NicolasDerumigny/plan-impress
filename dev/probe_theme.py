#!/usr/bin/env python3
"""What the office's theme settings mean, and what a light theme paints.

    DISPLAY=:98 python3 dev/probe_theme.py

A swatch needs a line round it that contrasts with the dialog, so something has to say
whether the dialog is dark.  ``/org.openoffice.Office.Common/Appearance`` is the only
node here that will answer at all (``/Common/Theme`` and ``/Common/VCL/Properties``
raise, and the toolkit has no ``getSettings``/``XStyleFacility`` -
``dev/probe_border_colour.py``), and on this office it says::

    ApplicationAppearance 0     LibreOfficeTheme 0

which is "follow the system": the dark grey the dialogs are painted in
(``#383C4A``, measured in ``dev/probe_border_colour.py``) comes from
``~/.config/gtk-3.0/settings.ini``, ``gtk-application-prefer-dark-theme=1`` and
``gtk-theme-name=Arc-Dark``.  So two things have to be measured, and neither can be
asserted on:

  * **which number is which.** The office's own option (Tools ▸ Options ▸ LibreOffice ▸
    Colors, "Application Appearance") writes ``Light``/``Dark`` somewhere, and only a
    screenshot can say whether ``1`` is the light one or the dark one.  Each value is
    therefore *written*, a dialog put up afterwards, and the dialog's own background
    sampled from the shot: a light theme paints a light dialog, and that is the
    evidence, not a name.  The value is put back at the end.
  * **whether the change is visible without a restart.** If it is not, the numbers are
    worth nothing to a widget that is being built now, and the file hints are the only
    signal.

Run it twice: once to measure, once after it has restored the setting to be sure the
office is as it was.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import dev.lo as lo  # noqa: E402
import numpy  # noqa: E402
from PIL import Image  # noqa: E402

TITLE = "plan-impress theme probe"
SHOT = os.environ.get("PROBE_SHOT", "/tmp/opencode/theme")
VALUES = (0, 1, 2)


def read_appearance(ctx):
    """The office's own answer, and its real type."""
    from com.sun.star.beans import PropertyValue
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx)
    node = PropertyValue()
    node.Name = "Nodepath"
    node.Value = "/org.openoffice.Office.Common/Appearance"
    read = PropertyValue()
    read.Name = "ReadOnly"
    read.Value = True
    view = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationAccess", (node, read))
    return dict((name, view.getByName(name)) for name in view.ElementNames)


def write_appearance(ctx, key, value):
    """Write one Appearance item the way the office's own option page does."""
    from com.sun.star.beans import PropertyValue
    provider = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", ctx)
    node = PropertyValue()
    node.Name = "Nodepath"
    node.Value = "/org.openoffice.Office.Common/Appearance"
    update = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdate", (node,))
    update.setPropertyValue(key, value)
    update.commitChanges()
    return read_appearance(ctx).get(key)


def dialog_background(ctx, manager):
    """Put up a dialog and return the colour its own background paints in.

    The dialog's *peer* will not say what colour it is (fact 46), so the answer comes
    from the screen: the window is found by its title through ``xdotool`` - the peer
    answers ``0,0`` (fact 76) - and the middle of its bottom strip, where no control
    is, is sampled.
    """
    dialog = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    model = manager.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel",
                                              ctx)
    dialog.setModel(model)
    label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    for property_name, value in (("Label", "theme"), ("PositionX", 6),
                                 ("PositionY", 6), ("Width", 30), ("Height", 8)):
        label.setPropertyValue(property_name, value)
    model.insertByName("label", label)
    model.setPropertyValue("Width", 60)
    model.setPropertyValue("Height", 40)
    model.setPropertyValue("Title", TITLE)
    toolkit = manager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    dialog.createPeer(toolkit, None)
    dialog.setVisible(True)
    time.sleep(1.2)
    shot = os.path.join(SHOT, "dialog.png")
    os.spawnv(os.P_WAIT, "/usr/bin/sh",
              ["/usr/bin/sh", "-c", "scrot -o %s 2>>%s"
               % (shot, os.path.join(SHOT, "scrot.log"))])
    image = Image.open(shot).convert("RGB")
    colour = None
    try:
        found = subprocess.run(["xdotool", "search", "--name", TITLE],
                               capture_output=True, text=True, timeout=10).stdout
        win = found.split()[0]
        shell = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win],
                               capture_output=True, text=True, timeout=10).stdout
        values = dict(line.split("=", 1) for line in shell.splitlines() if "=" in line)
        x, y = int(values["X"]), int(values["Y"])
        width, height = int(values["WIDTH"]), int(values["HEIGHT"])
        strip = numpy.asarray(image.crop((x + 4, y + height - 8,
                                          x + width - 4, y + height - 4)))
        # the mode of the strip: the window's own colour, whatever the theme paints
        colours, counts = numpy.unique(strip.reshape(-1, strip.shape[-1]),
                                       axis=0, return_counts=True)
        colour = tuple(int(v) for v in colours[counts.argmax()])
        print("   window %dx%d at %d,%d, background #%02X%02X%02X"
              % (width, height, x, y, colour[0], colour[1], colour[2]))
    except Exception as error:
        print("   background: %s: %s" % (error.__class__.__name__, error))
    dialog.dispose()
    return colour


def main():
    if not os.path.isdir(SHOT):
        os.makedirs(SHOT)
    ctx = lo.connect()
    manager = ctx.ServiceManager
    print("-- what the office says now")
    before = read_appearance(ctx)
    print("   %s" % dict((key, before[key]) for key in sorted(before)))
    for key in ("ApplicationAppearance", "LibreOfficeTheme"):
        if key not in before:
            print("   %s: absent" % key)
            continue
        print("-- %s" % key)
        for value in VALUES:
            try:
                written = write_appearance(ctx, key, value)
            except Exception as error:
                print("   %-3s write: %s: %s" % (key, error.__class__.__name__,
                                                 str(error).splitlines()[0][:70]))
                continue
            print("   %s=%s read back %r" % (key, value, written))
            dialog_background(ctx, manager)
        try:
            write_appearance(ctx, key, before[key])
        except Exception as error:
            print("   restore %s: %s" % (key, error.__class__.__name__))
    print("-- restored to %s" % (read_appearance(ctx),))
    print("-- the file hints the office itself reads")
    for path in ("~/.config/gtk-3.0/settings.ini", "~/.gtkrc-2.0",
                 "~/.config/kdeglobals"):
        real = os.path.expanduser(path)
        if not os.path.exists(real):
            print("   %s: absent" % path)
            continue
        words = ("dark", "theme", "contrast", "color scheme")
        keep = [line.strip() for line in open(real, errors="replace")
                if any(word in line.lower() for word in words)]
        print("   %-34s %s" % (path, keep[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
