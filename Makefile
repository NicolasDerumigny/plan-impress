# Plan Impress - development helpers.
#
#   make            package out/plan-impress.oxt
#   make install    package, install into the development profile, restart office
#   make test       install, then run tests/run_tests.py
#   make start      start the isolated office (UI mode, UNO socket on 2009)
#   make stop       stop only that instance
#   make icons      regenerate src/icons/*.png
#   make fixture    regenerate the fixture decks in tests/fixtures/
#   make clean      remove build output (never your documents)
#
# Everything runs against a profile inside this checkout (loprofile/) and a
# private UNO port, so the LibreOffice you use day-to-day is not touched.

ROOT     := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PY       ?= python3
OXT      ?= plan-impress.oxt
PROFILE  ?= $(ROOT)/loprofile
PORT     ?= 2009
export PLAN_IMPRESS_PROFILE := $(PROFILE)
export PLAN_IMPRESS_PORT    := $(PORT)

.PHONY: all oxt install start stop test unit icons fixture clean

all: oxt

oxt:
	dev/package.sh $(OXT)

install:
	dev/build_install.sh $(OXT)

start:
	dev/start_ui.sh

stop:
	dev/stop_lo.sh

fixture:
	$(PY) tests/make_fixture.py

test: install
	@test -f tests/fixtures/sections.odp || $(PY) tests/make_fixture.py
	@test -f tests/fixtures/sections_no_footer.odp || $(PY) tests/make_fixture.py
	$(PY) tests/run_tests.py

# Fast loop for the pure-Python part (no office needed).
unit:
	$(PY) tests/run_tests.py colour
	$(PY) tests/run_tests.py point_size
	$(PY) tests/run_tests.py list_label
	$(PY) tests/run_tests.py dialog_field

icons:
	$(PY) dev/make_icons.py

clean:
	rm -rf $(ROOT)/out
	find $(ROOT)/src $(ROOT)/tests $(ROOT)/dev -name '__pycache__' -type d -prune -exec rm -rf {} +
