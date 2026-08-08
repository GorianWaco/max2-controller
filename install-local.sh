#!/usr/bin/env bash
# Szybka instalacja BEZ Flatpaka (venv + skrót w menu + ikona)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_ID="pl.gorian.LovenseController"
ICON_SRC_SVG="$ROOT/flatpak/icons/hicolor/scalable/apps/${APP_ID}.svg"

echo "==> Zależności systemowe (GTK, BLE, dźwięk)"
if command -v pacman >/dev/null; then
  echo "Upewnij się, że masz: python-gobject gtk4 libadwaita bluez gst-plugins-good pipewire"
  echo "  sudo pacman -S python-gobject gtk4 libadwaita bluez gst-plugins-good"
fi

echo "==> venv + pip"
python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" \
  "$HOME/.local/share/icons" "$HOME/.icons"

# launcher
cat > "$HOME/.local/bin/lovense-controller" << EOF
#!/usr/bin/env bash
export PYTHONPATH="${ROOT}/src\${PYTHONPATH:+:\$PYTHONPATH}"
if [[ -f "${ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT}/.venv/bin/activate"
fi
exec python3 -m max2_controller "\$@"
EOF
chmod +x "$HOME/.local/bin/lovense-controller"

# ── Ikona (nie piszemy do systemowego hicolor — często root-only) ──
install_icon_tree() {
  local base="$1"
  [[ -d "$(dirname "$base")" ]] || mkdir -p "$(dirname "$base")"
  mkdir -p "$base/scalable/apps" || return 1
  # test zapisu
  local t="$base/.write-test-$$"
  if ! touch "$t" 2>/dev/null; then
    return 1
  fi
  rm -f "$t"

  cp -f "$ICON_SRC_SVG" "$base/scalable/apps/${APP_ID}.svg"

  local size
  for size in 16 24 32 48 64 128 256 512; do
    mkdir -p "$base/${size}x${size}/apps"
    if command -v rsvg-convert >/dev/null 2>&1; then
      rsvg-convert -w "$size" -h "$size" -o "$base/${size}x${size}/apps/${APP_ID}.png" "$ICON_SRC_SVG" \
        || return 1
    elif command -v magick >/dev/null 2>&1; then
      magick -background none "$ICON_SRC_SVG" -resize "${size}x${size}" \
        "$base/${size}x${size}/apps/${APP_ID}.png" || return 1
    else
      # bez PNG — sam SVG (część motywów to łyknie)
      :
    fi
  done
  return 0
}

ICON_INSTALLED=""
for base in \
  "$HOME/.icons/hicolor" \
  "$HOME/.local/share/icons/hicolor-user" \
  "$HOME/.local/share/icons/hicolor"
do
  if install_icon_tree "$base"; then
    ICON_INSTALLED="$base"
    echo "==> Ikona: $base"
    # cache (best-effort)
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
      gtk-update-icon-cache -f -t "$base" 2>/dev/null || true
    fi
    break
  fi
done

# kopia „na wszelki wypadek” + absolutna ścieżka w .desktop
ICON_FALLBACK_DIR="$HOME/.local/share/icons"
mkdir -p "$ICON_FALLBACK_DIR"
cp -f "$ICON_SRC_SVG" "$ICON_FALLBACK_DIR/${APP_ID}.svg"
ICON_ABS="$ICON_FALLBACK_DIR/${APP_ID}.svg"
if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 256 -h 256 -o "$ICON_FALLBACK_DIR/${APP_ID}.png" "$ICON_SRC_SVG" 2>/dev/null \
    && ICON_ABS="$ICON_FALLBACK_DIR/${APP_ID}.png" || true
fi

# W .desktop: nazwa motywu (gdy hicolor zadziała) + fallback absolutny w polu Icon
# GNOME zwykle woli Icon=nazwa z hicolor; jeśli cache nie widzi — użyj ścieżki absolutnej.
ICON_FIELD="$APP_ID"
if [[ -z "$ICON_INSTALLED" ]]; then
  ICON_FIELD="$ICON_ABS"
  echo "==> Uwaga: hicolor niedostępny do zapisu — Icon= ścieżka absolutna"
else
  # podwójne: też absolutny PNG jako pewniak dla docka/taskbara
  if [[ -f "$ICON_ABS" && "$ICON_ABS" == *.png ]]; then
    ICON_FIELD="$ICON_ABS"
  fi
fi

cat > "$HOME/.local/share/applications/${APP_ID}.desktop" << EOF
[Desktop Entry]
Name=Lovense Controller
Name[pl]=Lovense Controller
Comment=Sterowanie Lovense z PC (Bluetooth, dźwięk, zdalnie)
Comment[pl]=Sterowanie zabawkami Lovense z komputera
Exec=${HOME}/.local/bin/lovense-controller
Icon=${ICON_FIELD}
Terminal=false
Type=Application
Categories=Utility;AudioVideo;
Keywords=lovense;bluetooth;toy;remote;
StartupNotify=true
StartupWMClass=pl.gorian.LovenseController
EOF

# odśwież bazę .desktop
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo
echo "Zainstalowano."
echo "  Uruchom:  lovense-controller"
echo "  albo z menu aplikacji: Lovense Controller"
echo "  Ikona:    $ICON_FIELD"
if [[ -n "$ICON_INSTALLED" ]]; then
  echo "  Motyw:    $ICON_INSTALLED"
fi
echo
echo "Jeśli w menu nadal domyślna ikona: wyloguj/zaloguj albo:"
echo "  gtk-update-icon-cache -f -t ~/.icons/hicolor"
echo
echo "Dla partnerki na innym PC — lepiej Flatpak:"
echo "  ./build-flatpak.sh"
echo "  potem wyślij: dist/LovenseController.flatpak"
