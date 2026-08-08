"""Główne okno GUI (CustomTkinter z fallbackiem do tkinter)."""

from __future__ import annotations

import logging
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from max2_controller.models import PRESETS
from max2_controller.web.servers import (
    create_game_app,
    create_remote_app,
    run_flask_in_thread,
    stop_server,
)

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller
    from max2_controller.hotkeys import HotkeyManager

logger = logging.getLogger(__name__)

try:
    import customtkinter as ctk

    HAS_CTK = True
except ImportError:
    HAS_CTK = False


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class MainWindow:
    def __init__(
        self,
        controller: "Max2Controller",
        config: "AppConfig",
        hotkeys: "HotkeyManager | None" = None,
    ) -> None:
        self.controller = controller
        self.config = config
        self.hotkeys = hotkeys
        self._game_handle = None
        self._remote_handle = None
        self._updating_sliders = False

        if HAS_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")
            self.root = ctk.CTk()
            self._use_ctk = True
        else:
            self.root = tk.Tk()
            self._use_ctk = False

        self.root.title("Max 2 Controller")
        self.root.geometry("720x780")
        self.root.minsize(640, 680)

        self._build()
        self.controller.on_log(self._on_log)
        self.controller.on_state(self._schedule_refresh_state)

        self.root.after(200, self._initial_load)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- widgets helpers ----
    def _frame(self, parent, **kw):
        if self._use_ctk:
            return ctk.CTkFrame(parent, **kw)
        return ttk.Frame(parent, **kw)

    def _label(self, parent, text="", **kw):
        if self._use_ctk:
            return ctk.CTkLabel(parent, text=text, **kw)
        return ttk.Label(parent, text=text, **kw)

    def _button(self, parent, text, command, **kw):
        if self._use_ctk:
            return ctk.CTkButton(parent, text=text, command=command, **kw)
        return ttk.Button(parent, text=text, command=command, **kw)

    def _entry(self, parent, textvariable=None, **kw):
        if self._use_ctk:
            return ctk.CTkEntry(parent, textvariable=textvariable, **kw)
        return ttk.Entry(parent, textvariable=textvariable, **kw)

    def _slider(self, parent, from_, to, command, **kw):
        if self._use_ctk:
            return ctk.CTkSlider(parent, from_=from_, to=to, number_of_steps=int(to - from_), command=command, **kw)
        s = ttk.Scale(parent, from_=from_, to=to, orient="horizontal", command=command)
        return s

    def _switch(self, parent, text, variable, command=None):
        if self._use_ctk:
            return ctk.CTkSwitch(parent, text=text, variable=variable, command=command)
        return ttk.Checkbutton(parent, text=text, variable=variable, command=command)

    def _textbox(self, parent, **kw):
        if self._use_ctk:
            return ctk.CTkTextbox(parent, **kw)
        return tk.Text(parent, **kw)

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        root = self.root

        # --- backend / połączenie ---
        conn = self._frame(root)
        conn.pack(fill="x", **pad)
        self._label(conn, text="Sposób połączenia (bez telefonu = Bluetooth BLE)").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        be_row = self._frame(conn)
        be_row.pack(fill="x", padx=8, pady=4)
        self.backend_var = tk.StringVar(
            value="Bluetooth BLE (PC)" if self.config.backend == "ble" else "Lovense Connect/Remote"
        )
        backend_values = ["Bluetooth BLE (PC)", "Lovense Connect/Remote"]
        if self._use_ctk:
            self.backend_menu = ctk.CTkOptionMenu(
                be_row, variable=self.backend_var, values=backend_values, command=self._on_backend
            )
            self.backend_menu.pack(side="left", fill="x", expand=True)
        else:
            self.backend_menu = ttk.Combobox(be_row, textvariable=self.backend_var, values=backend_values, state="readonly")
            self.backend_menu.pack(side="left", fill="x", expand=True)
            self.backend_menu.bind("<<ComboboxSelected>>", lambda e: self._on_backend(self.backend_var.get()))

        ble_row = self._frame(conn)
        ble_row.pack(fill="x", padx=8, pady=4)
        self._button(ble_row, text="Skanuj BLE", command=self._ble_scan, width=110 if self._use_ctk else None).pack(
            side="left", padx=(0, 6)
        )
        self._button(ble_row, text="Połącz BLE", command=self._ble_connect, width=110 if self._use_ctk else None).pack(
            side="left", padx=6
        )
        self._button(ble_row, text="Rozłącz", command=self._ble_disconnect, width=90 if self._use_ctk else None).pack(
            side="left", padx=6
        )

        self._label(conn, text="URL (tylko tryb Connect/Remote):").pack(anchor="w", padx=8, pady=(6, 0))
        url_row = self._frame(conn)
        url_row.pack(fill="x", padx=8, pady=4)
        self.url_var = tk.StringVar(value=self.config.lovense_url)
        self._entry(url_row, textvariable=self.url_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(url_row, text="Zapisz URL", command=self._save_url, width=100 if self._use_ctk else None).pack(
            side="right"
        )

        hints = (
            "BLE: włącz Max 2 blisko PC, Skanuj → Połącz. "
            "Telefon NIE jest potrzebny. Wyłącz inne apki BLE (Remote/Intiface)."
        )
        self._label(conn, text=hints).pack(anchor="w", padx=8, pady=(0, 8))

        # --- zabawki ---
        toys_f = self._frame(root)
        toys_f.pack(fill="x", **pad)
        row = self._frame(toys_f)
        row.pack(fill="x", padx=8, pady=8)
        self._label(row, text="Zabawka:").pack(side="left")
        self.toy_var = tk.StringVar()
        if self._use_ctk:
            self.toy_menu = ctk.CTkOptionMenu(row, variable=self.toy_var, values=["—"], command=self._on_toy_pick)
            self.toy_menu.pack(side="left", fill="x", expand=True, padx=8)
        else:
            self.toy_menu = ttk.Combobox(row, textvariable=self.toy_var, state="readonly")
            self.toy_menu.pack(side="left", fill="x", expand=True, padx=8)
            self.toy_menu.bind("<<ComboboxSelected>>", lambda e: self._on_toy_pick(self.toy_var.get()))
        self._button(row, text="Odśwież", command=self._refresh_toys, width=90 if self._use_ctk else None).pack(
            side="right"
        )
        self.battery_var = tk.StringVar(value="Bateria: —")
        self.status_var = tk.StringVar(value="Status: niepołączony")
        self._label(toys_f, textvariable=self.status_var).pack(anchor="w", padx=8)
        self._label(toys_f, textvariable=self.battery_var).pack(anchor="w", padx=8, pady=(0, 8))

        # --- suwaki ---
        ctrl = self._frame(root)
        ctrl.pack(fill="x", **pad)
        self.vibrate_label = tk.StringVar(value="Vibrate: 0 / 20")
        self._label(ctrl, textvariable=self.vibrate_label).pack(anchor="w", padx=8, pady=(8, 0))
        self.vibrate_slider = self._slider(ctrl, 0, 20, self._on_vibrate)
        self.vibrate_slider.pack(fill="x", padx=8, pady=4)
        if self._use_ctk:
            self.vibrate_slider.set(0)

        self.pump_label = tk.StringVar(value="Pump: 0 / 3")
        self._label(ctrl, textvariable=self.pump_label).pack(anchor="w", padx=8, pady=(8, 0))
        self.pump_slider = self._slider(ctrl, 0, 3, self._on_pump)
        self.pump_slider.pack(fill="x", padx=8, pady=4)
        if self._use_ctk:
            self.pump_slider.set(0)

        self.time_label = tk.StringVar(value="Czas: 0 s (0 = ciągły)")
        self._label(ctrl, textvariable=self.time_label).pack(anchor="w", padx=8, pady=(8, 0))
        self.time_slider = self._slider(ctrl, 0, 60, self._on_time)
        self.time_slider.pack(fill="x", padx=8, pady=4)
        if self._use_ctk:
            self.time_slider.set(0)

        btn_row = self._frame(ctrl)
        btn_row.pack(fill="x", padx=8, pady=10)
        self._button(btn_row, text="Zastosuj", command=self._apply).pack(side="left", padx=(0, 6))
        stop_kw = {"fg_color": "#b91c1c", "hover_color": "#7f1d1d"} if self._use_ctk else {}
        self._button(btn_row, text="STOP", command=self._stop, **stop_kw).pack(side="left", padx=6)
        self._button(btn_row, text="Bateria", command=self._battery).pack(side="left", padx=6)

        # --- presety ---
        pre = self._frame(root)
        pre.pack(fill="x", **pad)
        self._label(pre, text="Presety").pack(anchor="w", padx=8, pady=(8, 4))
        prow = self._frame(pre)
        prow.pack(fill="x", padx=8, pady=(0, 8))
        for name in PRESETS:
            self._button(prow, text=name.capitalize(), command=lambda n=name: self._preset(n), width=100 if self._use_ctk else None).pack(
                side="left", padx=4
            )

        # --- pattern ---
        pat = self._frame(root)
        pat.pack(fill="x", **pad)
        self._label(pat, text="Własny wzorzec (wartości 0–20 oddzielone ; max 50)").pack(anchor="w", padx=8, pady=(8, 0))
        self.pattern_var = tk.StringVar(value="20;5;15;0;20;10")
        self._entry(pat, textvariable=self.pattern_var).pack(fill="x", padx=8, pady=4)
        prow2 = self._frame(pat)
        prow2.pack(fill="x", padx=8, pady=(0, 8))
        self._label(prow2, text="Interwał ms:").pack(side="left")
        self.interval_var = tk.StringVar(value="200")
        self._entry(prow2, textvariable=self.interval_var, width=80 if self._use_ctk else 8).pack(side="left", padx=6)
        self._button(prow2, text="Odtwórz pattern", command=self._pattern).pack(side="left", padx=6)

        # --- API / remote ---
        net = self._frame(root)
        net.pack(fill="x", **pad)
        self._label(net, text="Integracje").pack(anchor="w", padx=8, pady=(8, 4))

        self.game_api_var = tk.BooleanVar(value=self.config.game_api_enabled)
        self._switch(net, "API do gier (localhost)", self.game_api_var, command=self._toggle_game_api).pack(
            anchor="w", padx=8
        )
        self.game_info_var = tk.StringVar(value="")
        self._label(net, textvariable=self.game_info_var).pack(anchor="w", padx=8)

        self.remote_var = tk.BooleanVar(value=False)
        self._switch(net, "Zdalne sterowanie (dla innych osób)", self.remote_var, command=self._toggle_remote).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        self.remote_info_var = tk.StringVar(value="Wyłączone")
        self._label(net, textvariable=self.remote_info_var).pack(anchor="w", padx=8)
        tok_row = self._frame(net)
        tok_row.pack(fill="x", padx=8, pady=(4, 8))
        self._button(tok_row, text="Nowy token remote", command=self._regen_remote_token, width=140 if self._use_ctk else None).pack(
            side="left"
        )
        self._button(tok_row, text="Kopiuj link", command=self._copy_remote_link, width=100 if self._use_ctk else None).pack(
            side="left", padx=6
        )

        # --- log ---
        logf = self._frame(root)
        logf.pack(fill="both", expand=True, **pad)
        self._label(logf, text="Log").pack(anchor="w", padx=8, pady=(8, 0))
        self.log_box = self._textbox(logf, height=120 if self._use_ctk else 8)
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)
        if not self._use_ctk:
            self.log_box.configure(state="disabled", height=8)

        hk = (
            "Hotkeys: Ctrl+Shift+S STOP · ↑↓ wibracje · ←→ pump · 1 pulse · 2 wave"
            if self.config.hotkeys_enabled
            else "Hotkeys wyłączone"
        )
        self._label(root, text=hk).pack(anchor="w", padx=14, pady=(0, 10))

    # ---- actions ----
    def _initial_load(self) -> None:
        self._refresh_toys()
        self.controller.start_battery_poll()
        if self.config.game_api_enabled:
            self.game_api_var.set(True)
            self._start_game_api()

    def _save_url(self) -> None:
        url = self.url_var.get().strip()
        threading.Thread(target=lambda: self.controller.update_lovense_url(url), daemon=True).start()

    def _on_backend(self, label: str) -> None:
        name = "ble" if "BLE" in label or "Bluetooth" in label else "lovense_local"
        def work():
            self.controller.set_backend(name)
            self.root.after(0, self._sync_toy_menu)
        threading.Thread(target=work, daemon=True).start()

    def _ble_scan(self) -> None:
        self.controller.log("Skanowanie Bluetooth… (kilka sekund)")
        def work():
            self.controller.ble_scan(timeout=8.0)
            self.root.after(0, self._sync_toy_menu)
        threading.Thread(target=work, daemon=True).start()

    def _ble_connect(self) -> None:
        def work():
            self.controller.ble_connect()
            self.root.after(0, self._sync_toy_menu)
        threading.Thread(target=work, daemon=True).start()

    def _ble_disconnect(self) -> None:
        def work():
            self.controller.ble_disconnect()
            self.root.after(0, self._sync_toy_menu)
        threading.Thread(target=work, daemon=True).start()

    def _refresh_toys(self) -> None:
        def work():
            self.controller.refresh_toys()
            self.root.after(0, self._sync_toy_menu)

        threading.Thread(target=work, daemon=True).start()

    def _sync_toy_menu(self) -> None:
        toys = self.controller.state.toys
        labels = [t.display_name for t in toys] or ["— brak —"]
        self._toy_map = {t.display_name: t.id for t in toys}
        if self._use_ctk:
            self.toy_menu.configure(values=labels)
            if toys:
                sel = self.controller.selected_toy()
                self.toy_var.set(sel.display_name if sel else labels[0])
            else:
                self.toy_var.set(labels[0])
        else:
            self.toy_menu["values"] = labels
            if toys:
                sel = self.controller.selected_toy()
                self.toy_var.set(sel.display_name if sel else labels[0])
            else:
                self.toy_var.set(labels[0])
        self._refresh_state_labels()

    def _on_toy_pick(self, label: str) -> None:
        tid = getattr(self, "_toy_map", {}).get(label)
        self.controller.select_toy(tid)

    def _slider_val(self, slider) -> float:
        if self._use_ctk:
            return float(slider.get())
        return float(slider.get())

    def _on_vibrate(self, value) -> None:
        if self._updating_sliders:
            return
        v = int(round(float(value)))
        self.vibrate_label.set(f"Vibrate: {v} / 20")
        self.controller.set_levels(vibrate=v, immediate=False)

    def _on_pump(self, value) -> None:
        if self._updating_sliders:
            return
        p = int(round(float(value)))
        self.pump_label.set(f"Pump: {p} / 3")
        self.controller.set_levels(pump=p, immediate=False)

    def _on_time(self, value) -> None:
        t = int(round(float(value)))
        self.time_label.set(f"Czas: {t} s (0 = ciągły)")
        self.controller.state.time_sec = float(t)

    def _apply(self) -> None:
        threading.Thread(target=self.controller.apply_now, daemon=True).start()

    def _stop(self) -> None:
        def work():
            self.controller.stop()
            self.root.after(0, self._zero_sliders)

        threading.Thread(target=work, daemon=True).start()

    def _zero_sliders(self) -> None:
        self._updating_sliders = True
        try:
            if self._use_ctk:
                self.vibrate_slider.set(0)
                self.pump_slider.set(0)
            else:
                self.vibrate_slider.set(0)
                self.pump_slider.set(0)
            self.vibrate_label.set("Vibrate: 0 / 20")
            self.pump_label.set("Pump: 0 / 3")
        finally:
            self._updating_sliders = False

    def _battery(self) -> None:
        threading.Thread(target=self.controller.refresh_battery, daemon=True).start()

    def _preset(self, name: str) -> None:
        threading.Thread(target=lambda: self.controller.preset(name), daemon=True).start()

    def _pattern(self) -> None:
        strength = self.pattern_var.get().strip()
        try:
            interval = int(self.interval_var.get().strip() or "200")
        except ValueError:
            messagebox.showerror("Pattern", "Interwał musi być liczbą (ms)")
            return
        threading.Thread(
            target=lambda: self.controller.pattern(strength, interval_ms=interval),
            daemon=True,
        ).start()

    # ---- network ----
    def _start_game_api(self) -> None:
        if self._game_handle and self._game_handle.running:
            return
        app = create_game_app(self.controller, self.config)
        self._game_handle = run_flask_in_thread(
            app, self.config.game_api_host, self.config.game_api_port, "game-api"
        )
        self.controller.state.game_api_active = True
        self.config.game_api_enabled = True
        self.config.save()
        self.game_info_var.set(
            f"http://{self.config.game_api_host}:{self.config.game_api_port}  "
            f"token: {self.config.game_api_token}"
        )
        self.controller.log(f"Game API: {self.game_info_var.get()}")

    def _stop_game_api(self) -> None:
        stop_server(self._game_handle)
        self._game_handle = None
        self.controller.state.game_api_active = False
        self.config.game_api_enabled = False
        self.config.save()
        self.game_info_var.set("Wyłączone")

    def _toggle_game_api(self) -> None:
        if self.game_api_var.get():
            self._start_game_api()
        else:
            self._stop_game_api()

    def _start_remote(self) -> None:
        if self._remote_handle and self._remote_handle.running:
            return
        self.config.remote_enabled = True
        self.config.save()
        app = create_remote_app(self.controller, self.config)
        self._remote_handle = run_flask_in_thread(
            app, self.config.remote_host, self.config.remote_port, "remote"
        )
        self.controller.state.remote_active = True
        ip = _local_ip()
        link = f"http://{ip}:{self.config.remote_port}/panel?token={self.config.remote_token}"
        self.remote_info_var.set(
            f"LAN: {link}\n"
            f"Token: {self.config.remote_token}\n"
            f"Na internet: cloudflared tunnel / ngrok / tailscale → port {self.config.remote_port}"
        )
        self.controller.log("Zdalne sterowanie WŁĄCZONE — udostępniaj link tylko zaufanym osobom")

    def _stop_remote(self) -> None:
        stop_server(self._remote_handle)
        self._remote_handle = None
        self.controller.state.remote_active = False
        self.config.remote_enabled = False
        self.config.save()
        self.remote_info_var.set("Wyłączone")
        self.controller.log("Zdalne sterowanie wyłączone")

    def _toggle_remote(self) -> None:
        if self.remote_var.get():
            if not messagebox.askyesno(
                "Zdalne sterowanie",
                "Włączasz panel web, z którego inni mogą sterować zabawką.\n\n"
                "W sieci LAN link zadziała od razu.\n"
                "Przez internet użyj tunnel (cloudflared/ngrok) lub VPN (Tailscale).\n\n"
                "Kontynuować?",
            ):
                self.remote_var.set(False)
                return
            self._start_remote()
        else:
            self._stop_remote()

    def _regen_remote_token(self) -> None:
        import secrets

        self.config.remote_token = secrets.token_urlsafe(24)
        self.config.save()
        if self.remote_var.get():
            self._stop_remote()
            self._start_remote()
        # odśwież wyświetlany link z nowym tokenem
        try:
            ip = _local_ip()
            link = f"http://{ip}:{self.config.remote_port}/panel?token={self.config.remote_token}"
            if hasattr(self, "remote_link_var"):
                self.remote_link_var.set(link)
            elif hasattr(self, "remote_info"):
                pass
        except Exception:
            link = self.config.remote_token
        self.controller.log("Wygenerowano nowy token remote — zaktualizuj link panelu u partnerki")
        messagebox.showinfo(
            "Token",
            f"Nowy token:\n{self.config.remote_token}\n\n"
            f"Skopiuj świeży link (stary /r/… lub ?token= przestaje działać).",
        )

    def _copy_remote_link(self) -> None:
        ip = _local_ip()
        link = f"http://{ip}:{self.config.remote_port}/panel?token={self.config.remote_token}"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            self.controller.log(f"Skopiowano link: {link}")
        except Exception as e:
            messagebox.showinfo("Link", link)
            self.controller.log(str(e))

    # ---- ui updates ----
    def _on_log(self, msg: str) -> None:
        def append():
            if self._use_ctk:
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
            else:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")

        try:
            self.root.after(0, append)
        except Exception:
            pass

    def _schedule_refresh_state(self) -> None:
        try:
            self.root.after(0, self._refresh_state_labels)
        except Exception:
            pass

    def _refresh_state_labels(self) -> None:
        st = self.controller.state
        self.status_var.set(
            "Status: połączony z Lovense" if st.connected else "Status: brak połączenia z Lovense Connect/Remote"
        )
        toy = self.controller.selected_toy()
        if toy and toy.battery is not None:
            self.battery_var.set(f"Bateria: {toy.battery}%")
        elif toy:
            self.battery_var.set("Bateria: ? (kliknij Bateria)")
        else:
            self.battery_var.set("Bateria: —")

        # synchronizuj suwaki gdy stop z hotkey / API
        self._updating_sliders = True
        try:
            if self._use_ctk:
                if int(round(self.vibrate_slider.get())) != st.vibrate:
                    self.vibrate_slider.set(st.vibrate)
                if int(round(self.pump_slider.get())) != st.pump:
                    self.pump_slider.set(st.pump)
            else:
                if int(round(float(self.vibrate_slider.get()))) != st.vibrate:
                    self.vibrate_slider.set(st.vibrate)
                if int(round(float(self.pump_slider.get()))) != st.pump:
                    self.pump_slider.set(st.pump)
            self.vibrate_label.set(f"Vibrate: {st.vibrate} / 20")
            self.pump_label.set(f"Pump: {st.pump} / 3")
        finally:
            self._updating_sliders = False

    def _on_close(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
        self._stop_game_api()
        self._stop_remote()
        try:
            self.controller.shutdown()
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
