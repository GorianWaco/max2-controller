#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

# PyGObject (gi) jest pakietem systemowym — venv musi mieć --system-site-packages
if [[ -d "${ROOT}/.venv" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT}/.venv/bin/activate"
fi

# Jeśli venv nie widzi gi, a system tak — użyj systemowego Pythona z venv site-packages
if ! python3 -c "import gi" 2>/dev/null; then
  if /usr/bin/python3 -c "import gi" 2>/dev/null; then
    echo "Uwaga: venv bez dostępu do PyGObject — używam /usr/bin/python3 + zależności z .venv"
    # dołącz pakiety z venv
    VENV_SITE="$(echo "${ROOT}"/.venv/lib/python*/site-packages)"
    export PYTHONPATH="${ROOT}/src:${VENV_SITE}${PYTHONPATH:+:$PYTHONPATH}"
    exec /usr/bin/python3 -m max2_controller "$@"
  fi
  echo "Brak PyGObject. Zainstaluj:  sudo pacman -S python-gobject gtk4 libadwaita"
  echo "Albo:  ./run.sh --web"
fi

exec python3 -m max2_controller "$@"
