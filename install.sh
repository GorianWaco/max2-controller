#!/usr/bin/env bash
# Instalator Lovense Controller — native (venv) albo Flatpak.
#
# Znajomi / partnerka:
#   curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash -s -- --flatpak

set -euo pipefail

REPO="GorianWaco/max2-controller"
APP_NAME="Lovense Controller"
FLATPAK_ID="pl.gorian.LovenseController"
FLATHUB_REPO="https://dl.flathub.org/repo/flathub.flatpakrepo"

MODE="native"
LOCAL_BUNDLE=""
UNINSTALL=0
NO_DEPS=0

usage() {
  cat <<EOF
Użycie: $0 [opcje]

  (domyślnie)     native: zależności + venv + skrót w menu
  --flatpak       Flatpak z GitHub Releases (albo --local PLIK)
  --local PLIK    zainstaluj istniejący .flatpak
  --no-deps       nie instaluj pakietów systemowych
  --uninstall     odinstaluj native i Flatpak
  -h, --help      ta pomoc

Jedna komenda:
  curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash -s -- --flatpak
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --flatpak) MODE="flatpak"; shift ;;
    --local) LOCAL_BUNDLE="${2:?}"; MODE="flatpak"; shift 2 ;;
    --no-deps) NO_DEPS=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Nieznana opcja: $1" >&2; usage >&2; exit 1 ;;
  esac
done

info() { printf '==> %s\n' "$*"; }
die()  { printf 'Błąd: %s\n' "$*" >&2; exit 1; }

sudo_cmd() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "Potrzebuję sudo do pakietów. Zainstaluj je ręcznie albo: $0 --no-deps"
  fi
}

source_dir() {
  local self="${BASH_SOURCE[0]:-}"
  if [[ -n "$self" && -f "$self" ]]; then
    local dir
    dir="$(cd "$(dirname "$self")" && pwd)"
    if [[ -f "$dir/install-local.sh" && -d "$dir/src/max2_controller" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
  fi
  return 1
}

install_system_deps() {
  [[ "$NO_DEPS" -eq 1 ]] && return 0
  info "Zależności: GTK4, BLE, dźwięk, Python"
  if command -v pacman >/dev/null 2>&1; then
    sudo_cmd pacman -S --needed --noconfirm \
      python python-pip python-gobject gtk4 libadwaita bluez \
      gst-plugins-good pipewire pipewire-pulse python-cairo
  elif command -v dnf >/dev/null 2>&1; then
    sudo_cmd dnf install -y python3 python3-pip python3-gobject gtk4 libadwaita \
      bluez gstreamer1-plugins-good pipewire python3-cairo
  elif command -v apt-get >/dev/null 2>&1; then
    sudo_cmd apt-get update -y
    sudo_cmd apt-get install -y python3 python3-pip python3-gi python3-gi-cairo \
      gir1.2-gtk-4.0 gir1.2-adw-1 bluez gstreamer1.0-plugins-good pipewire \
      python3-venv
  else
    echo "! Nie znam dystrybucji. Doinstaluj: python3-gobject gtk4 libadwaita bluez"
  fi
}

fetch_sources() {
  if src="$(source_dir)"; then
    printf '%s\n' "$src"
    return 0
  fi
  command -v git >/dev/null 2>&1 || {
    if command -v pacman >/dev/null 2>&1; then sudo_cmd pacman -S --needed --noconfirm git
    elif command -v apt-get >/dev/null 2>&1; then sudo_cmd apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then sudo_cmd dnf install -y git
    else die "Zainstaluj git."; fi
  }
  local dest="${HOME}/.local/share/lovense-controller/src"
  info "Pobieram źródła do ${dest}"
  mkdir -p "$(dirname "$dest")"
  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" pull --ff-only || true
  else
    rm -rf "$dest"
    git clone --depth 1 "https://github.com/${REPO}.git" "$dest"
  fi
  printf '%s\n' "$dest"
}

ensure_flatpak() {
  command -v flatpak >/dev/null 2>&1 && return
  info "Instaluję Flatpak…"
  if command -v pacman >/dev/null 2>&1; then sudo_cmd pacman -S --needed --noconfirm flatpak
  elif command -v dnf >/dev/null 2>&1; then sudo_cmd dnf install -y flatpak
  elif command -v apt-get >/dev/null 2>&1; then sudo_cmd apt-get update -y && sudo_cmd apt-get install -y flatpak
  else die "Zainstaluj flatpak."; fi
}

ensure_flathub() {
  if flatpak remotes 2>/dev/null | awk '{print $1}' | grep -qx flathub; then
    return
  fi
  flatpak remote-add --if-not-exists --user flathub "$FLATHUB_REPO"
}

latest_flatpak_url() {
  command -v curl >/dev/null 2>&1 || die "Brak curl."
  local json url
  json=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest") || \
    die "Nie udało się odczytać GitHub Releases."
  url=$(printf '%s' "$json" | grep -oE "https://github.com/${REPO}/releases/download/[^\"[:space:]]+\\.flatpak" | head -n1)
  [[ -n "$url" ]] || die "W release nie ma .flatpak — użyj ./install.sh (native)."
  printf '%s\n' "$url"
}

uninstall_all() {
  info "Odinstalowuję ${APP_NAME}"
  if command -v flatpak >/dev/null 2>&1; then
    flatpak uninstall --user -y "$FLATPAK_ID" >/dev/null 2>&1 || true
  fi
  rm -f "${HOME}/.local/bin/lovense-controller"
  rm -f "${HOME}/.local/share/applications/${FLATPAK_ID}.desktop"
  rm -f "${HOME}/.local/share/icons/${FLATPAK_ID}.svg" "${HOME}/.local/share/icons/${FLATPAK_ID}.png"
  echo "Usunięto skróty. venv w katalogu projektu zostawiam."
}

install_flatpak() {
  ensure_flatpak
  ensure_flathub
  local bundle="$LOCAL_BUNDLE"
  if [[ -z "$bundle" ]]; then
    local src
    src="$(source_dir || true)"
    if [[ -n "$src" ]]; then
      local local_dist
      local_dist="$(ls -1t "$src"/dist/LovenseController*.flatpak 2>/dev/null | head -n1 || true)"
      [[ -n "$local_dist" ]] && bundle="$local_dist"
    fi
  fi
  if [[ -z "$bundle" ]]; then
    local tmp dest url
    tmp="$(mktemp -d)"
    info "Pobieram Flatpak z GitHub Releases…"
    url="$(latest_flatpak_url)"
    dest="$tmp/$(basename "$url")"
    curl -fL --progress-bar -o "$dest" "$url"
    bundle="$dest"
  fi
  [[ -f "$bundle" ]] || die "Nie ma pliku: $bundle"
  if flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1; then
    flatpak uninstall --user -y "$FLATPAK_ID" >/dev/null 2>&1 || true
  fi
  info "Instaluję Flatpak…"
  flatpak install --user -y "$bundle"
  echo
  echo "✓ ${APP_NAME} (Flatpak)"
  echo "  flatpak run ${FLATPAK_ID}"
  echo "Jeśli BLE nic nie widzi:  flatpak override --user --device=all ${FLATPAK_ID}"
}

install_native() {
  local src
  src="$(fetch_sources)"
  install_system_deps
  NO_DEPS=1 "$src/install-local.sh"
}

echo "=========================================="
echo "  ${APP_NAME}"
echo "=========================================="

if [[ "$UNINSTALL" -eq 1 ]]; then
  uninstall_all
  exit 0
fi

if [[ "$MODE" == "flatpak" ]]; then
  install_flatpak
else
  install_native
fi
