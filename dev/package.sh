#!/bin/zsh
# Package src/ into out/<name>.oxt without touching LibreOffice.
#
#   dev/package.sh [name.oxt]        default: plan-impress.oxt
#
# META-INF/manifest.xml must be stored uncompressed?  No: unlike ODF packages a
# .oxt has no mimetype-stored requirement, so a plain zip is fine.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-plan-impress.oxt}"
mkdir -p "$ROOT/out"
cd "$ROOT/src"
rm -f "$ROOT/out/$NAME"
zip -q -r -X "$ROOT/out/$NAME" . \
    -x '.*' -x '*/__pycache__/*' -x '__pycache__/*' -x '*.pyc'
echo "packed $ROOT/out/$NAME"
unzip -l "$ROOT/out/$NAME" | sed -n '1,40p'
