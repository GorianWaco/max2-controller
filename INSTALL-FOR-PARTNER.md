# Lovense Controller — instalacja (dla Ciebie / partnerki)

Program steruje **zabawkami Lovense** z komputera (Linux): Lush, Hush, Max 2, Nora, Edge, Domi i inne.

Nie wymaga telefonu (Bluetooth bezpośrednio z PC).

---

## Opcja A — Flatpak (zalecane do udostępnienia)

### U twórcy (zbuduj raz)

```bash
cd ~/Projekty/max2-controller   # lub sklonowany katalog
sudo pacman -S flatpak flatpak-builder   # jeśli nie ma
./build-flatpak.sh
```

Powstanie plik:

`dist/LovenseController.flatpak`

Wyślij go partnerce (Pendrive, Syncthing, chmura…).

### U partnerki (instalacja)

```bash
# Flatpak musi być zainstalowany
sudo pacman -S flatpak          # Arch/CachyOS
# sudo apt install flatpak      # Debian/Ubuntu

flatpak install --user LovenseController.flatpak
flatpak run pl.gorian.LovenseController
```

Albo dwuklik na pliku `.flatpak` w menedżerze plików (jeśli system to obsługuje).

**Uwagi Flatpak + Bluetooth:**  
Aplikacja ma uprawnienia do BlueZ i urządzeń. Jeśli skan BLE nic nie znajdzie:

```bash
# upewnij się, że Bluetooth działa poza flatpakiem
bluetoothctl show
# czasem pomaga:
flatpak override --user --device=all pl.gorian.LovenseController
```

---

## Opcja B — instalacja ze źródeł (bez Flatpaka)

```bash
# 1. skopiuj cały folder projektu
cd lovense-controller   # nazwa katalogu
./install-local.sh

# 2. uruchom
lovense-controller
```

Zależności (Arch/CachyOS):

```bash
sudo pacman -S python-gobject gtk4 libadwaita bluez \
  gst-plugins-good pipewire-pulse
```

---

## Pierwsze uruchomienie

1. Włącz zabawkę Lovense blisko PC.
2. **Zamknij** Lovense Remote na telefonie (tylko jedno połączenie BLE).
3. W programie: **Skanuj BLE** → wybierz urządzenie → **Połącz BLE**.
4. Suwaki / klawisze / audio / zdalne sterowanie.

### Modele

| Zabawka | Główna funkcja | Drugi suwak |
|---------|----------------|-------------|
| Lush, Hush, Ambi, Domi… | Vibrate | — |
| Max / Max 2 | Vibrate | Pump (powietrze) |
| Nora | Vibrate | Rotate |
| Edge | Vibrate | Vibrate 2 |

### Zdalne sterowanie (dla partnera w sieci)

1. Włącz **Zdalne sterowanie** w programie.
2. **Kopiuj link** i wyślij (w domu = sieć Wi‑Fi).
3. Przez internet: `cloudflared tunnel --url http://127.0.0.1:8787` lub Tailscale.

---

## Prywatność

- Zdalny panel wymaga **tokena** (linku).
- Można wyłączyć zdalne sterowanie w każdej chwili i wygenerować nowy token.
- API do gier domyślnie tylko na `127.0.0.1`.
