#!/bin/sh
# Launcher inside Flatpak / local install
export PYTHONPATH="/app/lib/lovense-controller${PYTHONPATH:+:$PYTHONPATH}"
# Gdy uruchamiane poza flatpakiem (lokalny install):
if [ -z "${FLATPAK_ID:-}" ]; then
  ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
  if [ -d "$ROOT/src" ]; then
    export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  fi
fi
exec python3 -m max2_controller "$@"
