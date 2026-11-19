#!/bin/zsh
# Stop only OUR development soffice instance, matched by its profile path so a
# normal LibreOffice of yours is never touched.
#
# Keep the pattern built from the profile name: an inline `pkill -f soffice.bin...`
# typed at a prompt also matches the invoking shell and kills the session.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${PLAN_IMPRESS_PROFILE:-$ROOT/loprofile}"
PATTERN="soffice[.]bin.*${PROFILE:t}"
pkill -f "$PATTERN" 2>/dev/null
sleep 2
if pgrep -f "$PATTERN" >/dev/null; then
  echo "still running:" >&2
  pgrep -af "$PATTERN" >&2
  exit 1
fi
echo "stopped $PATTERN"
