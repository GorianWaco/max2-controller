# Changelog

## 2.6.2 — 2026-09-11

`LovenseLook.lsl`: kuleczki ślizgają się po powierzchni orba (nie krążą wokół pozycji spoczynkowej), każda ma własny promień, rozmiar i tempo pulsu. Particle do avatara lecą wolniej i dłużej.

## 2.6.1 — 2026-09-09

Audio pasma: włączniki **wibracje / pump od basu** i **wibracje / pump od treble**.
Kick może iść na pompę, hi-hat na wibracje, albo oba naraz (max).

## 2.6.0 — 2026-09-09

Audio: **bas → wibracje, treble → 2. funkcja** (pump / rotate / silnik 2). Filtry IIR (kick nie wycieka do hi-hat).
W GTK i panelu partnerskim: przełącznik + wzmocnienie basu/treble + granice Hz (host).
Wyłączenie wraca do starego detektora (cały poziom).

## 2.5.1 — 2026-08-31

Energia i kolor hoveru są w osobnym skrypcie `LovenseEnergy.lsl` (Glass), żeby Core nie wpadał w Stack-Heap.

## 2.5.0 — 2026-08-30

Gdy zabawka jest offline, wibracje z SL ładują **energię** (kolejka). Po połączeniu: **Odtwórz kolejkę** w programie albo kula → Setup → Stats → Replay. Pasek Energy nad kulą. Kolor hoveru: Setup → Color.

## 2.4.2 — 2026-08-30

Rezowanie tip jara i kanał `TJ|` są w osobnym skrypcie `LovenseJarHost.lsl` (trzeci skrypt w Glass), żeby Core nie wpadał w Stack-Heap Collision.

## 2.4.1 — 2026-08-30

Kula rezzuje tip jar pod stopami: niebieskie menu → **Rez jar**. Kopia naczynia (`LovenseTipJar`) musi leżeć w Contents Glass.

## 2.4.0 — 2026-08-30

Tip jar jest osobnym naczyniem na ziemi (`LovenseTipJar.dae`), nie skryptem w kuli. Lewy klik naczynia = Pay. Kula zostaje menu wibracji. Handshake `TJ|hello` / `TJ|pong` w regionie.

## 2.3.0 — 2026-08-30

Magiczny orb nad głową: sześcian z Build staje się małą kulą (mesh zostaje). Gdy zabawka chodzi, orb tryska particle i świeci mocniej (siła = wibracje). STOP gasi spray od razu.

PAIR URL nie wypisuje się przy Wear / zmianie sima. Owner wywołuje go sam: klik kuli → **URL**.

Mesh `LovenseController.dae`: organiczny szklany orb (nachodzące membrany cyan/magenta). Róża zostaje jako `LovenseRose.dae`.

Orbit: wewnętrzne kawałki linksetu (Pink/Cyan/Core) powoli krążą w środku orba. Jeden mesh = brak ruchu (trzeba upload jako linkset). Setup → Orbit.

Wygląd (particle, glow, orbit, kształt) jest w osobnym skrypcie `LovenseLook.lsl` — wklej go jako drugi skrypt do Glass. Kontroler bez tego nie puchnie do Stack-Heap.

## 2.2.0 — 2026-08-30

Tip jar Second Life (L$ → wibracje): jeden skrypt, wersja na awatarze (Wear) i na ziemi (rez). Komendy idą do sparowanej kuli. GUI: **Kopiuj skrypt tip jara**.

## 2.1.0 — 2026-08-18

Potrzeby Sims (Horny, Hygiene, Hugs, Social) jako hover nad kulą na głowie. Token, ustawienia i stan w linkset data — nie giną po zmianie sima.

## 2.0.3 — 2026-08-17

Obiekt SL jest kulą. Nowe tekstury sferyczne (`lovense_offline/online/active`).

## 2.0.2 — 2026-08-17

Obiekt SL: krążek z nowymi teksturami. Hover wraca do 0% po końcu timed akcji.

## 2.0.1 — 2026-08-17

Obiekt SL nad głową: neonowy pręcik (cylinder, połysk, światło), zamiast szarego boxa.

## 2.0.0 — 2026-08-17

Prostsze łączenie z Second Life: obiekt dostaje URL od grida, program na PC go odpytuje.
Bez Cloudflare / tunelu / notatki. W GUI: Kopiuj skrypt → wklej PAIR URL → Połącz.

## 1.9.2 — 2026-08-17

Wybór tunelu z powrotem w GUI. Quick Cloudflare działa w przeglądarce, ale Second Life zwykle nie — do obiektu SL: SSH localhost.run albo ngrok.

## 1.9.1 — 2026-08-17

Koniec okienka „Authentication is required to flush DNS caches” — program nie woła już `resolvectl` bez roota.

## 1.9.0 — 2026-08-17

Second Life: zamiast HUDa jest obiekt na awatarze. Klik paska otwiera menu — sterować może każdy.
Właściciel: Setup (URL/token) i Lock. W GUI jeden przycisk **Kopiuj skrypt SL**.

## 1.8.3 — 2026-08-17

Panel web: język Português.

## 1.8.2 — 2026-08-17

Quick Cloudflare: nie pokazuj / nie kopiuj adresu zanim `/health` naprawdę działa.
Żywy tunel ma pierwszeństwo przed starym `*.trycloudflare.com` (Error 1016 = martwy hostname).

## 1.8.1 — 2026-08-17

LSL: `HTTP_PRAGMA` → `HTTP_PRAGMA_NO_CACHE` (kompilator SL: Name not defined).

## 1.8.0 — 2026-08-17

Pasek na awatarze w Second Life: na żywo pokazuje siłę wibracji.
Każdy, kto kliknie pasek, dostaje HUD do sterowania (obiekt `Lovense HUD` w Contents).
W GUI: **Kopiuj HUD** i **Kopiuj pasek**.

## 1.7.0 — 2026-08-17

Wybór języka w webowym kontrolerze: Polski, English, Deutsch, Français, Español, Italiano, Русский.
Język zapamiętywany w przeglądarce; start z języka przeglądarki.
Skrypt LSL i notecard `lovense.cfg` generowane przez program zostają po angielsku.

## 1.6.0 — 2026-08-17

Tryb bez Bluetooth: Lovense Remote na telefonie (Game Mode).
Wpisujesz IP i port, program składa URL i testuje połączenie.
Brak adaptera BLE → ten tryb włączany sam.

## 1.5.1 — 2026-08-17

Po starcie tunelu program czeka aż `https://…trycloudflare.com/health` naprawdę odpowiada
i czyści cache NXDOMAIN w systemd-resolved. Inaczej przeglądarka dostawała
„witryna nieosiągalna” (DNS_PROBE_POSSIBLE) na jeszcze nieopublikowany hostname.

## 1.5.0 — 2026-08-17

Zdalne sterowanie: jeden przełącznik, adres panelu partnerki, kopiowanie skryptu LSL i notatki z tokenem. Tunel startuje w tle.

## 1.4.0 — 2026-08-17

Po świeżej instalacji Linuksa HUD w Second Life i panel w przeglądarce nie łączyły się.

- Panel web + tunel startują razem, gdy włączony jest auto-start (wcześniej `remote_enabled=false` gasił wszystko).
- BASE_URL dla LSL bierze publiczny HTTPS tunelu, nie `http://192.168…` (grid SL tego nie widzi).
- Skrypt HUD rozpoznaje wszystkie prywatne IP, nie tylko placeholder `192.168.1.10`.
- Lepsze błędy HUD: 403 Cloudflare Bot Fight vs wyłączony panel; HTTP 0/499 = brak publicznego URL.
- Diagnostyka SL z User-Agent jak z `llHTTPRequest`.
- ProxyFix + CORS `X-Session-Id` — poprawne `https://` za tunellem.
- `/sl/ping` bez tokenu, `/diag` do sprawdzenia Host/scheme.
- Tryby tunelu: ngrok, Tailscale Funnel, SSH localhost.run (Quick Cloudflare często blokuje LSL).
- Martwe URL `trycloudflare` nie są pokazywane jako żywe po restarcie.

## 1.3.0

- HUD Second Life, panel partnerski, tunel Cloudflare, multi-toy BLE.
