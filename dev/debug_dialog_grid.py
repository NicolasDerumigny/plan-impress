"""Does the ``XLayoutContainer`` route give the settings dialog real geometry?

    python3 dev/debug_dialog_grid.py [show|"" ] [seconds]

Absolute positioning is unavailable here: ``insertByName`` with a
``sequence<PropertyValue>`` always raises, and a model inserted as an object
exposes no ``PositionX``/``Width``, so the controls land on top of each other
at 0,0.  ``XControl::setPosSize`` honours the position but not the size.

``com.sun.star.layoutLayoutManager.GridLayout`` is what LibreOffice's own
dialogs use; container properties set the grid, element properties the cell and
the sizing mode.  Element property names are tried one by one so an unsupported
one is visible instead of fatal.
"""
import sys
import time

ROOT = "/tmp/opencode/planimpress/plan-impress"
sys.path.insert(0, ROOT + "/dev")
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
EDIT = "com.sun.star.awt.UnoControlEditModel"
LABEL = "com.sun.star.awt.UnoControlFixedTextModel"

CONTAINER_PROPERTIES = (
    ("ColumnCount", 2), ("RowCount", 3),
    ("ColumnSpacing", 100), ("RowSpacing", 80),
    ("ColumnMinimumWidth", 800), ("RowMinimumHeight", 400),
    ("TopLeftMargin", 150), ("BottomRightMargin", 150),
)

ELEMENT_PROPERTIES = (
    ("Row", 0), ("Column", 1),
    ("ColumnMode", 2), ("ColumnWidth", 2500),
    ("RowMode", 2), ("RowHeight", 500),
    ("LeftMargin", 50), ("TopMargin", 50),
)

#: (name, service, control properties, row, column)
WIDGETS = (
    ("l1", LABEL, (("Label", "Muted colour"),), 0, 0),
    ("e1", EDIT, (("Text", "B0B0B0"),), 0, 1),
    ("l2", LABEL, (("Label", "Heading"),), 1, 0),
    ("e2", EDIT, (("Text", "Plan"),), 1, 1),
    ("ok", "com.sun.star.awt.UnoControlButtonModel", (("Label", "OK"),), 2, 1),
)


def pvs(pairs):
    return tuple(uno.createUnoStruct("com.sun.star.beans.PropertyValue", Name=n, Value=v)
                 for n, v in pairs)


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:70])


def main():
    show = len(sys.argv) > 2 and sys.argv[1] == "show"
    seconds = float(sys.argv[2]) if show else 0.0

    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)
    for name, service, props, _row, _column in WIDGETS:
        control_model = MANAGER.createInstanceWithContext(service, CTX)
        for pname, value in props:
            control_model.setPropertyValue(pname, value)
        model.insertByName(name, control_model)

    toolkit = MANAGER.createInstanceWithContext("com.sun.star.awt.Toolkit", CTX)
    dialog.createPeer(toolkit, None)

    for attribute in ("setLayoutLayoutManager", "addLayoutElement", "setLayoutProperties",
                      "setLayoutManagerProperties", "registerLayoutContainer"):
        print("dialog.%s: %s" % (attribute, hasattr(dialog, attribute)))

    layout = None
    for service in ("com.sun.star.layoutLayoutManager.GridLayout",
                    "com.sun.star.layoutLayoutManager.BoxLayout"):
        try:
            layout = MANAGER.createInstanceWithContext(service, CTX)
            print("created %s" % service)
            break
        except Exception as error:
            print("no %s: %s" % (service, detail(error)))
    if layout is None:
        return

    print("layout methods: %s" % [m for m in dir(layout) if not m.startswith("_")])
    try:
        theme = MANAGER.createInstanceWithContext("com.sun.star.ui.layout.LayoutManagerTheme",
                                                  CTX)
        layout.setTheme(theme)
        print("setTheme ok")
    except Exception as error:
        print("setTheme -> %s" % detail(error))
    try:
        dialog.setLayoutLayoutManager(layout)
        print("setLayoutLayoutManager ok")
    except Exception as error:
        print("setLayoutLayoutManager -> %s" % detail(error))

    for name, service, _props, row, column in WIDGETS:
        control = dialog.getControl(name)
        try:
            dialog.addLayoutElement(control, None)
        except Exception as error:
            print("%-4s addLayoutElement -> %s" % (name, detail(error)))
            continue
        pairs = [p for p in ELEMENT_PROPERTIES if p[0] not in ("Row", "Column")]
        pairs = [("Row", row), ("Column", column)] + [
            (n, v) for n, v in ELEMENT_PROPERTIES if n not in ("Row", "Column")]
        try:
            dialog.setLayoutProperties(control, pvs(pairs))
        except Exception as error:
            print("%-4s setLayoutProperties(all) -> %s" % (name, detail(error)))
            # fall back to one property at a time to find the unsupported one
            for index, (pname, _value) in enumerate(pairs):
                try:
                    dialog.setLayoutProperties(control, pvs(pairs[:index + 1]))
                except Exception as inner:
                    print("     %-14s %s" % (pname, detail(inner)))
                    break

    try:
        dialog.setLayoutManagerProperties(pvs(CONTAINER_PROPERTIES))
        print("setLayoutManagerProperties ok")
    except Exception as error:
        print("setLayoutManagerProperties -> %s" % detail(error))
        for index, (pname, _value) in enumerate(CONTAINER_PROPERTIES):
            try:
                dialog.setLayoutManagerProperties(pvs(CONTAINER_PROPERTIES[:index + 1]))
            except Exception as inner:
                print("     %-20s %s" % (pname, detail(inner)))
                break

    positions = []
    for name, _service, _props, _row, _column in WIDGETS:
        try:
            peer = dialog.getControl(name).getPosSize()
            positions.append((name, peer.X, peer.Y, peer.Width, peer.Height))
            print("%-4s %dx%d at %d,%d" % (name, peer.Width, peer.Height, peer.X, peer.Y))
        except Exception as error:
            print("%-4s %s" % (name, detail(error)))
    distinct = len(set((x, y) for _n, x, y, _w, _h in positions))
    print("distinct positions: %d of %d" % (distinct, len(positions)))
    sized = all(w > 0 and h > 0 for _n, _x, _y, w, h in positions)
    print("all sized: %s" % sized)
    try:
        dialog.setTitle("Plan Impress (layout probe)")
        dialog.setVisible(True)
    except Exception as error:
        print("setVisible -> %s" % detail(error))
    if seconds:
        time.sleep(seconds)
    dialog.dispose()


if __name__ == "__main__":
    main()
