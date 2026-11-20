#!/usr/bin/env python3
"""What font do the settings dialog's controls really render with?

    DISPLAY=:98 python3 dev/debug_font.py

Prints the font descriptor of a label and of a field, plus whatever the office
configuration says about UI fonts, so the dialog can be matched to the menu
text instead of guessed at.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402


def show(where, descriptor):
    if descriptor is None:
        print("%-32s -> <none>" % where)
        return
    try:
        print("%-32s -> %s" % (where, dict(descriptor)))
    except Exception:
        print("%-32s -> %s" % (where, descriptor))


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, os.path.join(ROOT, "tests/fixtures/sections.odp"),
                      hidden=True)

    cfg = ctx.ServiceManager.createInstance(
        "com.sun.star.configuration.ConfigurationProvider")
    for path in ("/org.openoffice.Office.Common/View",
                 "/org.openoffice.Office.Common/VCL"):
        try:
            node = lo.pv("Nodepath", path)
            access = cfg.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationAccess", (node,))
            print("== %s" % path)
            for name in access.ElementNames:
                value = getattr(access, name, None)
                if isinstance(value, (int, float, bool)) or isinstance(value, str):
                    print("   %-28s %s" % (name, value))
        except Exception as exc:
            print("%s: %s %s" % (path, exc.__class__.__name__, exc))

    from plan_impress import config, dialog
    settings = dict(config.DEFAULTS)
    settings.update({"muted_color": 0xC0504D, "title": "Plan"})
    box = dialog.SettingsDialog(ctx, settings, ["Master 1", "Master 2"])
    box.build()
    box._peer()
    for name in ("title_label", "title_field", "master_list"):
        control = box.control(name)
        for attr in ("FontDescriptor", "FontHeight", "FontName"):
            try:
                show("control %s.%s" % (name, attr), getattr(control, attr, None))
            except Exception as exc:
                print("control %s.%s -> %s" % (name, attr, exc.__class__.__name__))
    box.dispose()
    lo.close(doc)


if __name__ == "__main__":
    main()
