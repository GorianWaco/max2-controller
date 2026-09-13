# Lovense sphere textures

Tekstury 1024×512 (equirectangular) na **kulę** w SL. Opcjonalne — bez nich skrypt i tak robi różowy orb z glow. Particle (spray gdy zabawka chodzi) nie potrzebują tych plików.

| Plik | Kiedy |
|------|--------|
| `lovense_offline.png` | brak pary / brak zabawki |
| `lovense_online.png` | połączone, cisza |
| `lovense_active.png` | wibruje |

## W SL

1. **Build → Upload → Image** (L$10 za każdą).
2. Wrzuć do **Contents** obiektu.
3. Nazwy dokładnie: `lovense_offline`, `lovense_online`, `lovense_active`.
4. Wklej nowy skrypt i zresetuj.

## Particle (Contents Glass)

Wrzucasz do **Contents roota (Glass)**. Nazwy zaczynają się od `p_`. Skrypt wyglądu losuje jedną przy sprayu i zmienia co ~2,5 s.

| Plik | Co |
|------|-----|
| `particles/p_glow.png` | miękka poświata |
| `particles/p_star.png` | gwiazdka |
| `particles/p_spark.png` | iskrą / krzyżyk |
| `particles/p_dot.png` | kropka z halo |
| `particles/p_flake.png` | płatek |

Białe + alpha — kolor daje skrypt (róż). Upload Image (L$10), wrzuć do Glass, **nie** do Pink/Cyan/Core. Bez `p_*` particle i tak lecą (domyślna kropka SL).

```bash
python3 examples/secondlife/textures/make_orbs.py
python3 examples/secondlife/textures/make_particles.py
```
