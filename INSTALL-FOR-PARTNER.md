# Lovense Controller — instalacja (dla Ciebie / partnerki)

Program steruje **zabawkami Lovense** z komputera (Linux): Lush, Hush, Max 2, Nora, Edge, Domi i inne.

Nie wymaga telefonu (Bluetooth bezpośrednio z PC).

---

## Jedna komenda

```bash
curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash
```

To doinstaluje GTK/BLE i wrzuci skrót do menu.

### Flatpak (łatwiej wysłać gotową paczkę)

```bash
curl -fsSL https://raw.githubusercontent.com/GorianWaco/max2-controller/main/install.sh | bash -s -- --flatpak
```

Albo z GitHub Releases: pobierz `LovenseController-*.flatpak` i:

```bash
flatpak install --user LovenseController-2.0.0.flatpak
flatpak run pl.gorian.LovenseController
```

**Uwagi Flatpak + Bluetooth:** jeśli skan BLE nic nie znajdzie:

```bash
bluetoothctl show
flatpak override --user --device=all pl.gorian.LovenseController
```

---

## Z katalogu źródłowego

```bash
./install.sh                 # native + zależności
./install.sh --flatpak       # z dist/ albo z GitHuba
./build-flatpak.sh           # buduje dist/LovenseController-*.flatpak
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
