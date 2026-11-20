"""Insert the plan slides with the *saved* settings and export them to PDF.

    python3 dev/render_plan.py [output-dir]

The settings dialog and the document model have to agree, and the only way to
see that is to render: this loads `<profile>/planimpress/settings.json` exactly
as the menu command does, generates the slides, and writes ``plan.pdf`` next to
the PNGs ``pdftoppm`` produces from it.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402
import uno  # noqa: E402
from plan_impress import config, core  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                          else os.path.join(ROOT, "out"))
    os.makedirs(out, exist_ok=True)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    settings = config.load(ctx)
    print("settings  : %s" % settings)
    print("settings  : %s" % config.settings_path(ctx))
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        report = core.insert_plan(doc, settings, ctx)
        print("inserted  : %d slides, sections %d"
              % (report["inserted"], report["sections"]))
        pages = doc.DrawPages
        for index in range(pages.Count):
            page = pages.getByIndex(index)
            if not str(page.Name).startswith(core.PLAN_PREFIX):
                continue
            shapes = {}
            for shape_index in range(page.Count):
                shape = page.getByIndex(shape_index)
                shapes[shape.getString().replace("\n", " | ")] = [
                    paragraph.CharColor for paragraph in shape.createEnumeration()]
            print("  %-26s %s" % (page.Name, shapes))
        pdf = os.path.join(out, "plan.pdf")
        doc.storeToURL(uno.systemPathToFileUrl(pdf),
                       (uno.createUnoStruct("com.sun.star.beans.PropertyValue",
                                            Name="FilterName", Value="impress_pdf_Export"),))
        print("pdf       : %s" % pdf)
    finally:
        lo.close(doc)
    subprocess.run(["pdftoppm", "-png", "-r", "70", pdf, os.path.join(out, "plan")],
                   check=True)
    print("pngs      : %s" % sorted(f for f in os.listdir(out) if f.startswith("plan-")))


if __name__ == "__main__":
    main()
