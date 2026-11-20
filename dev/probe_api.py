#!/usr/bin/env python3
"""What colour-picker API does this office expose, and where do palettes come from?

    DISPLAY=:98 python3 dev/probe_api.py [module ...]

Two questions, both answered against the running office rather than from
memory.  First, is there a colour picker to reuse?  `strings` over
``program/types/offapi.rdb`` finds the name ``ColorListBox`` but no
``ColorPicker``/``ColorBox``/``ColorPickerDialog``, so every plausible spelling
is asked for by hierarchical name and the answer is printed.  Second, where does
the font-colour dropdown's palette list come from?  The office keeps its colour
tables in the configuration, which is the one place a hand-built picker can read
the same names and hex values from.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import lo  # noqa: E402
import uno  # noqa: E402

MODULES = ("com.sun.star.awt", "com.sun.star.ui", "com.sun.star.ui.dialogs",
           "com.sun.star.staroffice", "com.sun.star.beans", "com.sun.star.util",
           "com.sun.star.script", "com.sun.star.form", "com.sun.star.report")
NAMES = ("ColorListBox", "XColorListBox", "ColorBox", "ColorPicker",
         "ColorPickerDialog", "UnoControlColorListBoxModel",
         "UnoControlColorBoxModel", "Palette", "XPalette", "ColorTable")
TABLES = ("/org.openoffice.Office.Common/Color/Table",
          "/org.openoffice.Office.Common/Color/Standard",
          "/org.openoffice.Office.Common/View/ColorConfiguration")


def probe_names(manager):
    for module in MODULES:
        for name in NAMES:
            full = "%s.%s" % (module, name)
            try:
                found = manager.hasByHierarchicalName(full)
            except Exception as error:
                print("  %-58s ? %s" % (full, error.__class__.__name__))
                continue
            if found:
                try:
                    description = manager.getByHierarchicalName(full)
                    kind = getattr(description.eClass, "value", description.eClass)
                except Exception as error:
                    kind = "unreadable (%s)" % error.__class__.__name__
                print("  %-58s FOUND %s" % (full, kind))


def read_table(context, path):
    """One configuration node, as name -> value."""
    provider = context.ServiceManager.createInstance(
        "com.sun.star.configuration.ConfigurationProvider")
    try:
        access = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess",
            (lo.pv("Nodepath", path),))
    except Exception as error:
        return "%s %s" % (error.__class__.__name__, error)
    entries = []
    for name in access.getElementNames():
        entries.append((name, getattr(access, name, None)))
    return entries


def main():
    context = lo.connect()
    manager = context.getByName("/singletons/com.sun.star.reflection.theTypeDescriptionManager")
    print("=== colour types in the type repository")
    probe_names(manager)
    print("=== configuration colour tables")
    for path in sys.argv[1:] or TABLES:
        entries = read_table(context, path)
        if isinstance(entries, str):
            print("  %-52s %s" % (path, entries))
            continue
        print("  %-52s %d entries: %s" % (path, len(entries),
                                          ", ".join("%s=%s" % (n, v) for n, v
                                                    in entries[:8])))


if __name__ == "__main__":
    main()
