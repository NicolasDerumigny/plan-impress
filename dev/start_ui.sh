#!/bin/zsh
# Start the isolated soffice used for development, in UI mode under Xvfb.
#
# UI mode (not --headless) is required by the tests: moving slides and
# dispatching menu commands both need a controller and a frame.
#
#   DISPLAY          X display to use (default :97, started here if missing)
#   PLAN_IMPRESS_PROFILE  user installation (default <repo>/loprofile)
#   PLAN_IMPRESS_PORT     UNO socket port  (default 2009)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${PLAN_IMPRESS_PROFILE:-$ROOT/loprofile}"
PORT="${PLAN_IMPRESS_PORT:-2009}"
export DISPLAY="${DISPLAY:-:97}"

pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1440x900x24 >"$ROOT/out/xvfb.log" 2>&1 &)
sleep 2
"$ROOT/dev/stop_lo.sh"
mkdir -p "$ROOT/out"

nohup soffice -env:UserInstallation="file://$PROFILE" --norestore \
  --accept="socket,host=127.0.0.1,port=$PORT;urp;" \
  >"$ROOT/out/soffice.log" 2>&1 &

for i in {1..40}; do
  ss -ltn 2>/dev/null | grep -q "$PORT" && { echo "soffice listening on $PORT after ${i}s"; exit 0; }
  sleep 1
done
echo "soffice did not start listening on $PORT; last log lines:" >&2
tail -20 "$ROOT/out/soffice.log" >&2
exit 1
