"""Find which dialog control-model property is rejected (debug helper).

Inserts each control into a fresh UnoControlDialogModel, and when that fails
drops one property at a time to find the offender.

    python3 dev/debug_dialog.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import lo  # noqa: E402
from plan_impress import dialog  # noqa: E402

ctx = lo.connect()
manager = ctx.ServiceManager
values = {"MutedColor": "B0B0B0", "TextColor": "000000", "Title": "Plan",
          "master": "M1"}


def describe(error):
    parts = [type(error).__name__]
    for attribute in ("Message", "SequenceLength", "SequenceIndex", "PropertyName",
                      "PropertyHandle", "OriginalException", "Reason"):
        value = getattr(error, attribute, None)
        if value not in (None, 0, ""):
            parts.append("%s=%r" % (attribute, value))
    text = str(error)
    if text:
        parts.append(text)
    return " ".join(parts)


def try_insert(name, service, pairs):
    model = manager.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx)
    try:
        model.insertByName(name, dialog._properties([("Servicename", service)] + pairs))
        return None
    except Exception as error:
        return describe(error)
    finally:
        try:
            model.dispose()
        except Exception:
            pass


for name, service, props in dialog._field_specs(values, ["M1", "M2"]):
    pairs = list(props)
    error = try_insert(name, service, pairs)
    if error is None:
        print("ok   %-18s %s" % (name, service.split(".")[-1]))
        continue
    print("FAIL %-18s %s\n     %s" % (name, service.split(".")[-1], error))
    for index, (pname, _value) in enumerate(pairs):
        without = pairs[:index] + pairs[index + 1:]
        if try_insert(name, service, without) is None:
            print("     -> dropping %s makes it work" % pname)
            break
