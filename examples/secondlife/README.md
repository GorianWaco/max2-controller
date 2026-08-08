# Second Life HUD → Lovense Controller

Skrypt jest zrobiony jako **HUD na ekranie** (kafelek w rogu).  
Łączy się z aplikacją na PC przez te same endpointy `/sl/*` co panel web.

> Grid SL **nie widzi** `127.0.0.1` / zwykle `192.168.x` — potrzebny **tunnel HTTPS**.

## Zbuduj HUD (2 minuty)

1. W SL: **Build** → dowolny box (nawet default) — **skrypt sam go przerobi** na kafelek.
2. **Contents** → nowy skrypt → wklej z aplikacji:
   - GUI → **Zdalne → Second Life → Kopiuj skrypt LSL**  
     (BASE_URL + TOKEN już w środku).
3. Opcjonalnie: notecard **`lovense.cfg`** (przycisk **Kopiuj notecard cfg**).
4. Opcjonalnie: wrzuć **teksturę** do Contents (`lovense`, `hud`, albo dowolna pierwsza) — kafelek jej użyje.
   Bez tekstury: glass-rose (kolor + glow online/offline).
5. Weź obiekt do inventory → **Wear**  
   **albo** rez na ziemię i zaakceptuj prośbę **Attach** (HUD, prawy dół).

Kafelek pojawi się na **HUD (bottom-right)**.  
**Dotknij** = menu. Tekst nad kafelkiem: online / offline.

### Ręczne założenie na HUD
Inventory → obiekt → prawy przycisk → **Attach to HUD** → **Bottom Right**  
(albo inny róg — w notecardzie `HUD=38`).

## Na PC

1. Lovense Controller → zabawka połączona.  
2. **Panel web WŁ**.  
3. **Udostępnij przez internet** (Named = stały URL) albo Quick.  
4. Skopiuj skrypt / notecard z sekcji Second Life.

## Sterowanie

| Jak | Co |
|-----|-----|
| **Dotyk HUD** | Menu (STOP, siła, presety, długie, wzorce) |
| **⚙ Setup → Token / URL** | Niebieskie `llTextBox` — wklej token lub HTTPS tunnel |
| `/7 token` / `/7 url` | To samo okienko |
| `/7 stop` | STOP |
| `/7 status` | Ping do PC |
| `/7 v 12` | Wibracja 12 |
| `/7 i 0.6` | Intensywność 60% |
| `/7 preset marathon` | Długi preset |
| `/7 menu` | Otwórz dialog |

Przy pierwszym starcie (brak tokena / domyślny LAN URL) skrypt **sam** otwiera niebieskie okienko.

## Notecard `lovense.cfg` (opcjonalnie)

```
BASE_URL=https://twoj-tunnel.example.com
TOKEN=twoj_token
CHANNEL=7
DEFAULT_TIME=4
HUD=38
```

`HUD=38` = bottom-right (standard LSL).

## Bezpieczeństwo

- Token = hasło.  
- Nie dawaj HUD / notecard publicznie.  
- Na PC zawsze lokalny STOP.

## Pliki

| Plik | Opis |
|------|------|
| `LovenseController.lsl` | skrypt HUD |
| `lovense.cfg.example` | wzór notecard |

Ten sam skrypt jest w `src/max2_controller/secondlife/` (używany przez „Kopiuj skrypt LSL”).
