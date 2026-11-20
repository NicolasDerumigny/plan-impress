"""How the template's own first list level ends up on a generated slide.

    python3 dev/debug_numbering.py [output-dir]

Writes ``numbering.pdf`` (the deck's own slides first, then one slide per
variant, in the order below) plus the PNGs ``pdftoppm`` makes from it, and prints
what the office kept of each attempt.  Everything here was measured on
LibreOffice 26.8.

``from scratch``
    a rules object of its own, with the label, prefix, suffix, bullet colour and
    relative size written out.  The list renders, but in a font, a size, a gap and
    a colour of its own - the digits look pasted onto the slide rather than drawn
    by the template.
``inherit only``
    the master's level copied over and *only* ``NumberingType`` replaced.  The
    number comes in the template's bullet font and colour, but a level that draws
    a special character sizes *that character*: the fixture's master asks for 45 %
    of the text height, which is an unreadable digit, and its ``FirstLineOffset``
    is tuned for the glyph, which glues the digit to the text (``1Introduction``).
``core``
    what ``core._number_list`` does: as ``inherit only``, plus the label never
    smaller than the text and given a column of its own, plus one copy of the rules
    per paragraph differing only in ``BulletColor`` - which is what dims the numbers
    of the sections that are not the current one.  Look for "1 2 3" in the first
    column, not "1 1 1": different rule objects per paragraph do not restart the
    count.
``core, no paragraph indent``
    the same with the master's paragraph indentation put back afterwards.  This is
    the one that renders "1Introduction": once the slide says where its own box is
    (every variant here sets the master's rectangle, as ``core`` does), Impress
    ignores the level's ``LeftMargin``/``FirstLineOffset`` and the column the digit
    needs has to be asked for on the *paragraph*.
``symbol text distance``
    the gap between label and text cannot be asked for: writes to
    ``SymbolTextDistance`` are ignored (0, 350 and 600 all read back as the
    inherited -900) - it follows ``FirstLineOffset``, which is what moves it.
``string type``
    ``NumberingType`` as a string: it arrives as 0, which draws no number at all.
``letters``
    ``NumberingType = 1``, which is ``CHARS_LOWER_LETTER`` - the "a. b. c." the
    first attempt rendered.  ``NumberingType.ARABIC`` is 4.
``macro prefix``
    ``Prefix = "%1."``: the macro is not substituted, it prints as typed.
``untyped``
    the level handed to ``replaceByIndex`` as a plain tuple: refused with an
    ``IllegalArgumentException``.
``no mirror``
    the shape's own character and text-box properties kept, and the master's level
    left alone: the heading and the list come in the page style's font, vertically
    centred in a box that auto-grows, which is what made a generated slide look
    re-created rather than edited.  A paragraph of an outline placeholder takes its
    characters from the page style's outline level, which carries a weight of its
    own - 150 on the deck this was found on, over the master placeholder's 100.
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
NAMES = ("Introduction", "Architecture", "Demo")
CURRENT = 1
LEVEL = "[]com.sun.star.beans.PropertyValue"
#: the wrong answers, kept out of core.py on purpose; they live here so the
#: comparison can be re-run
WRONG = {"string type": "4", "letters": 1}


def level_dict(rules, index=0):
    try:
        return dict((entry.Name, entry.Value) for entry in rules.getByIndex(index))
    except Exception:
        return {}


def copy_rules(doc, source):
    rules = doc.createInstance("com.sun.star.text.NumberingRules")
    if source is not None:
        for index in range(min(rules.Count, source.Count)):
            rules.replaceByIndex(index, uno.Any(LEVEL, tuple(
                list(source.getByIndex(index)))))
    return rules


def patch(rules, overrides):
    """Change single properties of the first level; the rest is kept.

    The level goes back as one typed sequence: a plain tuple is refused.
    """
    level = list(rules.getByIndex(0))
    seen = set()
    for entry in level:
        if entry.Name in overrides:
            entry.Value = overrides[entry.Name]
            seen.add(entry.Name)
    for name in sorted(overrides):
        if name not in seen:
            entry = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
            entry.Name, entry.Value = name, overrides[name]
            level.append(entry)
    rules.replaceByIndex(0, uno.Any(LEVEL, tuple(level)))
    return rules


def describe(shape):
    return "pt=%-5s weight=%-5s font=%r grow=%r" % (
        getattr(shape, "CharHeight", None), getattr(shape, "CharWeight", None),
        getattr(shape, "CharFontName", None),
        getattr(shape, "TextAutoGrowHeight", None))


def slide(doc, master, kind, master_rules, settings):
    page = doc.DrawPages.insertNewByIndex(doc.DrawPages.Count)
    page.Name = "N:" + kind
    page.MasterPage = master
    page.Layout = core._LAYOUT_OUTLINE
    # the way core._ensure_placeholder does it: the layout has usually already put
    # the placeholders there, and a shape created next to them would be a second
    # list - and it would not carry the page style's characters either, which is
    # what the "no mirror" variant is about
    body = core._body_shape(page)
    if body is None:
        body = doc.createInstance("com.sun.star.presentation.OutlinerShape")
        page.add(body)
    body.setString("\n".join(NAMES))
    paragraphs = core._paragraphs_of(body)
    master_body = core._body_shape(master)
    highlight, muted = settings["text_color"], settings["muted_color"]
    colors = [highlight if index == CURRENT else muted for index in range(3)]
    arabis = core._numbering_type_arabic()
    # what core._make_text_shape does, in this order: the template's own characters
    # (shape *and* paragraphs, or the page style's outline level leaves a bold of
    # its own on every row), then the box it keeps its list in - and naming that
    # box is what makes Impress stop honouring the list level's own indentation,
    # which is what the two "core" variants below are about
    if kind != "no mirror":
        core._mirror_characters(master_body, body)
        for paragraph in paragraphs:
            core._mirror_characters(master_body, paragraph,
                                    core.PARAGRAPH_ATTRIBUTES)
    body.Position = core._point(master_body.Position.X, master_body.Position.Y)
    body.Size = core._size(master_body.Size.Width, master_body.Size.Height)

    if kind == "from scratch":
        body.NumberingRules = patch(
            doc.createInstance("com.sun.star.text.NumberingRules"),
            {"NumberingType": arabis, "StartWith": 1, "Prefix": "", "Suffix": ".",
             "BulletColor": -1, "BulletRelSize": 100})
    elif kind == "inherit only":
        body.NumberingRules = patch(copy_rules(doc, master_rules),
                                    {"NumberingType": arabis})
    elif kind == "core":
        template_bullet = core._level_value(master_rules, "BulletColor", -1)
        core._number_list(doc, body, master_rules,
                          [template_bullet if color == highlight and
                           template_bullet >= 0 else color for color in colors])
    elif kind == "core, no paragraph indent":
        # the same, with the master's paragraph indentation put back afterwards:
        # the level's own margins are not enough to give the digit a column
        template_bullet = core._level_value(master_rules, "BulletColor", -1)
        core._number_list(doc, body, master_rules,
                          [template_bullet if color == highlight and
                           template_bullet >= 0 else color for color in colors])
        master_body = core._body_shape(master)
        for paragraph in paragraphs:
            paragraph.ParaLeftMargin = master_body.ParaLeftMargin
            paragraph.ParaFirstLineIndent = master_body.ParaFirstLineIndent
    elif kind == "symbol text distance":
        body.NumberingRules = patch(
            copy_rules(doc, master_rules),
            {"NumberingType": arabis, "BulletRelSize": 100,
             "FirstLineOffset": -1200, "SymbolTextDistance": 350})
    elif kind in WRONG or kind == "macro prefix":
        wanted = {"NumberingType": arabis}
        if kind in WRONG:
            wanted["NumberingType"] = WRONG[kind]
        else:
            wanted.update({"Prefix": "%1.", "Suffix": ""})
        body.NumberingRules = patch(copy_rules(doc, master_rules), wanted)
    elif kind == "untyped":
        rules = copy_rules(doc, master_rules)
        level = list(rules.getByIndex(0))
        for entry in level:
            if entry.Name == "NumberingType":
                entry.Value = arabis
        try:
            rules.replaceByIndex(0, tuple(level))        # measured: refused
            body.NumberingRules = rules
        except Exception as error:
            print("      replaceByIndex(tuple) raised %s: %s"
                  % (type(error).__name__, error))

    for paragraph in paragraphs:
        try:
            paragraph.NumberingLevel = 0
            paragraph.NumberingIsNumber = True
        except Exception as error:
            print("      %s: %s" % (kind, error))
    core._paint_paragraphs(body, colors)

    kept = level_dict(getattr(body, "NumberingRules", None))
    labels = [core._level_value(para.NumberingRules, "BulletColor", "?")
              for para in paragraphs]
    print("%-20s type=%-4r prefix=%-5r suffix=%-5r bulletcolor=%-8r relsize=%-4r "
          "margins=%-19r rows=%r | indent=%r row weight=%r | %s"
          % (kind, kept.get("NumberingType"), kept.get("Prefix"),
             kept.get("Suffix"), kept.get("BulletColor"), kept.get("BulletRelSize"),
             (kept.get("LeftMargin"), kept.get("FirstLineOffset"),
              kept.get("SymbolTextDistance")), labels,
             [(paragraph.ParaLeftMargin, paragraph.ParaFirstLineIndent)
              for paragraph in paragraphs],
             [paragraph.CharWeight for paragraph in paragraphs], describe(body)))
    return page


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                          else os.path.join(ROOT, "out"))
    os.makedirs(out, exist_ok=True)
    kinds = ("from scratch", "inherit only", "core",
             "core, no paragraph indent", "symbol text distance",
             "string type", "letters", "macro prefix", "untyped", "no mirror")
    settings = dict(config.DEFAULTS, text_color=0x1A1A1A, muted_color=0xBFBFBF)
    ctx = lo.connect()
    desk = lo.desktop(ctx)
    doc = lo.open_doc(desk, FIXTURE, hidden=False)
    pdf = os.path.join(out, "numbering.pdf")
    try:
        master = core._default_master(doc)
        master_body = core._body_shape(master)
        master_rules = core._numbering_rules(master_body)
        print("master %r content placeholder %s %s"
              % (master.Name, master_body.ShapeType, describe(master_body)))
        print("its level 0: %r" % level_dict(master_rules))
        print("NumberingType.ARABIC = %d\n" % core._numbering_type_arabic())
        for kind in kinds:
            slide(doc, master, kind, master_rules, settings)
        doc.storeToURL(uno.systemPathToFileUrl(pdf),
                       (lo.pv("FilterName", "impress_pdf_Export"),))
    finally:
        lo.close(doc)
    subprocess.run(["pdftoppm", "-png", "-r", "100", pdf,
                    os.path.join(out, "numbering")], check=True)
    print("\npdf : %s\npngs: the variants are the last %d pages, in order (%s)"
          % (pdf, len(kinds),
             ", ".join(sorted(name for name in os.listdir(out)
                              if name.startswith("numbering-")))))


if __name__ == "__main__":
    main()
