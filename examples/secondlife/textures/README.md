# Lovense HUD status textures

Ready-to-upload PNGs (512×256) for the Second Life HUD face.  
The LSL script swaps them when status changes: **offline / online / busy / error**.

| File | When shown |
|------|------------|
| `hud_offline.png` | PC/toy offline or not connected |
| `hud_online.png` | Connected, idle |
| `hud_busy.png` | HTTP request in progress |
| `hud_error.png` | Bad token, remote off, HTTP error |

## Upload to Second Life

1. In SL: **Build → Upload → Image (L$10 each)** — upload all four PNGs.
2. After each upload, open the texture → copy **UUID** (Asset UUID).
3. Either:
   - **A)** Paste UUIDs into the script:

     ```lsl
     key TEX_OFFLINE = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx";
     key TEX_ONLINE  = "…";
     key TEX_BUSY    = "…";
     key TEX_ERROR   = "…";
     ```

   - **B)** Put the four **texture items** into the HUD object **Contents**  
     and name them exactly: `hud_offline`, `hud_online`, `hud_busy`, `hud_error`  
     (script resolves them via inventory — no UUID edit needed).

4. **Reset** the script.

Without textures, the HUD still works with solid color + glow fallback.

## Regenerate

```bash
# from repo (requires Pillow)
python3 -c "print('see agent script or re-run generation')"
```

Source generator can be re-run from the project tooling; files live next to this README.
