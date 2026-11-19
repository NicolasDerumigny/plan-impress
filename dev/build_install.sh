#!/bin/zsh
# Package src/ into out/<name>.oxt and install it into the development profile.
#
#   dev/build_install.sh [name.oxt]        default: plan-impress.oxt
#
# soffice is stopped first: unopkg cannot replace files a running instance has
# open, and the extension's Python modules are cached inside the office process,
# so a restart is needed after every install anyway.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-plan-impress.oxt}"
PROFILE="${PLAN_IMPRESS_PROFILE:-$ROOT/loprofile}"

"$ROOT/dev/stop_lo.sh"
"$ROOT/dev/package.sh" "$NAME"

# Remove any earlier copy first: unopkg keys on the identifier in
# description.xml, and an old build left in place shadows the new one.
unopkg -env:UserInstallation="file://$PROFILE" remove "$NAME" >/dev/null 2>&1 || true
unopkg -env:UserInstallation="file://$PROFILE" remove \
    org.devsys.planimpress >/dev/null 2>&1 || true
unopkg -env:UserInstallation="file://$PROFILE" add "$ROOT/out/$NAME" 2>&1 | tail -3
echo "installed $ROOT/out/$NAME into $PROFILE"

"$ROOT/dev/start_ui.sh"
