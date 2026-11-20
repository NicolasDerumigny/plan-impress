"""Which property set does each control-model factory actually give?

    python3 dev/debug_dialog_props.py

``dev/debug_dialog_wizard.py`` showed that only a control model created by the
dialog model's own ``createInstance`` keeps ``PositionX``/``Width``; but a
control built that way refused ``TabStop``, ``MaxLen``, ``Multiple`` and
``TabPosition``, which the service manager's version accepted.  This prints the
full property-name list of both, so the difference is on the table instead of
guessed at.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import lo  # noqa: E402
import uno  # noqa: E402

CTX = lo.connect()
MANAGER = CTX.ServiceManager
PROBES = (
    "com.sun.star.awt.UnoControlEditModel",
    "com.sun.star.awt.UnoControlListBoxModel",
    "com.sun.star.awt.UnoControlButtonModel",
)
INTERESTING = ("PositionX", "PositionY", "Width", "Height", "TabStop", "TabPosition",
               "MaxLen", "Multiple", "Dropdown", "StringItemList", "Text", "Label",
               "FontHeight", "DefaultButton", "Border", "BackgroundColor")


def names_of(propset):
    try:
        info = propset.getPropertySetInfo()
    except Exception as error:
        return "no property set info (%s)" % type(error).__name__
    try:
        return sorted(entry.Name for entry in info.getProperties())
    except Exception as error:
        return "unreadable (%s)" % type(error).__name__


def try_set(model, name, value):
    try:
        model.setPropertyValue(name, value)
    except Exception as error:
        return "%s" % type(error).__name__
    return "ok"


def main():
    dialog = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", CTX)
    model = MANAGER.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", CTX)
    dialog.setModel(model)

    for service in PROBES:
        short = service.split(".")[-1]
        from_manager = MANAGER.createInstanceWithContext(service, CTX)
        from_container = model.createInstance(service)
        manager_names = names_of(from_manager)
        container_names = names_of(from_container)
        print("== %s" % short)
        print("   service manager : %d properties"
              % (len(manager_names) if isinstance(manager_names, list) else 0))
        print("   container       : %d properties"
              % (len(container_names) if isinstance(container_names, list) else 0))
        if isinstance(manager_names, list) and isinstance(container_names, list):
            only_manager = [n for n in manager_names if n not in container_names]
            only_container = [n for n in container_names if n not in manager_names]
            print("   only from the service manager (%d): %s"
                  % (len(only_manager), ", ".join(only_manager) or "-"))
            print("   only from the container (%d): %s"
                  % (len(only_container), ", ".join(only_container) or "-"))
        sample = {"com.sun.star.awt.UnoControlEditModel":
                  (("Text", "abc"), ("MaxLen", 7), ("TabStop", True),
                   ("PositionX", 10), ("Width", 50)),
                  "com.sun.star.awt.UnoControlListBoxModel":
                  (("StringItemList", uno.Any("[]string", ("a", "b"))),
                   ("Multiple", False), ("Dropdown", True), ("TabStop", True),
                   ("Width", 50)),
                  "com.sun.star.awt.UnoControlButtonModel":
                  (("Label", "OK"), ("DefaultButton", True), ("TabStop", True),
                   ("TabPosition", 1), ("Width", 40))}[service]
        for label, target in (("manager", from_manager), ("container", from_container)):
            results = ["%s=%s" % (n, try_set(target, n, v)) for n, v in sample]
            print("   %-9s %s" % (label, " ".join(results)))
        # the bulk call the wizards use
        pairs = tuple(n for n, _v in sample), tuple(v for _n, v in sample)
        for label, target in (("manager", from_manager), ("container", from_container)):
            try:
                uno.invoke(target, "setPropertyValues", pairs)
                print("   %-9s setPropertyValues ok" % label)
            except Exception as error:
                print("   %-9s setPropertyValues -> %s: %s"
                      % (label, type(error).__name__, str(error)[:60]))
    dialog.dispose()


if __name__ == "__main__":
    main()
