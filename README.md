# Lovense Controller

Program do sterowania **zabawkami Lovense** z komputera (Linux, GTK).  
Działa z **Max 2, Lush, Hush, Nora, Edge, Domi, Ambi** i innymi modelami BLE.

## Czy działa z innymi zabawkami Lovense?

**Tak.** Wspólny protokół Bluetooth. Po połączeniu program rozpoznaje model (`DeviceType`) i ustawia drugi suwak:

| Model | Suwak 1 | Suwak 2 |
|-------|---------|--------|
| Lush, Hush, Ambi, Domi, Ferri… | Vibrate | — |
| **Max / Max 2** | Vibrate | Pump (powietrze) |
| **Nora** | Vibrate | Rotate |
| **Edge** | Vibrate | Vibrate 2 |

Partnerka może użyć tego samego programu ze swoją zabawką (np. Lush) — ten sam Flatpak / te same źródła.

## Funkcje

| Funkcja | Opis |
|--------|------|
| Bluetooth BLE | bezpośrednio z PC, **bez telefonu** |
| Suwaki | Vibrate + druga funkcja zależnie od modelu |
| Szybkie poziomy | 0 / 25% / 50% / 75% / 100% + limit max |
| Tryby auto | oscylacja, losowy, ramp ↑/↓, boost |
| Czas / STOP | + panic hotkey |
| Presety / pattern | 8 presetów + własne + zapis ulubionych |
| Bateria | odczyt + auto-poll |
| Audio react | dźwięk z Firefoxa/gier lub mikrofon |
| API do gier | lokalne HTTP JSON |
| Hotkeys | **własne skróty w GUI** — chord + tryb gry |
| Zdalne sterowanie | panel web z tokenem (dla partnera) |
| Second Life | API `/sl/*` + gotowy skrypt LSL (HUD / collara) |

## Połączenie — **bez telefonu** (domyślne)

Program łączy się z Max 2 **bezpośrednio przez Bluetooth** komputera (biblioteka `bleak`).  
**Telefon i Lovense Connect nie są potrzebne.**

1. Włącz Bluetooth na PC (`bluetoothctl` / ustawienia systemu).
2. Włącz Max 2 (tryb parowania / włączony, blisko komputera).
3. **Zamknij** Lovense Remote / Connect / Intiface na innych urządzeniach — zabawka trzyma tylko **jedno** połączenie BLE.
4. W programie: backend **Bluetooth BLE (PC)** → **Skanuj BLE** → wybierz urządzenie → **Połącz BLE**.
5. Steruj suwakami Vibrate / Pump.

Wymagania Linux: działający adapter BLE (`hci0`), użytkownik w grupie uprawnień do BT (zwykle działa „out of the box” na CachyOS/Arch).

### Gdy PC nie ma Bluetooth: Lovense Remote na telefonie

Zabawkę trzyma **oficjalna apka na Androidzie**. Program na PC steruje nią po Wi‑Fi (Game Mode).

1. Telefon i PC w tej samej sieci Wi‑Fi.
2. Lovense Remote → zabawka połączona → **Game Mode** (IP + port na ekranie).
3. W programie: **Jak łączyć → Telefon (Lovense Remote)** → wpisz IP i port → **Połącz z telefonem**.
4. **Test połączenia** powinien pokazać zabawkę.

Gdy w PC nie ma adaptera BLE, ten tryb wybiera się sam.

Ręczny URL (gdy trzeba): `https://192-168-0-15.lovense.club:30010/command` (kropki w IP → myślniki).

## Instalacja

### Szybko u siebie (bez Flatpaka)

```bash
# CachyOS / Arch
sudo pacman -S python-gobject gtk4 libadwaita bluez gst-plugins-good

cd ~/Projekty/max2-controller
./install-local.sh
lovense-controller
# albo:
./run.sh
```

### Flatpak (do wysłania partnerce)

```bash
sudo pacman -S flatpak flatpak-builder
./build-flatpak.sh
# plik: dist/LovenseController.flatpak
# u niej:
flatpak install --user dist/LovenseController.flatpak
flatpak run pl.gorian.LovenseController
```

Szczegóły: [INSTALL-FOR-PARTNER.md](INSTALL-FOR-PARTNER.md)

Konfiguracja zapisuje się w `~/.config/max2-controller/config.json` (tokeny API, porty, URL).

## Reakcja na dźwięk

W GTK włącz **„Reakcja na dźwięk”**.

| Źródło | Co łapie |
|--------|----------|
| **Aplikacje** (domyślne) | Firefox, gry, YouTube — monitor **głośników** (nie mikrofon) |
| **Mikrofon** | Wejście mikrofonowe |

Technicznie: GStreamer `pulsesrc` na `<sink>.monitor` (na Focusrite `pw-record` bywa cichy — stąd GStreamer).

1. Połącz Max 2 (BLE).
2. Źródło: **Aplikacje**.
3. Wyjście: to samo co system (np. Scarlett) — Firefox musi grać na nie.
4. Włącz przełącznik, puść dźwięk.
5. W logu powinno być: `GStreamer → aplikacje/głośniki: ….monitor`.
6. Dostosuj **Czułość** / **Wzmocnienie**.

Skrót: `Ctrl+Shift+A` (lub `A` w trybie gry).

Wymaga: `gst-plugins-good` (pulsesrc) — na Arch: `sudo pacman -S gst-plugins-good`.

## Klawiatura — własne skróty

W GUI: sekcja **Klawiatura / skróty**.

1. Włącz **Skróty globalne**.
2. Opcjonalnie **Tryb gry** (pojedyncze klawisze globalnie — wygodne w grze, ostrożnie przy pisaniu).
3. Przy każdej akcji są dwa przyciski:
   - **Chord** — skrót z modyfikatorami (Ctrl/Alt/Shift)
   - **Gra** — pojedynczy klawisz
4. Kliknij przycisk → naciśnij klawisze → **Enter** (lub „Zapisz”). **Esc** anuluje, **Backspace** czyści.
5. **Przywróć domyślne skróty** wraca do fabrycznych.

Kolizje: nowy skrót „przejmuje” akcję, która go wcześniej miała (stara zostaje pusta).

Zapis: `~/.config/max2-controller/config.json` → `hotkeys_chord` / `hotkeys_game`.

### Domyślny tryb gry (gdy włączony)

| Klawisz | Akcja |
|---------|--------|
| `0`–`9` | siła (0=stop … 9=max) |
| `Spacja` / `S` | STOP |
| `+` / `-` | wibracja ±2 |
| `[` / `]` | 2. funkcja ±1 |
| `↑` `↓` | wibracja ±1 |
| `←` `→` | 2. funkcja ±1 |
| `Q`–`I` | 8 presetów |
| `A` | audio react |
| `B` | boost |
| `O` / `X` | oscylacja / losowy |
| `Z` | stop trybu auto |

### Domyślne chord (zawsze, gdy hotkeys włączone)

| Skrót | Akcja |
|-------|--------|
| `Ctrl+Shift+S` | STOP |
| `Ctrl+Shift+↑` / `↓` | wibracja ±1 |
| `Ctrl+Shift+←` / `→` | 2. funkcja ±1 |
| `Ctrl+Shift+1`–`8` | presety |
| `Ctrl+Alt+1`–`9` | poziomy |
| `Ctrl+Shift+A` | audio |
| `Ctrl+Shift+B` | boost |
| `Ctrl+Shift+O` / `X` | oscylacja / losowy |

Na Wayland globalne hotkeys mogą wymagać X11/XWayland lub uprawnień.  
Wyłącz: `hotkeys_enabled` / `hotkeys_game_mode` w configu lub przełącznikami w GUI.

## Rozszerzone sterowanie

| Element | Opis |
|---------|------|
| Szybko 0–100% | ustawia siłę względem **limitu max** |
| Limit max wibracji | miękki sufit 1–20 (bezpieczeństwo / preferencje) |
| Boost | skok do `control_boost_level` (domyślnie 20) |
| Oscylacja | góra–dół w zakresie z configu |
| Losowy | losowa siła co N ms |
| Ramp ↑/↓ | płynne dojście do limitu / zera w N sekund |
| Presety | pulse, wave, fireworks, earthquake, **tease, climb, edge, throb** |
| Zapis wzorca | nazwa + strength + interwał → lista „Zapisane” |

Parametry trybów auto w `config.json`: `control_oscillate_*`, `control_random_*`, `control_ramp_seconds`, `control_level_map`.

## API do gier (localhost)

Po włączeniu w GUI (domyślnie włączone):

```
http://127.0.0.1:8765
Header: X-API-Token: <token z GUI / config.json>
```

### Endpointy

| Method | Path | Body (JSON) |
|--------|------|-------------|
| GET | `/status` | — |
| GET | `/toys` | — |
| GET | `/battery` | — |
| POST | `/function` | `{"vibrate":10,"pump":2,"time_sec":0}` |
| POST | `/vibrate` | `{"level":12,"time_sec":3}` |
| POST | `/pump` | `{"level":2,"time_sec":3}` |
| POST | `/stop` | `{}` |
| POST | `/preset` | `{"name":"pulse","time_sec":8}` |
| POST | `/pattern` | `{"strength":"20;5;0","interval_ms":200,"time_sec":6}` |
| POST | `/backend` | `{"backend":"ble"}` lub `"lovense_local"` |
| POST | `/ble/scan` | `{"timeout":8}` |
| POST | `/ble/connect` | `{"address":"AA:BB:…"}` |
| POST | `/ble/disconnect` | `{}` |

### Przykład Python

```bash
export MAX2_TOKEN='…'
python examples/game_client.py
```

### Przykład curl

```bash
export MAX2_TOKEN='…'
bash examples/curl_cheatsheet.sh
```

### Pomysł pod grę

- obrażenia → `/function` z intensywnością zależną od HP
- loot / level-up → `/preset` pulse
- boss → mocniejszy pattern
- pause / death → `/stop`

## Zdalne sterowanie (inne osoby z daleka)

1. W GUI włącz **„Zdalne sterowanie”**.
2. Skopiuj link (`Kopiuj link`) — w LAN działa od razu:
   `http://TWOJE_IP:8787/panel?token=…`
3. **Przez internet** wystaw port bezpiecznie, np.:

```bash
# Cloudflare Tunnel (polecane)
cloudflared tunnel --url http://127.0.0.1:8787

# albo ngrok
ngrok http 8787

# albo Tailscale — daj drugiej osobie IP 100.x i port 8787
```

4. Wyślij **link z tokenem** tylko zaufanej osobie.
5. W każdej chwili wyłącz przełącznik w GUI albo wygeneruj **nowy token**.

### Bezpieczeństwo

- Token jest wymagany do każdej komendy.
- Możesz ograniczyć max vibrate/pump w `config.json` (`remote_max_vibrate`, `remote_max_pump`).
- Nie wystawiaj portu publicznie bez tokena / tunnelu z HTTPS.
- Zawsze masz lokalny **STOP** i hotkey panic.

## Second Life (skrypt LSL)

Grid SL **nie widzi** `127.0.0.1` ani `192.168.x` — skrypt woła publiczny HTTPS (`/sl/*`).

**Ważne:** Quick Cloudflare (`*.trycloudflare.com`) często **blokuje LSL** (Bot Fight / challenge).
Przeglądarka wtedy działa, HUD w SL dostaje 403. Do HUD użyj **ngrok**, **Tailscale Funnel**
albo **Named tunnel** z wyłączonym Bot Fight.

1. Włącz **panel web** w GUI (albo zostaw auto-start panelu + tunelu).
2. **Udostępnij przez internet** — tryb ngrok / Funnel (nie samo LAN).
3. Sekcja **Second Life** → **„Kopiuj skrypt LSL”** (wypełnia BASE_URL + TOKEN).
   Zapisuje też `~/.config/max2-controller/LovenseController.lsl`.
4. Wklej skrypt do HUD / collary wworld. Przycisk **Diagnostyka SL** sprawdza tunel
   z User-Agent jak z gridu.

### Endpointy (GET lub POST)

| Path | Parametry |
|------|-----------|
| `/sl/help` | — |
| `/sl/status` | `token` |
| `/sl/vibrate` | `token`, `level` 0–20, `time` |
| `/sl/intensity` | `token`, `i` 0.0–1.0, `time` |
| `/sl/function` | `token`, `v`, `p`, `t` |
| `/sl/stop` | `token` |
| `/sl/preset` | `token`, `name`, `time` |
| `/sl/pattern` | `token`, `strength`, `interval`, `time` |

### Komendy wworld (kanał 7)

```
/7 stop
/7 v 12
/7 i 0.6
/7 preset pulse
/7 status
```

Szczegóły: [examples/secondlife/README.md](examples/secondlife/README.md)

## Oficjalne API Lovense (opcjonalnie)

Ten projekt używa **lokalnego** Standard API (Game Mode).  
Do pełnej chmury Lovense (QR, developer token) zobacz:  
https://developer.lovense.com/docs/standard-solutions/standard-api

## Struktura

```
max2-controller/
├── run.sh
├── requirements.txt
├── README.md
├── examples/
│   ├── game_client.py
│   └── curl_cheatsheet.sh
└── src/max2_controller/
    ├── app.py
    ├── config.py
    ├── controller.py
    ├── hotkeys.py
    ├── backends/lovense_local.py
    ├── gui/main_window.py
    └── web/servers.py
```

## Rozwiązywanie problemów

| Problem | Co sprawdzić |
|---------|----------------|
| Brak połączenia | Aplikacja Lovense uruchomiona, zabawka connected, poprawny URL/port |
| HTTPS cert error | Program domyślnie `verify_ssl: false` dla `*.lovense.club` |
| Puste GetToys | Zabawka sparowana w Lovense, nie w innej apce BLE jednocześnie |
| Hotkeys nie działają | Wayland/X11 permissions; wyłącz w configu |
| Remote nie działa z internetu | Firewall + tunnel; w LAN sprawdź IP i port 8787 |
| HUD SL offline / HTTP 0 / 499 | BASE_URL jest `192.168` albo `127.0.0.1` — grid tego nie widzi. Włącz tunel HTTPS i skopiuj skrypt ponownie |
| HUD SL HTTP 403, przeglądarka OK | Cloudflare Bot Fight. Zmień tunel na ngrok / Tailscale Funnel / Named (wyłącz Bot Fight) |
| Panel w przeglądarce „nie łączy” | Panel web musi być WŁ; stary link `trycloudflare` umiera po restarcie — nowy „Udostępnij” |
| Po reinstalacji Linuksa nic nie słucha | Auto-start panelu+tunelu, albo włącz przełącznik Zdalne. Test: `http://127.0.0.1:8787/health` |

## Licencja / odpowiedzialność

Narzędzie do prywatnego użytku z własnym sprzętem.  
Używaj świadomie, z zgodą wszystkich osób mających dostęp do zdalnego sterowania.
