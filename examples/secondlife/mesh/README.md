# Mesh kontrolera (Second Life)

Plik: **`LovenseController.dae`**

Organiczny szklany orb jak stopione szkło: nachodzące przezroczyste pęcherze, masa magenta i cyan w środku. Bez metalu.

~35k trójkątów, 4 materiały (osobne face w SL):

| Face | Co pomalujesz | W SL dobrze wygląda jako |
|------|----------------|--------------------------|
| `Glass` | zewnętrzne membrany | jasny cyan/biel, **alpha ~35–50%**, shiny high, fullbright |
| `Pink` | masa magenta | róż, lekki alpha ~80% albo opaque, fullbright |
| `Cyan` | masa błękitna | cyan, tak samo |
| `Core` | małe serce | jaśniejszy róż, fullbright, glow |

Tekstury (1024×512, equirectangular, seamless):

| Plik | Face |
|------|------|
| `orb_glass.png` | Glass — iryzujący róż↔cyan |
| `orb_pink.png` | Pink |
| `orb_cyan.png` | Cyan |
| `orb_core.png` | Core |

W SL: Build → Upload → Image (L$10 / szt.) → Edit mesha → każdy face osobno. Glass: alpha ~40% + shiny. Pink/Cyan: fullbright. Regeneracja: `python3 examples/secondlife/mesh/make_orb_textures.py`.

Skrypt LSL **nie zmienia** mesha (kształt, tekstura, rozmiar). Particle i światło i tak idą z obiektu, gdy zabawka działa.

**Orbit:** wewnętrzne masy (Pink / Cyan / Core, albo child o nazwie `orb`) ślizgają się po powierzchni i pulsują. Działa tylko gdy orb jest **linksetem** (osobne primy), nie jednym meshem. Setup → Orbit on/off. Promień / rozmiar / tempo pulsu: listy na górze `LovenseLook.lsl`.

## Upload (linkset — żeby orbit działał)

**Wariant A — jeden DAE jako linkset (Firestorm)**

1. **Build → Upload → Model…** → `LovenseController.dae`.
2. Jeśli pyta: **upload as linkset / multiple meshes** — tak. Root = `Glass`.
3. High LOD. Physics: **Analyze** → Convex Hull.
4. Upload. Wear na Skull. Wklej skrypt do **roota (Glass)**.

**Wariant B — cztery osobne meshe**

Pliki: `LovenseOrb_Glass.dae`, `_Pink.dae`, `_Cyan.dae`, `_Core.dae`.

1. Upload każdego osobno (nie ruszaj origin / nie „center mesh”).
2. Rez wszystkie w tym samym miejscu. Zaznacz Pink+Cyan+Core, potem Glass, **Link**. Glass = parent.
3. Do **Glass (root)** dwa skrypty: kontroler + **LovenseLook**. Z Pink / Cyan / Core **usuń wszystkie skrypty**. Particle: wrzuć do Contents Glass tekstury `p_glow` / `p_star` / `p_spark` / `p_dot` / `p_flake` (losuje je).

Na `Glass` alpha ~40% + shiny, `Pink`/`Cyan` fullbright.

Podgląd: `LovenseController_preview.png`

Regeneracja:

```bash
python3 examples/secondlife/mesh/make_controller_dae.py
```

Róża (stary mesh): `LovenseRose.dae` — `python3 examples/secondlife/mesh/make_rose_dae.py`.

## Tip jar na ziemi

Plik: **`LovenseTipJar.dae`**

Szklana czara w tym samym języku co orb: przezroczyste membrany, nektar magenta/cyan w studni, perła. Origin w stopie — stoi na podłodze.

Te same 4 face (`Glass` / `Pink` / `Cyan` / `Core`). Tekstury orba (`orb_glass.png` itd.) można nałożyć 1:1.

Wklej `LovenseTipJar.lsl` do naczynia, weź **kopię** do Contents kuli (nazwa `LovenseTipJar`). Kula → **Rez jar** stawia je pod stopami. Lewy klik naczynia = Pay.

Upload jak orb (High LOD, Convex Hull). **Nie** „center mesh”.

Podgląd: `LovenseTipJar_preview.png`

```bash
python3 examples/secondlife/mesh/make_tipjar_dae.py
```
