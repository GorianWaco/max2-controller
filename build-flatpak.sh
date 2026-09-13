#!/usr/bin/env bash
# Buduje plik .flatpak do instalacji u siebie / u partnerki
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_ID="pl.gorian.LovenseController"
MANIFEST="flatpak/pl.gorian.LovenseController.yml"
BUILD_DIR="flatpak/build"
REPO_DIR="flatpak/repo"
VERSION=$(python3 -c "import pathlib,re; t=pathlib.Path('src/max2_controller/__init__.py').read_text(); print(re.search(r'__version__\\s*=\\s*\"([^\"]+)\"', t).group(1))" 2>/dev/null || echo "2.0.0")
BUNDLE="dist/LovenseController-${VERSION}.flatpak"

mkdir -p dist flatpak/build flatpak/repo

BUILDER=()
if command -v flatpak-builder >/dev/null 2>&1; then
  BUILDER=(flatpak-builder)
elif flatpak info --user org.flatpak.Builder >/dev/null 2>&1 || flatpak info org.flatpak.Builder >/dev/null 2>&1; then
  BUILDER=(
    flatpak run
    --filesystem=home
    --share=network
    --env=FLATPAK_USER_DIR="${HOME}/.local/share/flatpak"
    --command=flatpak-builder
    org.flatpak.Builder
  )
else
  echo "Brak flatpak-builder."
  echo "  sudo pacman -S flatpak-builder"
  echo "  albo: flatpak install --user flathub org.flatpak.Builder"
  exit 1
fi

echo "==> Runtime GNOME 50"
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo || true
flatpak install -y --user flathub org.gnome.Platform//50 org.gnome.Sdk//50 || true

echo "==> flatpak-builder (${BUILDER[*]})"
"${BUILDER[@]}" --force-clean --user --install-deps-from=flathub \
  --repo="$REPO_DIR" \
  "$BUILD_DIR" \
  "$MANIFEST"

echo "==> bundle → $BUNDLE"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$REPO_DIR" "$BUNDLE" "$APP_ID"
ln -sfn "$(basename "$BUNDLE")" dist/LovenseController.flatpak

echo
echo "OK. Instalacja u siebie lub u partnerki:"
echo "  flatpak install --user $BUNDLE"
echo "  flatpak run $APP_ID"
echo
echo "Albo po buildzie (już w repo user):"
echo "  flatpak install --user --reinstall $REPO_DIR $APP_ID"
echo "  flatpak run $APP_ID"
