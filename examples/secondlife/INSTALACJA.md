# Instrukcja: Lovense + potrzeby w Second Life

Potrzebujesz **jednej kuli na głowie** z **dwoma skryptami** w środku:

1. **Kontroler** — inni klikają kulę i sterują zabawką.
2. **Potrzeby** — hover nad głową: Horny, Hygiene, Hugs, Social.

Program Lovense Controller musi działać na PC.

---

## 0. Zanim wejdziesz do SL

1. Uruchom **Lovense Controller** na komputerze.
2. Podłącz zabawkę (albo tryb Lovense Remote / Game Mode).
3. Wejdź w zakładkę **Zdalne**.
4. Zostaw program włączony — to on odpytuje kulę w SL.

Nie potrzebujesz Cloudflare ani tunelu do samej kuli.

---

## 1. Kula na ciele (sterowanie)

### Skopiuj skrypt

W programie: **Zdalne → 1. Kopiuj skrypt SL**.

Skrypt jest w schowku. Jest też zapisany jako plik `LovenseController.lsl` w katalogu konfiguracji programu.

### Zrób obiekt w SL

1. W SL: **Build** (Ctrl+B) → postaw **Cube**.
2. W edytorze: zakładka **Content**.
3. **New Script**.
4. Otwórz skrypt, **zaznacz wszystko** (Ctrl+A), skasuj, **wklej** skrypt ze schowka.
5. Zaznacz **Running** (Włączony).
6. Kompilator: **Mono** (albo domyślny w nowszym viewerze).
7. **Save**. Poczekaj aż zniknie błąd kompilacji.

Sześcian sam zmieni się w **mały magiczny orb** (różowa kula, glow). Na głowie skrypt uniesie go ~22 cm, jeśli jeszcze nie był ruszany. **Mesh** (upload modelu) skrypt nie rusza — particle i tak z niego polecą, gdy zabawka działa.

### Uprawnienia obiektu

W zakładce **General**:

- nazwa może zostać — skrypt i tak zmieni ją na `Lovense`
- **Next owner** nie musi mieć Modify (to Twoja kula)
- zostaw obiekt **na ziemi** na chwilę albo od razu weź do ekwipunku

### Załóż na ciało (NIE na HUD)

1. Weź obiekt do Inventory.
2. Klik prawym → **Wear** / **Add**.
3. W **Attachments** wybierz **Skull (głowa)** albo **Chest (klatka)**.
4. **Nie** zakładaj na punkty HUD (ekran). Inni wtedy nie klikną kuli.

Skrypt zmienia **tylko zwykły Cube** w kulę. Mesh zostaje. Particle lecą z obiektu, gdy zabawka chodzi (gęstość = siła wibracji). Mesh na wypasie: upload **jako linkset** (Glass = root). Do Glass wklej **dwa** skrypty: kontroler + **skrypt wyglądu** (`LovenseLook.lsl` — particle, glow, ślizg po powierzchni, puls). Z Core/Pink/Cyan skasuj **wszystkie** skrypty (Stack-Heap = ciężki skrypt w dziecku). Face `Glass` ~40% alpha + shiny. Setup → Orbit. Po Wear kliknij **Yes / Allow** przy Attach.

Tekstury kuli (opcjonalnie) wrzuć do Contents pod nazwami `lovense_offline` / `lovense_online` / `lovense_active` — patrz `textures/README.md`.

### Połącz z programem

Wear **nie** wypisuje linka. Gdy chcesz się sparować:

1. Klik kuli (jako owner) → **URL**.
2. W czacie właściciela (nie w lokalu) pojawi się:

```
PAIR URL — paste in Lovense Controller → Second Life:
https://sim….lindenlab.com:12043/cap/…
```

3. Skopiuj **cały** ten adres (od `https://` do końca).
4. W programie, pole **2. Wklej PAIR URL z czatu SL**.
5. **Połącz**.
6. Status: **Połączone z obiektem SL**.

Hover nad kulą jest **wyłączony** na starcie (nikt nie widzi tekstu nad głową).
Włączysz go u siebie: klik kuli → **Setup → Show text**.

### Token (opcjonalnie, ale warto)

Jeśli skrypt pyta o TOKEN:

1. W programie skopiuj token z sekcji Zdalne (ten sam, co do panelu).
2. Wklej w okienko w SL.

Token zapisuje się w obiekcie i **zostaje po zmianie sima**. Nie musisz wpisywać go za każdym teleportem.

Możesz też wrzucić do kuli notatkę o **dokładnej** nazwie `lovense.cfg`:

```
TOKEN=wklej_token_z_programu
DEFAULT_TIME=4
ATTACH=2
PUBLIC=1
HOVER=✦  Lovense
```

### Sprawdź sterowanie

Kliknij kulę (albo niech kliknie partnerka):

- menu: 25% / 50% / MAX / Presets / STOP
- **Setup → Lock** = tylko Ty sterujesz
- **Setup → Unlock** = każdy może kliknąć

Jeśli zabawka zadrżała — kula działa. Nad głową powinien tryskać różowy spray (particle). Siła sprayu rośnie z wibracją.

---

## 2. Potrzeby nad głową (ten sam obiekt)

Nie rób drugiego boxa i nie zakładaj nic na ekran.

### Skopiuj skrypt potrzeb

W programie: **Zdalne → Kopiuj skrypt potrzeb**.

### Wklej jako DRUGI skrypt do kuli

1. Kliknij założoną kulę → **Edit**.
2. Zakładka **Content**.
3. Powinieneś widzieć już pierwszy skrypt (kontroler). **Nie kasuj go.**
4. **New Script**.
5. Wklej skrypt potrzeb, **Save**.
6. Nad kulą (nad głową) pojawią się paski:

```
✦  Needs
Horny    ●●○○○○○○○○  8
Hygiene  ●●●●●●●●●●  100
Hugs     ●●○○○○○○○○  22
Social   ●●○○○○○○○○  22
```

Menu potrzeb: klik kuli (jako właściciel) → **Setup → Needs**.

Komunikaty skryptów idą tylko do Ciebie (`llOwnerSay`) albo prywatnym IM do klikającego — **nie** na local chat dla wszystkich.

### Opcjonalna regulacja (`needs.cfg`)

W kuli: **Content → New Note**. Nazwa **dokładnie** `needs.cfg` (małe litery).

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

Po zapisaniu notatki skrypt potrzeb wczyta ją sam.

---

## 2b. Tip jar (napiwki L$ → wibracje)

Osobne **naczynie na ziemi** — nie wkładaj skryptu do kuli. Pay na założonym obiekcie w SL często nie działa (lewy klik ginie, nie ma dialogu).

Kula Lovense musi być **założona i sparowana** w tym samym regionie. Naczynie samo ją znajdzie i wysyła komendę (`TJ|buzz` / `LVQ`) — nie potrzebuje osobnego PAIR URL.

Kula zostaje menu wibracji (lewy klik). Napiwki są tylko z naczynia.

### Mesh

`examples/secondlife/mesh/LovenseTipJar.dae` — szklana czara (Glass / Pink / Cyan / Core, te same face co orb).

1. Build → Upload → Model → `LovenseTipJar.dae`.
2. High LOD. Physics: **Analyze** → Convex Hull.
3. Nie włączaj „center mesh” — origin jest w stopie, żeby stało na ziemi.
4. Po uploade: rez na podłogę. Skaluj jak chcesz.

### Skopiuj skrypt

W programie: **Zdalne → Kopiuj skrypt tip jara**.

Skrypt **nie zmienia** kształtu, rozmiaru ani koloru mesha.

1. Naczynie → Content → New Script → wklej → Save (Running).
2. Weź **kopię** do ekwipunku, nazwij dokładnie `LovenseTipJar`. Włóż ją do **Glass** kuli.
3. Program → **Kopiuj host jara** → trzeci skrypt w Glass (obok kontrolera i wyglądu).
4. Klik kuli → **Rez jar** — naczynie pojawia się pod stopami. **Kill jar** je zabiera.
5. Lewy klik naczynia = **Pay** (L$10 / 50 / 100 / 250; inne kwoty też).
6. Menu naczynia: `/77 jar` (Close / Open / Test 50 / Reset $).
7. Hover: „waiting for orb” znika, gdy kula odpowie.

### Opcjonalna notatka `tipjar.cfg`

```
TITLE=Tip jar
THANKS=Thanks {name}! L${amount} -> {time}s
PRICE_A=10
PRICE_B=50
PRICE_C=100
PRICE_D=250
```

| Napiwek | Efekt |
|---------|--------|
| L$1+ | lekki tease, 4 s |
| L$10 | ~28%, 6 s |
| L$50 | ~58%, 12 s |
| L$100 | ~78%, 18 s |
| L$250 | preset pulse, 20 s |
| L$500 | fireworks, 28 s |

Owner: **Test 50** (bez L$), **Close** chowa Pay, **Reset $** zeruje sesję naczynia.
Kula → **Setup → Stats**: **Clear uses** (licznik wibracji), **Clear tips** (sesja L$), **Clear all**.

---

## 3. Jak to ma działać razem

```
Partner klika KULĘ      →  menu wibracji  →  program na PC  →  zabawka
Partner płaci NACZYNIE  →  kula w tym simie →  program na PC  →  zabawka
                              ↓
                    sygnał do skryptu potrzeb w kuli
                              ↓
                    hover nad głową (Horny ↑, Hygiene ↓)
```

| Potrzeba | Kiedy rośnie | Kiedy spada |
|----------|----------------|-------------|
| **Horny** | Ktoś włączy wibracje na kuli; dalej rośnie, póki zabawka chodzi | Powoli, gdy cisza |
| **Hygiene** | Wejście w wodę sima (ocean / staw Linden) — hover: `washing`. Albo sama, gdy dawno nie było wibracji | Powoli w trakcie i ~5 min po wibracjach |
| **Hugs** | Ktoś stoi bliżej niż **1,5 m** | Nikt nie stoi blisko |
| **Social** | Im więcej osób w **20 m**, tym szybciej | Nikogo w 20 m |

Hugs i Social **nie potrzebują** programu na PC — liczy je skrypt w kuli.

Horny i Hygiene **wymagają** kuli + połączonego programu (inaczej nie ma sygnału o wibracjach).

---

## 4. Po zmianie sima / teście

| Co | Czy ginie? |
|----|------------|
| Token, Lock, hover, licznik uses | Nie |
| Horny / Hygiene / Hugs / Social | Nie |
| PAIR URL kuli | **Tak** — grid daje nowy adres |

Po teście:

1. Klik kuli → **URL** (nowy adres nie wypisuje się sam).
2. Wklej go w programie → **Połącz**.
3. Kuli nie zdejmuj i nie resetuj skryptów.

Nie rób **Reset Scripts**, chyba że musisz. Stan i tak jest zapisany w obiekcie, ale PAIR URL i tak trzeba wkleić od nowa.

---

## 5. Typowe problemy

**Kuli nie widać / zostaje sześcianem**  
Skrypt nie zapisał się albo nie jest Running. Otwórz skrypt, Save, sprawdź błędy na dole okna. Cube → orb działa tylko na zwykłym primie (nie na mesh).

**Brak particle przy wibracjach**  
Program musi być połączony (PAIR URL) i zabawka musi faktycznie chodzić. Spray gęstnieje z siłą. STOP gasi od razu. Mesh też tryska.

**„BODY object, not HUD”**  
Kula siedzi na slocie HUD. Zdejmij i załóż na **Skull** albo **Chest**.

**Program: „Szukam obiektu” / URL wygasł**  
Nowy sim albo reset skryptu. Klik kuli → **URL**, wklej świeży PAIR URL. Wear sam linka nie wypisuje.

**Klik działa, Horny nie rośnie**  
W kuli muszą być **dwa** skrypty (kontroler + potrzeby), oba Running.

**Hugs nie rośnie przy przytulaniu**  
Druga osoba musi być w zasięgu ~1,5 m (w SL to prawie nachodzenie awatarów). W `needs.cfg` ustaw np. `HUG_RANGE=2.5`.

**Social zawsze 0**  
Kula musi być założona na awatarze (nie leżeć na ziemi). Sensor nie działa z inventory.

**Inni nie mogą kliknąć kuli**  
Masz **Lock** w Setup, albo kula jest na HUD zamiast na ciele.

**Po oddaniu obiektu komuś innemu**  
Zmiana właściciela czyści token i stan (tak ma być). Nowy owner wpisuje swój token.

---

## 6. Szybka checklista

- [ ] Program włączony, zabawka połączona
- [ ] Kula: skrypt wklejony, Running, **Wear na głowę/klatkę**
- [ ] PAIR URL wklejony w programie → Połącz
- [ ] Klik kuli rusza zabawką; MAX = gęsty spray z orba
- [ ] W tej samej kuli drugi skrypt (potrzeby), Running
- [ ] Nad głową widać 4 paski
- [ ] Test: ktoś klika MAX → Horny skacze, Hygiene zaczyna wolno spadać
- [ ] Test: ktoś staje obok → Social rośnie; przytula się → Hugs rośnie
- [ ] Tip jar: kopia `LovenseTipJar` w Glass, klik kuli → Rez jar, kula sparowana w simie
- [ ] Test: Pay L$10 / Test 50 → zabawka drży
