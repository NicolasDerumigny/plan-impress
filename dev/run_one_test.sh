#!/bin/zsh
# Run one test on a fresh office and say whether the office survived.
#
#   dev/run_one_test.sh plan_slide_typography
#
# The office is restarted first, so a crash cannot be left over from an earlier
# test; the exit code is the test suite's, and the last line says whether soffice
# is still listening afterwards.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DISPLAY="${DISPLAY:-:98}"
"$ROOT/dev/start_ui.sh" >/dev/null 2>&1
sleep 1
set +e
timeout 300 python3 -u "$ROOT/tests/run_tests.py" "$1" 2>&1 | tail -4
if ss -ltn | grep -q 2009; then
  echo "office: ALIVE"
else
  echo "office: DEAD"
  tail -3 "$ROOT/out/soffice.log"
fi
