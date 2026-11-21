"""Can this office be asked for its installed fonts?  (debug)

    DISPLAY=:98 python3 dev/probe_fonts.py

The settings dialog wants an editable font field with a list of names beside it,
and there is no ``FontListBox`` in ``offapi.rdb``.  Every route that looks
plausible is printed with what it answers, because the fallback - offering the
fonts the *deck* uses and letting anything be typed - is a different widget and
has to be justified by the office really being mute.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402

from plan_impress import core  # noqa: E402


def report(label, factory, limit=8):
    try:
        value = factory()
    except Exception as error:
        print("  %-38s -> %s: %s" % (label, type(error).__name__, error))
        return None
    if value is None:
        print("  %-38s -> None" % label)
        return None
    try:
        items = [str(v) for v in value]
    except TypeError:
        print("  %-38s -> %r" % (label, value))
        return value
    print("  %-38s -> %d, e.g. %s" % (label, len(items), items[:limit]))
    return items


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    toolkit = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", ctx)

    print("1. asking the office")
    report("Toolkit.getFontDescriptors()", lambda: toolkit.getFontDescriptors())
    dialog = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialog", ctx)
    model = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    dialog.setModel(model)
    dialog.createPeer(toolkit, None)
    peer = dialog.getPeer()
    report("dialog peer.getFontDescriptors()", lambda: peer.getFontDescriptors())
    report("dialog peer.getFont('')", lambda: peer.getFont(""))
    print("  peer 'Device' methods:",
          [name for name in dir(peer) if "Device" in name] or "<none>")

    def device_fonts():
        device = peer.createDevice()
        names = [name for name in dir(device) if "Font" in name]
        print("    device methods:", names or "<none>")
        return device.getDeviceFontEnumeration()

    report("peer.createDevice().getDeviceFontEnumeration()", device_fonts)

    # a *control* peer is an XOutputDevice too, and that is the spelling the
    # Basic wizards use
    combo_model = model.createInstance("com.sun.star.awt.UnoControlComboBoxModel")
    print("  combo model has:",
          [name for name in dir(combo_model) if "Font" in name] or "<none>")

    print("2. what a dialog model can build")
    for service in ("com.sun.star.awt.UnoControlComboBoxModel",
                    "com.sun.star.awt.UnoControlCheckBoxModel",
                    "com.sun.star.awt.UnoControlListBoxModel",
                    "com.sun.star.awt.UnoControlFixedTextModel",
                    "com.sun.star.awt.UnoControlEditModel"):
        try:
            control = model.createInstance(service)
        except Exception as error:
            print("  %-46s -> %s: %s" % (service.split(".")[-1],
                                         type(error).__name__, error))
            continue
        if control is None:
            print("  %-46s -> None" % service.split(".")[-1])
            continue
        names = set(control.getPropertySetInfo().getProperties())
        names = set(p.Name for p in names)
        wanted = ("StringItemList", "Text", "Dropdown", "SelectedItems", "State",
                  "MultiLine", "CheckBox", "ReadOnly", "MaxLen", "FontHeight",
                  "SymbolSet", "ThreeState")
        print("  %-46s -> %s" % (service.split(".")[-1],
                                 " ".join(w for w in wanted if w in names)))

    print("3. the fonts the deck itself paints with (the fallback list)")
    doc = lo.open_doc(desk, os.path.join(ROOT, "tests", "fixtures", "sections.odp"),
                      hidden=False)
    try:
        fonts = []
        for pages in (doc.DrawPages, doc.MasterPages):
            for index in range(pages.Count):
                for shape in core._text_shapes(pages.getByIndex(index)):
                    for source in [shape] + core._paragraphs_of(shape):
                        try:
                            name = source.getPropertyValue("CharFontName")
                        except Exception:
                            continue
                        if name and str(name) not in fonts:
                            fonts.append(str(name))
        print("  deck                                     :", fonts)
    finally:
        lo.close(doc)
    try:
        dialog.dispose()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
