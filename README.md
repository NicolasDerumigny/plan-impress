# Plan Impress

A LibreOffice Impress extension that adds a **Plan** menu and inserts agenda
slides for the presentation's sections:

* one **overview slide** in front of the first section, listing every section;
* one **plan slide at the top of each section**, also listing every section,
  with only the current section drawn in the text colour and all the others in
  the muted colour;
* a **Settings…** dialog for the muted colour, the highlight colour, the title of
  the plan slides and the master slide they are based on;
* a **colour picker** behind each colour: click the swatch and choose from the
  colours this presentation already uses, the ones you picked recently, or any
  palette LibreOffice ships (`standard`, `material`, `html`, …) — the same list
  the font-colour dropdown shows;
* the deck's **footer** on all of them: the date, the footer text and the page
  number a slide of the deck shows are shown by the generated slides too.

```
before                              after
─────                               ─────
 1  title             (no section)   1  title             <- untouched, still outside every section
 2  welcome           (Introduction) 2  Plan              <- overview, all sections
 3  agenda-notes      (Introduction) 3  Plan              <- Introduction
 4  overview-diagram  (Architecture) 4  welcome
 5  data-model        (Architecture) 5  agenda-notes
 6  apis              (Architecture) 6  Plan              <- Architecture
 7  live-demo         (Demo)         7  overview-diagram
 8  questions         (Demo)         8  data-model
                                     9  apis
                                    10  Plan              <- Demo
                                    11  live-demo
                                    12  questions
```

Each plan slide lists all sections; the current one is highlighted, the rest are
muted. The overview slide is deliberately outside every section — it belongs to
the deck, not to a chapter of it.

A **title slide that belongs to no section** is left exactly where it is: the
overview goes in front of the *first section*, not in front of the deck, so the
title slide stays slide 1 and the overview becomes slide 2. (Slides left
ungrouped *after* the first section are a different matter — LibreOffice itself
attaches those to the section in front of them whenever the section list is
written, `AGENTS.md`.)

## Install

Either from the file manager (Extensions dialog: *Tools ▸ Extension Manager*),
or on the command line:

```sh
make                                    # builds out/plan-impress.oxt
unopkg add out/plan-impress.oxt         # for your own LibreOffice profile
```

Restart LibreOffice and open a presentation that uses sections
(*Slide ▸ Insert Section*). The **Plan** menu appears next to *Slide Show*.

Requires LibreOffice 7.0 or newer; developed and tested on 26.8.

## Using it

| Menu item | What it does |
|---|---|
| Insert Plan Slides | Regenerates the overview slide and one plan slide per section |
| Remove Plan Slides | Deletes every slide the extension generated |
| Insert Section Titles | Writes each slide's section name above its heading, and updates the boxes already there |
| Remove Section Titles | Takes those name boxes away again |
| Settings… | Colours (each with a palette picker), plan slide title, master slide, the defaults the section label falls back on |
| Toggle Debug Log | Turns the trace log on or off |

The six rows are three groups of two, with a line between the groups: the plan
slides and their undo, the section names and their undo, and the two commands
that change nothing in the deck.

Plan slides are named `PlanImpress:Overview` and `PlanImpress:Section=<n>`.
That naming is how the extension recognises its own output, so:

* running *Insert Plan Slides* twice regenerates the slides instead of adding
  duplicates;
* *Remove Plan Slides* takes exactly those slides out again and leaves your own
  slides untouched;
* if you rename or delete a generated slide, the next run simply creates a
  fresh set.

Settings are stored per LibreOffice user profile in
`<profile>/user/planimpress/settings.json`, so they survive extension updates
and are easy to edit or version by hand.

## How it works

`src/` **is** the extension package — the layout of `src/` is the layout inside
the `.oxt`.

| File | Role |
|---|---|
| `src/Addons.xcu` | The Plan menu and the icons for its items |
| `src/handler.py` | The `com.sun.star.task.Job` implementations the menu items dispatch to |
| `src/plan_impress/core.py` | All document-model work: sections, page insertion, slide content |
| `src/plan_impress/dialog.py` | The settings dialog and the message boxes |
| `src/plan_impress/picker.py` | The palette picker the colour swatches open |
| `src/plan_impress/palettes.py` | The office's `.soc` colour tables, the deck's own colours, recently used ones |
| `src/plan_impress/config.py` | Settings load/save, colour helpers, logging |
| `src/description.xml` | Extension metadata, version, dependencies |
| `src/META-INF/manifest.xml` | Declares `Addons.xcu` as configuration data and `handler.py` as a Python UNO component |

The flow of a menu click:

1. `Addons.xcu` merges a *Plan* menu into the Impress menu bar. Its items carry
   a URL such as `service:org.nicolasderumigny.planimpress.InsertPlan?insert`.
2. LibreOffice instantiates that implementation name — registered in
   `handler.py` — as a `com.sun.star.task.Job` and calls
   `XJobExecutor.trigger()`.
3. `PlanJob` looks up `do_<command>` on itself and runs it: load the settings,
   find the active presentation, call into `core.py`.
4. `core.insert_plan()` removes the previously generated slides, reads the
   sections, inserts the plan pages at the right positions, fills them with a
   title shape and one paragraph per section, copies the deck's footer band onto
   them, and rewrites the section list so every plan slide leads its own section.

Only `handler.py` is registered as a UNO component; it puts its own folder on
`sys.path` and imports the rest of the `plan_impress` package normally. That
keeps the plain modules out of the registration step, where an unrelated import
failure would silently make the whole extension disappear from the menu.

### Design decisions worth knowing

* **Jobs, not script URLs.** A `vnd.sun.star.script:` URL has to spell out the
  installed `.oxt` file name and `location=user:uno_packages`, which breaks as
  soon as the extension is renamed, updated or installed system-wide.
  Implementation names are stable, and `service:` URLs are the pattern the SDK
  itself documents.
* **A JSON file, not the configuration registry.** An extension cannot write to
  the LibreOffice config without shipping a schema; a small JSON file under the
  user profile is simpler, inspectable, and just as persistent.
* **Inline, in the office process.** The commands run directly inside
  `trigger()`. Running them from a Python worker thread crashes the office (see
  `AGENTS.md`).
* **The picker is ours, because there is nothing to borrow.** LibreOffice exposes
  no colour picker and no palette list through UNO (`AGENTS.md`), so the popup is
  built out of AWT control models and the palettes are read from the same
  `share/palette/*.soc` files the office reads — which is also why the picker can
  offer the deck's own colours first: a plan slide should be coloured like the
  deck. Clicking a colour is the answer, as in the font-colour dropdown; every
  colour you pick is remembered as *Recently used*.
* **The footer is copied from the deck, never invented.** Impress keeps the date,
  the footer text and the page number on each *slide*, so a slide the extension
  creates starts without them; `core.apply_footer()` copies them from the first
  slide of the deck that actually prints something, and recreates that slide's
  footer frames when the deck carries its own. A deck whose author switched the
  footer on but typed nothing prints nothing, and the plan slides print nothing
  there too: switched on is not the same as filled in.

## Development

Everything runs against a **separate LibreOffice installation and profile**
inside this checkout, so the LibreOffice you use day-to-day is never touched.

```sh
make            # package out/plan-impress.oxt
make install    # stop the dev office, install the .oxt, start it again
make start      # start the dev office (UI mode under Xvfb, UNO socket on 2009)
make stop       # stop only that instance
make test       # install, then run the test suite
make unit       # the tests that need no office
make icons      # regenerate src/icons/*.png
make fixture    # regenerate the fixture decks (with and without a footer)
make clean

python3 dev/open_fixture.py   # open the fixture in the dev office for a UI check
python3 dev/render_plan.py    # insert with the saved settings, export PDF + PNGs
```

Requirements: LibreOffice (with `unopkg` and pyuno), Python 3, `zip`, and an X
display for the tests — `dev/start_ui.sh` starts `Xvfb :97` if `DISPLAY` is not
already set. Set `PLAN_IMPRESS_PROFILE` / `PLAN_IMPRESS_PORT` to move the
development instance elsewhere, and `PLAN_IMPRESS_DATA_DIR` to point the settings
file somewhere else (the `dev/` scripts run outside the office, which is the only
way the extension itself finds its profile — see `AGENTS.md`).

The tests connect over UNO to the running development office (`dev/lo.py`) and
drive it the same way a user does: the document model through
`plan_impress.core`, the menu items by dispatching their `service:` URL on the
document's frame. The settings dialog is checked where it used to break: the
controls are built, a native peer is attached, and every control's rectangle is
asserted to be its own — distinct position, non-zero size, inside the window —
before the values are read back. Screenshots come last, because assertions have
passed on a dialog nobody could use.

Debugging helpers live in `dev/` (`debug_twice.py`, `debug_move.py`,
`debug_dialog*.py`, `debug_footer*.py`, `dep_probe.py`, `measure_text.py`, plus
`render_plan.py` and `show_plan.py` for a look at the result); each one
reproduces one of the LibreOffice behaviours described in `AGENTS.md` and prints
what it measured. `probe_api.py`, `probe_palettes.py` and `probe_paint.py` are the
three that asked the office whether it had a colour picker, a palette list or a
paintable control at all — it has none, which is why `picker.py` exists.

## Documentation for agents

`AGENTS.md` records the LibreOffice API behaviours this extension depends on —
the ones that cost real debugging time — plus the layout, the commands and the
conventions to follow when changing it. Read it before editing.

## Author

Nicolas Derumigny [AI] — developed with an AI coding agent, which the bracketed
`[AI]` says on the Extension Manager's screen as well (`src/description.xml`).

## License

MIT. See `LICENSE`.
