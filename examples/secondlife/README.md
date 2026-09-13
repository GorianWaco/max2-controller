# Second Life — obiekt na awatarze (bez tunelu)

Program na PC **sam dzwoni do obiektu** w SL.  
Nie potrzebujesz Cloudflare, ngrok ani notatki.

## Zrób to raz

1. Lovense Controller → **Zdalne** → **1. Kopiuj skrypt SL**.
2. W SL: Build → box → nowy skrypt → wklej wszystko.
3. **Włączony** + **Mono** → Zapisz.
4. Inventory → **Wear** na **głowę albo klatkę** (nie HUD).
5. Klik kuli (jako owner) → **URL** — wtedy dostajesz **PAIR URL** (`https://sim….lindenlab.com/cap/…`). Wear sam nic nie wypisuje.
6. W programie wklej ten URL → **Połącz**.
7. Status: **Połączone z obiektem SL**.

Klik kuli = menu. Każdy może sterować (albo Lock = tylko Ty).

Zwykły **Cube** z Build sam zmienia się w mały różowy orb nad głową. **Mesh** (`LovenseController.dae` — organiczne szkło cyan/magenta) skrypt zostawia w spokoju. Gdy zabawka działa, orb **tryska particle** i świeci — im mocniej wibruje, tym gęstszy spray. STOP gasi particle od razu.

Opcjonalne tekstury w Contents (dokładne nazwy): `lovense_offline`, `lovense_online`, `lovense_active`. Bez nich orb i tak świeci kolorem.

URL zmienia się po resecie skryptu / zmianie regionu — klik **URL** i wklej nowy PAIR URL.

## Hover text

Twój klik → **Setup → Hover** → wpisz tekst nad pręcikiem.  
Puste pole = wraca `✦  Lovense`. Nowa linia: `\n`.

Albo w notatce `lovense.cfg`:

```
HOVER=play with me
```

Hover jest wyłączony po starcie. Włącz: **Setup → Show text**.
Kolor tekstu: **Setup → Color** (albo Custom: `r g b`). Wymaga skryptu **LovenseEnergy.lsl** w Glass.

Gdy zabawka na PC jest **offline**, kliknięcia z kuli ładują pasek **Energy**. Po połączeniu zabawki: **Setup → Stats → Replay** (albo w programie **Odtwórz kolejkę**) — wibracje idą po kolei. **Clear E** czyści zapas.
Komunikaty nie idą na publiczny local chat (tylko owner / IM do klikającego).

## Tip jar (L$ → zabawka)

Osobne **naczynie na ziemi** (`mesh/LovenseTipJar.dae`). Nie wkładaj skryptu jara do kuli — Pay na attachmentach w SL jest zawodne.

1. Upload `LovenseTipJar.dae` (Build → Upload → Model). High LOD. Physics: Analyze → Convex Hull. **Nie** centruje mesha — origin jest w stopie.
2. Rez naczynie raz, wklej skrypt tip jara, Save. Weź **kopię** (Copy) do ekwipunku, nazwij `LovenseTipJar`.
3. Włóż tę kopię do **Glass (root)** kuli — Contents. Musi być Copy, inaczej wyleci z kuli przy rezowaniu.
4. Do Glass wklej też **host jara** (`LovenseJarHost.lsl`) jako trzeci skrypt obok kontrolera i wyglądu.
5. Załóż kulę. Niebieskie menu → **Rez jar** — naczynie spada pod stopy. **Kill jar** je zbiera.
5. Inni: lewy klik naczynia = **Pay** (L$10 / 50 / 100 / 250). Ty: `/77 jar` albo kula → Setup → Tip jar.

Opcjonalna notatka `tipjar.cfg` — patrz `tipjar.cfg.example`.

Kula zostaje menu wibracji. Napiwek leci z naczynia do kuli, potem PC odpytuje PAIR URL.

Statystyki: kula → **Setup → Stats** → **Clear uses** (ile razy ktoś odpalił zabawkę), **Clear tips** (sesja L$ na hoverze i w naczyniu), **Clear all**.

## Potrzeby nad głową (Sims)

Paski **Horny / Hygiene / Hugs / Social** są hoverem nad kulą (nie HUD na ekranie).

1. Lovense Controller → **Zdalne** → **Kopiuj skrypt potrzeb**.
2. W SL otwórz **tę samą kulę** (Content).
3. **New Script** (drugi skrypt, nie kasuj pierwszego) → wklej → **Save**.
4. Nad głową pojawią się 4 paski.

| Potrzeba | Co robi |
|----------|---------|
| **Horny** | Rośnie, gdy ktoś kliknie kulę i włączy wibracje; dalej rośnie, dopóki zabawka działa. |
| **Hygiene** | Powoli spada po (i w trakcie) wibracji. Wejdź w wodę sima (ocean, staw Linden), żeby się umyć — nad głową pojawi się `washing`. |
| **Hugs** | Rośnie, gdy ktoś stoi bardzo blisko Ciebie (~1,5 m). |
| **Social** | Ładuje się od liczby awatarów w promieniu 20 m. |

Stan jest w **linkset data** obiektu: token, ustawienia kuli i wartości potrzeb **nie zerują się** po teście, resecie skryptu ani zmianie regionu. Menu: kula → **Setup → Needs**.

Opcjonalna notatka w kuli, nazwa dokładnie `needs.cfg`:

```
HUG_RANGE=1.5
SOCIAL_RANGE=20
HORNY_QUEUE=10
HORNY_PER_MIN=12
HYGIENE_DRAIN=0.8
HYGIENE_WASH=80
HUGS_PER_MIN=14
SOCIAL_PER_PERSON=3
```
