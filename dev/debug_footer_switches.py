"""The footer switches and the fields inside the master's footer shapes.

    python3 dev/debug_footer_fields.py

The bottom band of a slide is controlled by four flags which ODF keeps on the
drawing-page style as ``presentation:display-footer`` and friends (that is
visible in the fixture's ``styles.xml``).  Through UNO they are the
``HeaderIsOn``/``FooterIsOn``/``DateIsOn``/``PageNumberIsOn`` properties of
``com.sun.star.presentation.DrawPage``, but asking a page for them raises
``AttributeError`` - so this dumps every property name that could be a switch, on
the page, on its style and on the master, to find out where they really live.

It also dumps the field objects the master's footer shapes contain: the date and
the page number are not text, they are text *fields*, and copying a footer means
either copying those fields or creating equivalents.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev"))
sys.path.insert(0, ROOT + "/src")

import lo  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sections.odp")
KINDS = ("HeaderShape", "DateTimeShape", "FooterShape", "SlideNumberShape")
WORDS = ("on", "footer", "header", "date", "number", "decor", "display", "start")
FIELD_SERVICES = (
    "com.sun.star.text.TextField.PageNumber",
    "com.sun.star.text.TextField.CountPage",
    "com.sun.star.text.TextField.Date",
    "com.sun.star.text.TextField.DateTime",
    "com.sun.star.text.TextField.HeaderFooter",
    "com.sun.star.text.TextField.Page",
    "com.sun.star.presentation.SlideNumberField",
    "com.sun.star.presentation.DateTimeField",
    "com.sun.star.drawing.TableOfContentsShape",
)


def detail(error):
    return "%s: %s" % (type(error).__name__, str(error)[:60])


def kind_of(shape):
    shape_type = str(getattr(shape, "ShapeType", ""))
    for kind in KINDS:
        if shape_type.endswith("." + kind):
            return kind
    return None


def switch_names(target, label):
    try:
        info = target.getPropertySetInfo().getProperties()
    except Exception as error:
        print("   %-22s no property set: %s" % (label, detail(error)))
        return
    hits = sorted(entry.Name for entry in info
                  if any(word in entry.Name.lower() for word in WORDS))
    print("   %-22s %s" % (label, ", ".join(hits) or "(none)"))
    for name in hits:
        try:
            print("      %-28s = %s" % (name, getattr(target, name)))
        except Exception as error:
            print("      %-28s -> %s" % (name, detail(error)))


def describe_fields(shape, label):
    """The text fields a footer shape holds, with whatever the proxy reveals."""
    for paragraph in shape.createEnumeration():
        for portion in paragraph.createEnumeration():
            try:
                if portion.getPropertyValue("TextPortionType") != "TextField":
                    continue
                field = portion.getPropertyValue("TextField")
            except Exception as error:
                print("      %s: no field (%s)" % (label, detail(error)))
                continue
            names = []
            for method in ("getImplementationName", "getSupportedServiceNames"):
                try:
                    names.append("%s=%s" % (method.split("get")[1],
                                            getattr(field, method)()))
                except Exception as error:
                    names.append("%s -> %s" % (method, detail(error)))
            print("      %s field: %s" % (label, " ".join(names)))
            try:
                properties = field.getPropertySetInfo().getProperties()
                print("         %s" % ", ".join(sorted(e.Name for e in properties)))
                for entry in sorted(properties, key=lambda e: e.Name):
                    print("         %-22s = %s" % (entry.Name, getattr(field, entry.Name)))
            except Exception as error:
                print("         no property set: %s" % detail(error))


def main():
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    try:
        pages = doc.DrawPages
        page = pages.getByIndex(0)
        master = doc.MasterPages.getByIndex(0)

        print("== where the footer switches live")
        switch_names(page, "DrawPages[0]")
        switch_names(master, "MasterPages[0]")
        for family in ("PageStyles", "PresentationStyles", "Styles"):
            try:
                styles = doc.StyleFamilies.getByName(family)
            except Exception as error:
                print("   %-22s -> %s" % (family, detail(error)))
                continue
            print("   %-22s members: %s" % (family, list(styles.ElementNames)[:6]))
            for name in ("Default", "Default Handout", "Notes"):
                if name not in list(styles.ElementNames):
                    continue
                switch_names(styles.getByName(name), "style %r" % name)
        try:
            print("   page.StyleName = %r" % page.StyleName)
        except Exception as error:
            print("   page.StyleName -> %s" % detail(error))

        print("== the fields in the master's footer band")
        for index in range(master.Count):
            shape = master.getByIndex(index)
            kind = kind_of(shape)
            if kind:
                describe_fields(shape, kind)

        print("== creatable field services")
        for service in FIELD_SERVICES:
            try:
                field = doc.createInstance(service)
            except Exception as error:
                print("   %-46s -> %s" % (service.rsplit(".", 2)[-1], detail(error)))
                continue
            names = "?"
            try:
                names = field.getSupportedServiceNames()
            except Exception:
                pass
            print("   %-46s created, services %s" % (service.rsplit(".", 2)[-1], names))
            try:
                properties = field.getPropertySetInfo().getProperties()
                print("      %s" % ", ".join(sorted(e.Name for e in properties)))
            except Exception as error:
                print("      no property set: %s" % detail(error))

        print("== can the master's own field be inserted into another shape?")
        donor_field = None
        for index in range(master.Count):
            shape = master.getByIndex(index)
            if kind_of(shape) == "SlideNumberShape":
                for paragraph in shape.createEnumeration():
                    for portion in paragraph.createEnumeration():
                        try:
                            if portion.getPropertyValue("TextPortionType") == "TextField":
                                donor_field = portion.getPropertyValue("TextField")
                        except Exception:
                            pass
        if donor_field is None:
            print("   no donor field found")
        else:
            page = pages.insertNewByIndex(pages.Count)
            try:
                shape = doc.createInstance("com.sun.star.presentation.SlideNumberShape")
                page.add(shape)
                text = shape.getText()
                cursor = text.createTextCursor()
                try:
                    text.insertTextContent(cursor, donor_field, False)
                    print("   inserted the master's field -> %r" % shape.getString())
                except Exception as error:
                    print("   insertTextContent(master field) -> %s" % detail(error))
                print("   page shapes: %d" % page.Count)
            finally:
                pages.remove(page)
    finally:
        lo.close(doc)


if __name__ == "__main__":
    main()
