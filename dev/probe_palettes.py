#!/usr/bin/env python3
"""Where can a hand-built palette picker read palettes from in this office?

    DISPLAY=:98 python3 dev/probe_palettes.py

There is no colour picker service to reuse (see the notes in AGENTS.md), so the
palettes have to come from somewhere the office itself uses.  Three candidates
are checked against the running office and the fixture deck: the configuration
tree under ``/org.openoffice.Office.Common``, the document theme that the
font-colour dropdown shows for a presentation, and the colours the deck actually
paints with.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests/fixtures/sections.odp")
NODES = ("/org.openoffice.Office.Common/View",
         "/org.openoffice.Office.Common/Color",
         "/org.openoffice.Office.Common/Colors/Standard")
TYPES = ("com.sun.star.daming.Theme", "com.sun.star.daming.XTheme",
         "com.sun.star.daming.XTheme2", "com.sun.star.drawing.XMasterPage",
         "com.sun.star.presentation.PresentationDocument")
COLOUR_PROPERTIES = ("FillColor", "CharColor", "LineColor", "CharHighlight",
                     "BackColor", "ShadowColor")


def children(provider, path):
    try:
        access = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess", (lo.pv("Nodepath", path),))
    except Exception as error:
        return "%s: %s" % (error.__class__.__name__, str(error).strip().splitlines()[0])
    return list(access.ElementNames)


def known_types(context):
    manager = context.getByName("/singletons/com.sun.star.reflection.theTypeDescriptionManager")
    for name in TYPES:
        try:
            print("  %-46s %s" % (name, manager.hasByHierarchicalName(name)))
        except Exception as error:
            print("  %-46s ? %s" % (name, error.__class__.__name__))


def walk(shape, found, depth=0):
    """Collect every colour a shape (or its group members) paints with."""
    if depth > 4:
        return
    try:
        grouped = shape.supportsService("com.sun.star.drawing.ShapeGroup")
    except Exception:
        grouped = False
    if grouped:
        for index in range(shape.Count):
            walk(shape.getByIndex(index), found, depth + 1)
        return
    for property_name in COLOUR_PROPERTIES:
        try:
            value = shape.getPropertyValue(property_name)
        except Exception:
            continue
        if isinstance(value, int) and 0 <= value <= 0xFFFFFF:
            found.add(value)


def deck_colours(doc):
    found = set()
    for container in (doc.DrawPages, doc.MasterPages):
        for index in range(container.Count):
            page = container.getByIndex(index)
            for shape_index in range(page.Count):
                walk(page.getByIndex(shape_index), found)
    return sorted(found)


def main():
    context = lo.connect()
    desk = lo.desktop(context)
    provider = context.ServiceManager.createInstance(
        "com.sun.star.configuration.ConfigurationProvider")
    print("=== configuration nodes")
    for node in NODES:
        result = children(provider, node)
        if isinstance(result, str):
            print("  %-46s %s" % (node, result))
        else:
            print("  %-46s %d: %s" % (node, len(result), ", ".join(result[:24])))
    print("=== types in the repository")
    known_types(context)

    doc = lo.open_doc(desk, FIXTURE, hidden=True)
    print("=== master page theme")
    for index in range(doc.MasterPages.Count):
        master = doc.MasterPages.getByIndex(index)
        for method in ("getTargetTheme", "getTheme"):
            try:
                theme_object = getattr(master, method)()
                names = theme_object.getColorNames()
                print("  master %d %s -> %d colours: %s"
                      % (index, method, len(names),
                         ", ".join("%s=%06X" % (n, theme_object.getColor(n))
                                   for n in names[:10])))
                break
            except Exception as error:
                print("  master %d %s -> %s" % (index, method, error.__class__.__name__))
        break
    print("=== colours the deck paints with")
    colours = deck_colours(doc)
    print("  %d distinct: %s" % (len(colours),
                                 " ".join("%06X" % c for c in colours[:24])))
    lo.close(doc)


if __name__ == "__main__":
    main()
