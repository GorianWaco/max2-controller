#!/usr/bin/env bash
# Buduje plik .flatpak do instalacji u siebie / u partnerki
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_ID="pl.gorian.LovenseController"
MANIFEST="flatpak/pl.gorian.LovenseController.yml"
BUILD_DIR="flatpak/build"
REPO_DIR="flatpak/repo"
BUNDLE="dist/LovenseController.flatpak"

mkdir -p dist flatpak/build flatpak/repo

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Brak: $1"
    echo "  Arch/CachyOS:  sudo pacman -S flatpak flatpak-builder"
    exit 1
  fi
}

need flatpak
need flatpak-builder

echo "==> Runtime GNOME (pobierze się przy pierwszym buildzie)"
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo || true
flatpak install -y --user flathub org.gnome.Platform//48 org.gnome.Sdk//48 || \
  flatpak install -y --user flathub org.gnome.Platform//47 org.gnome.Sdk//47 || \
  flatpak install -y --user flathub org.gnome.Platform//46 org.gnome.Sdk//46 || true

# Jeśli 48 nie ma — spróbuj dostosować manifest
if ! flatpak info org.gnome.Platform//48 >/dev/null 2>&1; then
  for ver in 47 46 45; do
    if flatpak info "org.gnome.Platform//${ver}" >/dev/null 2>&1; then
      echo "Używam runtime GNOME ${ver}"
      sed -i "s/runtime-version: '48'/runtime-version: '${ver}'/" "$MANIFEST"
      break
    fi
  done
fi

echo "==> flatpak-builder"
flatpak-builder --force-clean --user --install-deps-from=flathub \
  --repo="$REPO_DIR" \
  "$BUILD_DIR" \
  "$MANIFEST"

echo "==> bundle → $BUNDLE"
flatpak build-bundle "$REPO_DIR" "$BUNDLE" "$APP_ID"

echo
echo "OK. Instalacja u siebie lub u partnerki:"
echo "  flatpak install --user $BUNDLE"
echo "  flatpak run $APP_ID"
echo
echo "Albo po buildzie (już w repo user):"
echo "  flatpak install --user --reinstall $REPO_DIR $APP_ID"
echo "  flatpak run $APP_ID"
