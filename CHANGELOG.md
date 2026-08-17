# Changelog

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
