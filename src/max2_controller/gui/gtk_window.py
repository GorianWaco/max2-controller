"""Główne okno — GTK 4 (PyGObject), bez Tk."""

from __future__ import annotations

import logging
import socket
import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from max2_controller.audio_react import (
    AudioReactor,
    default_sink_name,
    default_source_name,
    list_input_sources,
    list_playback_sinks,
)
from max2_controller.hotkey_defs import (
    GROUP_LABELS,
    HOTKEY_ACTIONS,
    format_chord_display,
    format_game_display,
)
from max2_controller.hotkeys import gtk_key_to_chord, gtk_key_to_game
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

# Adwaita opcjonalne — bez libadwaita ruszy czysty Gtk.Application
try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    HAS_ADW = True
except Exception:
    Adw = None  # type: ignore
    HAS_ADW = False


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


_AppBase = Adw.Application if HAS_ADW else Gtk.Application


class Max2GtkApp(_AppBase):
    APP_ID = "pl.gorian.LovenseController"
    ICON_NAME = "pl.gorian.LovenseController"

    def __init__(
        self,
        controller: "Max2Controller",
        config: "AppConfig",
        hotkeys: "HotkeyManager | None" = None,
    ) -> None:
        # application_id = desktop/icon id (GNOME / dock)
        super().__init__(application_id=self.APP_ID)
        self.controller = controller
        self.config = config
        self.hotkeys = hotkeys
        self.audio = AudioReactor(controller, config)
        self.controller.audio_reactor = self.audio
        self.controller.on_audio_toggle(self._toggle_audio_from_hotkey)
        self._game_handle = None
        self._remote_handle = None
        self._updating_sliders = False
        self._remote_sw_guard = False  # blokada reentrancy przy błędzie startu
        self._toy_map: dict[str, str] = {}
        self.win: Gtk.ApplicationWindow | None = None
        self._audio_level_idle = False
        self._internet_tunnel = None  # max2_controller.internet_share.InternetTunnel

    # Kategorie lewego paska: (id, etykieta)
    _NAV_PAGES: tuple[tuple[str, str], ...] = (
        ("polaczenie", "Łączenie"),
        ("sterowanie", "Sterowanie"),
        ("wzorce", "Wzorce i presety"),
        ("audio", "Audio"),
        ("skroty", "Skróty klawiszowe"),
        ("zdalne", "Zdalne sterowanie"),
        ("sesje", "Połączenia remote"),
        ("log", "Log"),
    )

    def do_activate(self) -> None:  # noqa: N802 — GTK signal
        if self.win is not None:
            self.win.present()
            return
        self.win = Gtk.ApplicationWindow(application=self, title="Lovense Controller")
        self.win.set_default_size(920, 720)
        self.win.connect("close-request", self._on_close)
        # ikona w docku / Alt-Tab (nazwa z hicolor + plik z install-local.sh)
        try:
            self.win.set_icon_name(self.ICON_NAME)
        except Exception:
            pass

        # shell: lewy pasek + treść + pasek STOP na dole
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.win.set_child(shell)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_hexpand(True)
        body.set_vexpand(True)
        shell.append(body)

        # --- lewy pasek kategorii ---
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        side.set_margin_top(10)
        side.set_margin_bottom(10)
        side.set_margin_start(8)
        side.set_margin_end(8)
        side.set_size_request(188, -1)
        side.add_css_class("sidebar")
        body.append(side)

        brand = Gtk.Label(label="Lovense\nController")
        brand.set_justify(Gtk.Justification.CENTER)
        brand.add_css_class("title-4")
        brand.set_margin_bottom(8)
        side.append(brand)

        self._nav_list = Gtk.ListBox()
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.add_css_class("navigation-sidebar")
        self._nav_list.set_vexpand(True)
        for page_id, label in self._NAV_PAGES:
            row = Gtk.ListBoxRow()
            # set_name bywa kolizyjne z CSS — trzymamy id w atrybucie
            row.page_id = page_id  # type: ignore[attr-defined]
            lab = Gtk.Label(label=label, xalign=0)
            lab.set_wrap(True)
            lab.set_margin_top(10)
            lab.set_margin_bottom(10)
            lab.set_margin_start(12)
            lab.set_margin_end(12)
            row.set_child(lab)
            self._nav_list.append(row)
        side.append(self._nav_list)

        # --- prawa strona: stack stron ---
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)
        body.append(self._stack)

        pages: dict[str, Gtk.Box] = {}
        for page_id, title in self._NAV_PAGES:
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            page.set_margin_top(12)
            page.set_margin_bottom(12)
            page.set_margin_start(14)
            page.set_margin_end(14)
            scroll.set_child(page)
            self._stack.add_named(scroll, page_id)
            pages[page_id] = page

        self._nav_list.connect("row-selected", self._on_nav_selected)
        self._nav_list.select_row(self._nav_list.get_row_at_index(0))

        # --- dolny pasek: STOP zawsze widoczny ---
        dock = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        dock.set_margin_top(6)
        dock.set_margin_bottom(10)
        dock.set_margin_start(14)
        dock.set_margin_end(14)
        self._dock_status = Gtk.Label(label="—", xalign=0, hexpand=True)
        self._dock_status.add_css_class("dim-label")
        dock.append(self._dock_status)
        dock_stop = Gtk.Button(label="STOP")
        dock_stop.add_css_class("destructive-action")
        dock_stop.set_size_request(120, -1)
        dock_stop.connect("clicked", lambda *_: self._stop())
        dock.append(dock_stop)
        shell.append(dock)

        self._build(pages)
        self.controller.on_log(self._on_log)
        self.controller.on_state(self._schedule_refresh_state)
        GLib.timeout_add(250, self._initial_load)
        self.win.present()

    def _on_nav_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        page_id = getattr(row, "page_id", None) or row.get_name()
        if page_id and self._stack.get_child_by_name(page_id):
            self._stack.set_visible_child_name(page_id)

    def _section(self, parent: Gtk.Box, title: str) -> Gtk.Box:
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        frame.set_child(box)
        parent.append(frame)
        return box

    def _build(self, pages: dict[str, Gtk.Box]) -> None:
        # Backend
        sec = self._section(pages["polaczenie"], "Bluetooth (bez telefonu)")
        self.backend_dd = Gtk.DropDown.new_from_strings(
            ["Bluetooth BLE (PC)", "Lovense Connect/Remote"]
        )
        if self.config.backend != "ble":
            self.backend_dd.set_selected(1)
        self.backend_dd.connect("notify::selected", self._on_backend)
        sec.append(self.backend_dd)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, cb in (
            ("Skanuj BLE", self._ble_scan),
            ("Połącz (dodaj)", self._ble_connect),
            ("Rozłącz wybraną", self._ble_disconnect_one),
            ("Rozłącz wszystkie", self._ble_disconnect_all),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, c=cb: c())
            row.append(b)
        sec.append(row)

        all_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        all_row.append(
            Gtk.Label(label="Steruj wszystkimi połączonymi naraz", hexpand=True, xalign=0)
        )
        self.control_all_sw = Gtk.Switch()
        self.control_all_sw.set_active(True)
        self.control_all_sw.connect("notify::active", self._on_control_all)
        all_row.append(self.control_all_sw)
        sec.append(all_row)

        hint = Gtk.Label(
            label="Dwie zabawki naraz: Skanuj → wybierz 1. → Połącz (dodaj) → wybierz 2. → Połącz. "
            "„Steruj wszystkimi” = te same poziomy na obie. Zamknij Lovense na telefonach.",
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("dim-label")
        sec.append(hint)

        self.url_entry = Gtk.Entry()
        self.url_entry.set_text(self.config.lovense_url)
        self.url_entry.set_placeholder_text("URL tylko dla trybu Connect/Remote")
        url_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        url_row.append(self.url_entry)
        save_url = Gtk.Button(label="Zapisz URL")
        save_url.connect("clicked", lambda *_: self._save_url())
        url_row.append(save_url)
        sec.append(url_row)

        # Zabawki — skan + lista połączonych (ListBox + przycisk Połącz przy każdym)
        sec = self._section(pages["polaczenie"], "Zabawki (Lush 3 · Nora · Max 2 · Gemini…)")
        self.status_lbl = Gtk.Label(label="Status: —", xalign=0)
        self.status_lbl.set_wrap(True)
        sec.append(self.status_lbl)
        self.scan_status_lbl = Gtk.Label(label="", xalign=0)
        self.scan_status_lbl.add_css_class("dim-label")
        sec.append(self.scan_status_lbl)

        sec.append(Gtk.Label(label="Znalezione (kliknij Połącz przy urządzeniu):", xalign=0))
        self.scan_list = Gtk.ListBox()
        self.scan_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scan_scroll = Gtk.ScrolledWindow()
        scan_scroll.set_min_content_height(220)
        scan_scroll.set_max_content_height(360)
        scan_scroll.set_vexpand(True)
        scan_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scan_scroll.set_child(self.scan_list)
        sec.append(scan_scroll)
        self.scan_empty_lbl = Gtk.Label(
            label="Kliknij „Skanuj BLE” — pokażą się Lush / Nora / Max / Gemini w pobliżu.",
            wrap=True,
            xalign=0,
        )
        self.scan_empty_lbl.add_css_class("dim-label")
        sec.append(self.scan_empty_lbl)

        # zachowane pod kompatybilność API (nieużywane w UI)
        self.toy_dd = None
        self._toy_map = {}
        self._scan_busy = False

        sec.append(Gtk.Label(label="Połączone teraz:", xalign=0))
        self.connected_list = Gtk.ListBox()
        self.connected_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.connected_list.connect("row-selected", self._on_connected_row)
        conn_scroll = Gtk.ScrolledWindow()
        conn_scroll.set_min_content_height(180)
        conn_scroll.set_max_content_height(300)
        conn_scroll.set_vexpand(True)
        conn_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        conn_scroll.set_child(self.connected_list)
        sec.append(conn_scroll)
        self.connected_empty_lbl = Gtk.Label(
            label="(brak — po połączeniu zobaczysz listę, można dodać 2+)",
            xalign=0,
        )
        self.connected_empty_lbl.add_css_class("dim-label")
        sec.append(self.connected_empty_lbl)

        self.battery_lbl = Gtk.Label(label="Bateria: —", xalign=0)
        sec.append(self.battery_lbl)

        # Suwaki
        sec = self._section(pages["sterowanie"], "Sterowanie")
        self.vib_lbl = Gtk.Label(label="Vibrate: 0 / 20", xalign=0)
        self.vib_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 20, 1)
        self.vib_scale.set_draw_value(False)
        self.vib_scale.set_hexpand(True)
        self.vib_scale.connect("value-changed", self._on_vibrate)
        sec.append(self.vib_lbl)
        sec.append(self.vib_scale)

        self.pump_lbl = Gtk.Label(label="Druga funkcja: 0 (po połączeniu: Pump/Rotate/…)", xalign=0)
        self.pump_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 3, 1)
        self.pump_scale.set_draw_value(False)
        self.pump_scale.set_hexpand(True)
        self.pump_scale.connect("value-changed", self._on_pump)
        sec.append(self.pump_lbl)
        sec.append(self.pump_scale)
        self.model_lbl = Gtk.Label(label="Model: — (działa z większością Lovense)", xalign=0)
        sec.append(self.model_lbl)

        # Szybkie poziomy %
        qrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        qrow.append(Gtk.Label(label="Szybko:"))
        for pct in (0, 25, 50, 75, 100):
            lab = "STOP" if pct == 0 else f"{pct}%"
            b = Gtk.Button(label=lab)
            if pct == 0:
                b.add_css_class("destructive-action")
            b.connect("clicked", lambda _w, p=pct: self._quick_percent(p))
            qrow.append(b)
        sec.append(qrow)

        # Limit siły
        lim_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.max_vib_lbl = Gtk.Label(
            label=f"Limit max wibracji: {self.config.control_max_vibrate}", xalign=0, hexpand=True
        )
        lim_row.append(self.max_vib_lbl)
        self.max_vib_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 20, 1)
        self.max_vib_scale.set_value(self.config.control_max_vibrate)
        self.max_vib_scale.set_draw_value(True)
        self.max_vib_scale.set_size_request(160, -1)
        self.max_vib_scale.connect("value-changed", self._on_max_vibrate)
        lim_row.append(self.max_vib_scale)
        sec.append(lim_row)

        self.time_lbl = Gtk.Label(label="Czas: 0 s (0 = ciągły)", xalign=0)
        self.time_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 60, 1)
        self.time_scale.set_draw_value(False)
        self.time_scale.set_hexpand(True)
        self.time_scale.connect("value-changed", self._on_time)
        sec.append(self.time_lbl)
        sec.append(self.time_scale)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_b = Gtk.Button(label="Zastosuj")
        apply_b.connect("clicked", lambda *_: self._apply())
        stop_b = Gtk.Button(label="STOP")
        stop_b.add_css_class("destructive-action")
        stop_b.connect("clicked", lambda *_: self._stop())
        bat_b = Gtk.Button(label="Bateria")
        bat_b.connect("clicked", lambda *_: self._battery())
        boost_b = Gtk.Button(label="Boost")
        boost_b.connect("clicked", lambda *_: self._boost())
        btn_row.append(apply_b)
        btn_row.append(stop_b)
        btn_row.append(bat_b)
        btn_row.append(boost_b)
        sec.append(btn_row)

        # Tryby automatyczne
        sec = self._section(pages["sterowanie"], "Tryby automatyczne")
        self.auto_mode_lbl = Gtk.Label(label="Tryb: wyłączony", xalign=0)
        sec.append(self.auto_mode_lbl)
        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, cb in (
            ("Oscylacja", lambda: self.controller.toggle_mode("oscillate")),
            ("Losowy", lambda: self.controller.toggle_mode("random")),
            ("Ramp ↑", lambda: self.controller.start_ramp(up=True)),
            ("Ramp ↓", lambda: self.controller.start_ramp(up=False)),
            ("Stop trybu", self.controller.stop_auto_modes),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, c=cb: self._bg(c))
            mrow.append(b)
        sec.append(mrow)
        mode_hint = Gtk.Label(
            label=(
                f"Oscylacja: {self.config.control_oscillate_min}–{self.config.control_oscillate_max} "
                f"co {self.config.control_oscillate_interval_ms} ms · "
                f"Losowy: {self.config.control_random_min}–{self.config.control_random_max} · "
                f"Ramp: {self.config.control_ramp_seconds:.0f} s "
                "(zakresy w config.json / skróty)."
            ),
            wrap=True,
            xalign=0,
        )
        mode_hint.add_css_class("dim-label")
        sec.append(mode_hint)

        # Presety (wiele rzędów)
        sec = self._section(pages["wzorce"], "Presety (krótkie + długie)")
        from max2_controller.models import PRESET_DEFAULT_SEC, PRESET_LABELS_PL

        row_box: Gtk.Box | None = None
        for i, name in enumerate(PRESETS):
            if i % 4 == 0:
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                sec.append(row_box)
            sec_def = int(PRESET_DEFAULT_SEC.get(name, 10))
            lab = PRESET_LABELS_PL.get(name, name)
            short = lab if len(lab) <= 14 else name
            b = Gtk.Button(label=f"{short}")
            b.set_tooltip_text(f"{name} · domyślnie ~{sec_def}s")
            b.connect("clicked", lambda _w, n=name: self._preset(n))
            if row_box is not None:
                row_box.append(b)
        long_hint = Gtk.Label(
            label="Długie: slowburn, marathon, teaselong, edgelong, waveslow, deepwave, crescendo, afterglow "
            "(domyślnie 35–60 s — lub ustaw suwak Czas).",
            wrap=True,
            xalign=0,
        )
        long_hint.add_css_class("dim-label")
        sec.append(long_hint)

        # Pattern
        sec = self._section(pages["wzorce"], "Własny wzorzec")
        self.pattern_entry = Gtk.Entry()
        self.pattern_entry.set_text("20;5;15;0;20;10")
        self.pattern_entry.set_placeholder_text("0–20 oddzielone ;")
        sec.append(self.pattern_entry)
        prow_p = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prow_p.append(Gtk.Label(label="Interwał ms:"))
        self.interval_entry = Gtk.Entry()
        self.interval_entry.set_text("200")
        self.interval_entry.set_width_chars(6)
        prow_p.append(self.interval_entry)
        pb = Gtk.Button(label="Odtwórz")
        pb.connect("clicked", lambda *_: self._pattern())
        prow_p.append(pb)
        sec.append(prow_p)

        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pattern_name_entry = Gtk.Entry()
        self.pattern_name_entry.set_placeholder_text("Nazwa zapisu…")
        self.pattern_name_entry.set_hexpand(True)
        save_row.append(self.pattern_name_entry)
        save_b = Gtk.Button(label="Zapisz wzorzec")
        save_b.connect("clicked", lambda *_: self._save_pattern())
        save_row.append(save_b)
        del_b = Gtk.Button(label="Usuń")
        del_b.connect("clicked", lambda *_: self._delete_saved_pattern())
        save_row.append(del_b)
        sec.append(save_row)

        fav_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        fav_row.append(Gtk.Label(label="Zapisane:"))
        self.saved_pattern_dd = Gtk.DropDown.new_from_strings(["(brak)"])
        self.saved_pattern_dd.set_hexpand(True)
        fav_row.append(self.saved_pattern_dd)
        load_b = Gtk.Button(label="Wczytaj i graj")
        load_b.connect("clicked", lambda *_: self._play_saved_pattern())
        fav_row.append(load_b)
        sec.append(fav_row)
        self._refresh_saved_patterns_dd()

        # Audio react
        sec = self._section(pages["audio"], "Reakcja na dźwięk")
        audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        audio_row.append(Gtk.Label(label="Włącz audio → zabawka", hexpand=True, xalign=0))
        self.audio_sw = Gtk.Switch()
        self._audio_sw_guard = False
        self.audio_sw.connect("notify::active", self._on_audio_sw)
        audio_row.append(self.audio_sw)
        sec.append(audio_row)
        self.audio_remote_hint = Gtk.Label(
            label="Partnerka może to włączać/wyłączać z panelu (Opcje → Audio), jeśli remote_allow_audio=true. "
            "Uwaga: w trybie gry klawisz „A” też przełącza audio — łatwo włączyć przypadkiem.",
            wrap=True,
            xalign=0,
        )
        self.audio_remote_hint.add_css_class("dim-label")
        sec.append(self.audio_remote_hint)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode_row.append(Gtk.Label(label="Źródło:"))
        self.audio_mode_dd = Gtk.DropDown.new_from_strings(
            [
                "Aplikacje (Firefox, gry, YouTube…)",
                "Mikrofon",
            ]
        )
        if (self.config.audio_mode or "playback").lower() in ("mic", "microphone", "input"):
            self.audio_mode_dd.set_selected(1)
        else:
            self.audio_mode_dd.set_selected(0)
        self.audio_mode_dd.set_hexpand(True)
        self.audio_mode_dd.connect("notify::selected", self._on_audio_mode)
        mode_row.append(self.audio_mode_dd)
        sec.append(mode_row)

        dev_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.audio_dev_lbl = Gtk.Label(label="Wyjście (głośniki):")
        dev_row.append(self.audio_dev_lbl)
        self._sinks = list_playback_sinks() or []
        default_sink = default_sink_name() or ""
        if default_sink and default_sink not in self._sinks:
            self._sinks.insert(0, default_sink)
        if not self._sinks:
            self._sinks = ["(domyślny systemowy)"]
        self._sources = list_input_sources() or []
        default_src = default_source_name() or ""
        if default_src and default_src not in self._sources:
            self._sources.insert(0, default_src)
        if not self._sources:
            self._sources = ["(domyślny mikrofon)"]
        self.sink_dd = Gtk.DropDown.new_from_strings(self._sinks)
        if default_sink in self._sinks:
            self.sink_dd.set_selected(self._sinks.index(default_sink))
        self.sink_dd.set_hexpand(True)
        dev_row.append(self.sink_dd)
        sec.append(dev_row)
        self._refresh_audio_device_list()

        self.audio_level_lbl = Gtk.Label(label="Poziom: —  → V=0 P=0", xalign=0)
        sec.append(self.audio_level_lbl)

        sens_lbl = Gtk.Label(label=f"Czułość: {self.config.audio_sensitivity:.1f}", xalign=0)
        self.sens_lbl = sens_lbl
        self.sens_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.3, 3.0, 0.1)
        self.sens_scale.set_value(self.config.audio_sensitivity)
        self.sens_scale.set_draw_value(False)
        self.sens_scale.connect(
            "value-changed",
            lambda s: (
                setattr(self.config, "audio_sensitivity", float(s.get_value())),
                self.sens_lbl.set_text(f"Czułość: {s.get_value():.1f}"),
            ),
        )
        sec.append(sens_lbl)
        sec.append(self.sens_scale)

        gain_lbl = Gtk.Label(label=f"Wzmocnienie: {self.config.audio_gain:.1f}", xalign=0)
        self.gain_lbl = gain_lbl
        self.gain_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1.0, 30.0, 0.5)
        self.gain_scale.set_value(self.config.audio_gain)
        self.gain_scale.set_draw_value(False)
        self.gain_scale.connect(
            "value-changed",
            lambda s: (
                setattr(self.config, "audio_gain", float(s.get_value())),
                self.gain_lbl.set_text(f"Wzmocnienie: {s.get_value():.1f}"),
            ),
        )
        sec.append(gain_lbl)
        sec.append(self.gain_scale)

        pump_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pump_row.append(Gtk.Label(label="Pump też od dźwięku", hexpand=True, xalign=0))
        self.audio_pump_sw = Gtk.Switch()
        self.audio_pump_sw.set_active(self.config.audio_pump_enabled)
        self.audio_pump_sw.connect(
            "notify::active",
            lambda *_: setattr(self.config, "audio_pump_enabled", self.audio_pump_sw.get_active()),
        )
        pump_row.append(self.audio_pump_sw)
        sec.append(pump_row)

        audio_hint = Gtk.Label(
            label=(
                "„Aplikacje” = dźwięk z Firefoxa/gier (monitor głośników), NIE mikrofon.\n"
                "Wybierz to samo wyjście co w systemie (u Ciebie: Scarlett). "
                "Firefox musi grać na to wyjście. Połącz BLE, potem włącz. "
                "Skrót: Ctrl+Shift+A."
            ),
            wrap=True,
            xalign=0,
        )
        audio_hint.add_css_class("dim-label")
        sec.append(audio_hint)
        self.audio.on_level(self._on_audio_level)

        # Klawiatura — włączniki + edytor skrótów
        sec = self._section(pages["skroty"], "Skróty globalne i tryb gry")
        en_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        en_row.append(Gtk.Label(label="Skróty globalne włączone", hexpand=True, xalign=0))
        self.hotkeys_sw = Gtk.Switch()
        self.hotkeys_sw.set_active(self.config.hotkeys_enabled)
        self.hotkeys_sw.connect("notify::active", self._on_hotkeys_enabled_sw)
        en_row.append(self.hotkeys_sw)
        sec.append(en_row)

        game_hk = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        game_hk.append(Gtk.Label(label="Tryb gry (proste klawisze globalnie)", hexpand=True, xalign=0))
        self.game_keys_sw = Gtk.Switch()
        self.game_keys_sw.set_active(self.config.hotkeys_game_mode)
        self.game_keys_sw.connect("notify::active", self._on_game_keys_sw)
        game_hk.append(self.game_keys_sw)
        sec.append(game_hk)

        keys_hint = Gtk.Label(
            label=(
                "Kliknij przycisk skrótu → naciśnij klawisze → Enter zatwierdza, Esc anuluje.\n"
                "„Chord” = z modyfikatorami (bezpieczniejsze). „Gra” = pojedynczy klawisz "
                "(działa globalnie — ostrożnie przy pisaniu)."
            ),
            wrap=True,
            xalign=0,
        )
        keys_hint.add_css_class("dim-label")
        sec.append(keys_hint)

        # Przewijana lista akcji
        hk_scroll = Gtk.ScrolledWindow()
        hk_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        hk_scroll.set_min_content_height(280)
        hk_scroll.set_max_content_height(360)
        hk_scroll.set_propagate_natural_height(True)
        self._hotkey_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hk_scroll.set_child(self._hotkey_list_box)
        sec.append(hk_scroll)
        self._hotkey_row_widgets: dict[str, tuple[Gtk.Button, Gtk.Button]] = {}
        self._rebuild_hotkey_rows()

        hk_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_b = Gtk.Button(label="Przywróć domyślne skróty")
        reset_b.connect("clicked", lambda *_: self._reset_hotkeys())
        hk_btns.append(reset_b)
        sec.append(hk_btns)

        # Integracje
        sec = self._section(pages["zdalne"], "Integracje")
        self.game_sw = Gtk.Switch()
        self.game_sw.set_active(self.config.game_api_enabled)
        self.game_sw.connect("notify::active", self._on_game_sw)
        game_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        game_row.append(Gtk.Label(label="API do gier (localhost)", hexpand=True, xalign=0))
        game_row.append(self.game_sw)
        sec.append(game_row)
        self.game_info = Gtk.Label(label="", wrap=True, xalign=0, selectable=True)
        sec.append(self.game_info)

        # --- Zdalne: panel partnerki + skrypt SL ---
        sec = self._section(pages["zdalne"], "Zdalne sterowanie")
        rem_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        rem_row.append(
            Gtk.Label(label="Udostępnij (panel + internet)", hexpand=True, xalign=0)
        )
        self.remote_sw = Gtk.Switch()
        self.remote_sw.connect("notify::active", self._on_remote_sw)
        rem_row.append(self.remote_sw)
        sec.append(rem_row)

        self.remote_status_lbl = Gtk.Label(label="Wyłączone", wrap=True, xalign=0)
        sec.append(self.remote_status_lbl)

        sec.append(Gtk.Label(label="Adres dla partnerki (przeglądarka):", xalign=0))
        url_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.partner_url_entry = Gtk.Entry()
        self.partner_url_entry.set_editable(False)
        self.partner_url_entry.set_placeholder_text("Włącz udostępnianie — tu pojawi się link")
        self.partner_url_entry.set_hexpand(True)
        url_row.append(self.partner_url_entry)
        copy_url_btn = Gtk.Button(label="Kopiuj adres")
        copy_url_btn.add_css_class("suggested-action")
        copy_url_btn.connect("clicked", lambda *_: self._copy_partner_url())
        url_row.append(copy_url_btn)
        sec.append(url_row)

        sl_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        copy_lsl = Gtk.Button(label="Kopiuj skrypt LSL")
        copy_lsl.connect("clicked", lambda *_: self._copy_sl_script())
        sl_btns.append(copy_lsl)
        copy_note = Gtk.Button(label="Kopiuj notatkę (token + URL)")
        copy_note.connect("clicked", lambda *_: self._copy_sl_notecard())
        sl_btns.append(copy_note)
        sec.append(sl_btns)

        self.sl_info = Gtk.Label(
            label=(
                "Włącz przełącznik. Partnerka otwiera adres w przeglądarce.\n"
                "W SL: skrypt wklej do HUD, notatkę wrzuć jako lovense.cfg."
            ),
            wrap=True,
            xalign=0,
            selectable=True,
        )
        self.sl_info.add_css_class("dim-label")
        sec.append(self.sl_info)

        # aliasy / ukryte pola — stary kod tunelu nadal je uzupełnia
        self.remote_link_entry = self.partner_url_entry
        self.internet_link_entry = self.partner_url_entry
        self.remote_info = self.sl_info
        self.sl_tunnel_entry = Gtk.Entry()
        if self.config.tunnel_public_url:
            self.sl_tunnel_entry.set_text(self.config.tunnel_public_url.rstrip("/"))
        self.sl_base_entry = Gtk.Entry()
        self.sl_token_entry = Gtk.Entry()
        self.sl_example_entry = Gtk.Entry()
        self.internet_status_lbl = self.remote_status_lbl

        self._build_sessions_page(pages["sesje"])
        self._update_sl_ui()

        # Log
        sec = self._section(pages["log"], "Log")
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_monospace(True)
        self.log_buf = self.log_view.get_buffer()
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(140)
        log_scroll.set_child(self.log_view)
        log_scroll.set_vexpand(True)
        sec.append(log_scroll)

    # ---- helpers ----
    def _bg(self, fn) -> None:
        def runner():
            try:
                fn()
            except Exception:
                logger.exception("background task")
                self._ui(lambda: self.controller.log("Błąd w tle — zobacz terminal"))

        threading.Thread(target=runner, daemon=True, name="max2-bg").start()

    def _ui(self, fn) -> None:
        """Zawsze na wątku GTK; idle_add musi zwracać False (inaczej pętla = freeze)."""

        def wrapper():
            try:
                fn()
            except Exception:
                logger.exception("UI update failed")
            return False  # GLib.SOURCE_REMOVE

        GLib.idle_add(wrapper)

    def _clear_listbox(self, listbox: Gtk.ListBox) -> None:
        """Bezpieczne czyszczenie ListBox (GTK4)."""
        try:
            while True:
                row = listbox.get_row_at_index(0)
                if row is None:
                    break
                listbox.remove(row)
        except Exception:
            # fallback: unparent
            child = listbox.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                listbox.remove(child)
                child = nxt

    def _initial_load(self) -> bool:
        # nie skanuj od razu na starcie (może „zamrażać” pierwsze sekundy) —
        # user klika Skanuj BLE
        self.scan_status_lbl.set_text("Kliknij „Skanuj BLE”, potem „Połącz” przy zabawce.")
        self.controller.start_battery_poll()
        if self.config.game_api_enabled:
            # set_active wywoła _on_game_sw → start (jeśli jeszcze nie)
            if not self.game_sw.get_active():
                self.game_sw.set_active(True)
            elif not (self._game_handle and self._game_handle.running):
                self._start_game_api()
        # Wznów panel remote po restarcie. Auto-start tunelu wymaga też panelu.
        want_remote = bool(self.config.remote_enabled or self.config.tunnel_auto_start)
        if want_remote:
            if not self.remote_sw.get_active():
                self.remote_sw.set_active(True)
            elif not (self._remote_handle and self._remote_handle.running):
                self._start_remote()
            if self.config.tunnel_auto_start:
                GLib.timeout_add(800, self._auto_start_tunnel_once)
        return False

    def _auto_start_tunnel_once(self) -> bool:
        try:
            if self.config.tunnel_auto_start:
                self.controller.log("Auto-start tunnelu internetowego…")
                self._start_internet_share()
        except Exception:
            logger.exception("auto tunnel")
        return False  # nie powtarzaj

    def _save_url(self) -> None:
        url = self.url_entry.get_text().strip()
        self._bg(lambda: self.controller.update_lovense_url(url))

    def _on_backend(self, *_args) -> None:
        idx = self.backend_dd.get_selected()
        name = "ble" if idx == 0 else "lovense_local"

        def work():
            self.controller.set_backend(name)
            self._ui(self._sync_toy_menu)

        self._bg(work)

    def _ble_scan(self) -> None:
        if self._scan_busy:
            self.controller.log("Skan już trwa…")
            return
        self._scan_busy = True
        self.scan_status_lbl.set_text("⏳ Skanowanie Bluetooth (~5 s) — okno powinno reagować…")
        self.controller.log("Skanowanie Bluetooth…")

        def work():
            try:
                self.controller.ble_scan(timeout=5.0)
            except Exception as e:
                logger.exception("scan")
                self.controller.log(f"Skan błąd: {e}")
            finally:
                self._scan_busy = False
                self._ui(self._sync_toy_menu)

        self._bg(work)

    def _ble_connect(self) -> None:
        """Połącz wybraną z listy połączonych / last selected."""
        tid = self.controller.state.selected_toy_id
        if not tid:
            self.controller.log("Wybierz zabawkę z listy skanu (przycisk Połącz przy wierszu)")
            return
        self._connect_id(tid)

    def _connect_id(self, toy_id: str) -> None:
        self.scan_status_lbl.set_text(f"Łączenie z {toy_id[:17]}…")
        self.controller.select_toy(toy_id)

        def work():
            try:
                self.controller.ble_connect(toy_id)
            except Exception as e:
                logger.exception("connect")
                self.controller.log(f"Połączenie błąd: {e}")
            finally:
                self._ui(self._sync_toy_menu)

        self._bg(work)

    def _ble_disconnect_one(self) -> None:
        from max2_controller.backends.ble_lovense import TOY_ALL

        tid = self.controller.state.selected_toy_id
        if not tid or tid == TOY_ALL:
            self.controller.log("Zaznacz zabawkę na liście „Połączone teraz”")
            return
        self._disconnect_id(tid)

    def _ble_disconnect_all(self) -> None:
        from max2_controller.backends.ble_lovense import TOY_ALL

        def work():
            self.controller.ble_disconnect(TOY_ALL)
            self._ui(self._sync_toy_menu)

        self._bg(work)

    def _on_control_all(self, *_args) -> None:
        self.controller.set_control_all(self.control_all_sw.get_active())
        self._update_secondary_slider()

    def _refresh_toys(self) -> None:
        self._ble_scan()

    def _sync_toy_menu(self) -> None:
        try:
            toys = list(self.controller.state.toys)
            self._toy_map = {t.display_name: t.id for t in toys}
            self._rebuild_scan_list(toys)
            self._rebuild_connected_list()
            self._update_secondary_slider()
            self._refresh_state_labels()
            n = len(toys)
            n_conn = self.controller.state.connected_count
            self.scan_status_lbl.set_text(
                f"Skan: {n} widocznych · połączonych w app: {n_conn}. "
                "Kliknij „Połącz” przy kolejnej zabawce, żeby dodać drugą."
            )
        except Exception:
            logger.exception("sync toy menu")

    def _rebuild_scan_list(self, toys: list) -> None:
        self._clear_listbox(self.scan_list)
        # pokaż te jeszcze niepołączone w appce + połączone (z etykietą)
        if hasattr(self.controller.backend, "connected_infos"):
            try:
                conn_ids = {t.id.upper() for t in self.controller.backend.connected_infos()}
            except Exception:
                conn_ids = set()
        else:
            conn_ids = {t.id.upper() for t in toys if t.app_connected}

        shown = 0
        for t in toys:
            already = t.id.upper() in conn_ids or t.app_connected
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            box.set_margin_start(6)
            box.set_margin_end(6)
            model = t.model_name or "Lovense"
            mark = "✓ połączona" if already else "dostępna"
            lbl = Gtk.Label(
                label=f"{model}  ·  {t.name}\n{t.id}  ({mark})",
                xalign=0,
            )
            lbl.set_hexpand(True)
            box.append(lbl)
            if already:
                btn = Gtk.Button(label="OK")
                btn.set_sensitive(False)
            else:
                btn = Gtk.Button(label="Połącz")
                btn.add_css_class("suggested-action")
                btn.connect("clicked", lambda _b, tid=t.id: self._connect_id(tid))
            box.append(btn)
            row.set_child(box)
            self.scan_list.append(row)
            shown += 1

        self.scan_empty_lbl.set_visible(shown == 0)

    def _rebuild_connected_list(self) -> None:
        self._clear_listbox(self.connected_list)
        connected = []
        if hasattr(self.controller.backend, "connected_infos"):
            try:
                connected = self.controller.backend.connected_infos()
            except Exception:
                connected = []
        if not connected:
            connected = [t for t in self.controller.state.toys if t.app_connected]

        self._connected_rows: dict[int, str] = {}
        if not connected:
            self.connected_empty_lbl.set_visible(True)
            return
        self.connected_empty_lbl.set_visible(False)

        for t in connected:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            model = t.model_name or "Lovense"
            sec = {
                "pump": "Max·pump",
                "rotate": "Nora·rotate",
                "vibrate2": "Gemini·2silniki",
                "none": "Lush·vibrate",
            }.get(t.secondary, t.secondary)
            bat = f"{t.battery}%" if t.battery is not None else "?"
            lbl = Gtk.Label(
                label=f"● {model}  [{sec}]  🔋{bat}\n  {t.name}  ·  {t.id}",
                xalign=0,
            )
            lbl.set_hexpand(True)
            box.append(lbl)
            disc = Gtk.Button(label="Rozłącz")
            disc.connect("clicked", lambda _b, tid=t.id: self._disconnect_id(tid))
            box.append(disc)
            row.set_child(box)
            row.set_activatable(True)
            self.connected_list.append(row)
            self._connected_rows[id(row)] = t.id

        sel_id = self.controller.state.selected_toy_id
        if sel_id:
            i = 0
            while True:
                row = self.connected_list.get_row_at_index(i)
                if row is None:
                    break
                if self._connected_rows.get(id(row)) == sel_id:
                    self.connected_list.select_row(row)
                    break
                i += 1

    def _on_connected_row(self, _listbox, row) -> None:
        if row is None:
            return
        tid = getattr(self, "_connected_rows", {}).get(id(row))
        if tid:
            self.controller.select_toy(tid)
            self._update_secondary_slider()
            self._refresh_state_labels()

    def _disconnect_id(self, toy_id: str) -> None:
        def work():
            self.controller.ble_disconnect(toy_id)
            self._ui(self._sync_toy_menu)

        self._bg(work)

    def _on_vibrate(self, scale: Gtk.Scale) -> None:
        if self._updating_sliders:
            return
        v = int(round(scale.get_value()))
        self.vib_lbl.set_text(f"Vibrate: {v} / 20")
        self.controller.set_levels(vibrate=v, immediate=False)

    def _on_pump(self, scale: Gtk.Scale) -> None:
        if self._updating_sliders:
            return
        p = int(round(scale.get_value()))
        toy = self.controller.selected_toy()
        mx = toy.secondary_max() if toy and toy.secondary != "none" else 3
        label = toy.secondary_label() if toy else "Druga funkcja"
        self.pump_lbl.set_text(f"{label}: {p} / {mx or 3}")
        self.controller.set_levels(pump=p, immediate=False)

    def _update_secondary_slider(self) -> None:
        toy = self.controller.selected_toy()
        # przy sterowaniu wszystkimi — pokaż zakres max z połączonych
        if self.controller.state.control_all and hasattr(self.controller.backend, "connected_infos"):
            infos = self.controller.backend.connected_infos()
            if infos:
                # suwak 2: max z secondary_max wśród urządzeń które go mają
                secs = [t for t in infos if t.secondary != "none"]
                if secs:
                    mx = float(max(t.secondary_max() for t in secs))
                    self.pump_scale.set_range(0, mx)
                    self.pump_scale.set_sensitive(True)
                    kinds = ", ".join(sorted({t.secondary_label().split("·")[0].strip() for t in secs}))
                    self.pump_lbl.set_text(f"2. funkcja (mix): {kinds}")
                else:
                    self.pump_scale.set_range(0, 3)
                    self.pump_scale.set_sensitive(False)
                    self.pump_lbl.set_text("2. funkcja: brak (same Lush / single-motor)")
                names = ", ".join(t.model_name or t.name for t in infos)
                self.model_lbl.set_text(f"Połączone ({len(infos)}): {names}")
                if hasattr(self, "vib_lbl"):
                    self.vib_lbl.set_text("Vibrate / silnik 1 (0–20) — wszystkie")
                return

        if toy and toy.connected and toy.secondary != "none":
            mx = float(toy.secondary_max())
            self.pump_scale.set_range(0, mx)
            self.pump_scale.set_increments(1, 1)
            self.pump_lbl.set_text(f"{toy.secondary_label()}: {int(self.pump_scale.get_value())} / {int(mx)}")
            self.model_lbl.set_text(
                f"Model: {toy.model_name or toy.name} · 2. funkcja: {toy.secondary}"
            )
            self.pump_scale.set_sensitive(True)
            if hasattr(self, "vib_lbl"):
                self.vib_lbl.set_text(f"{toy.primary_label()}: {int(self.vib_scale.get_value())}")
        elif toy and toy.connected:
            self.pump_scale.set_range(0, 3)
            self.pump_scale.set_sensitive(False)
            self.pump_lbl.set_text("Druga funkcja: brak (Lush 3 = tylko wibracje)")
            self.model_lbl.set_text(f"Model: {toy.model_name or toy.name}")
            if hasattr(self, "vib_lbl"):
                self.vib_lbl.set_text(f"{toy.primary_label()}: {int(self.vib_scale.get_value())}")
        else:
            self.pump_scale.set_sensitive(True)
            self.model_lbl.set_text("Model: — Lush 3 · Nora · Max 2 · Gemini")

    def _on_time(self, scale: Gtk.Scale) -> None:
        t = int(round(scale.get_value()))
        self.time_lbl.set_text(f"Czas: {t} s (0 = ciągły)")
        self.controller.state.time_sec = float(t)

    def _apply(self) -> None:
        self._bg(self.controller.apply_now)

    def _stop(self) -> None:
        def work():
            self.controller.stop_auto_modes()
            self.controller.stop()
            self._ui(self._zero_sliders)
        self._bg(work)

    def _zero_sliders(self) -> None:
        self._updating_sliders = True
        try:
            self.vib_scale.set_value(0)
            self.pump_scale.set_value(0)
            self.vib_lbl.set_text("Vibrate: 0 / 20")
            self.pump_lbl.set_text("Pump: 0 / 3")
        finally:
            self._updating_sliders = False

    def _battery(self) -> None:
        self._bg(self.controller.refresh_battery)

    def _preset(self, name: str) -> None:
        self._bg(lambda: self.controller.preset(name))

    def _pattern(self) -> None:
        strength = self.pattern_entry.get_text().strip()
        try:
            interval = int(self.interval_entry.get_text().strip() or "200")
        except ValueError:
            self.controller.log("Interwał musi być liczbą (ms)")
            return
        self._bg(lambda: self.controller.pattern(strength, interval_ms=interval))

    def _quick_percent(self, percent: int) -> None:
        def work():
            if percent == 0:
                self.controller.stop_auto_modes()
            self.controller.set_quick_percent(percent)
            self._ui(self._sync_sliders_from_state)

        self._bg(work)

    def _boost(self) -> None:
        boost = self.config.clamp_vibrate(self.config.control_boost_level)
        self._bg(lambda: self.controller.set_levels(vibrate=boost, immediate=True))

    def _on_max_vibrate(self, scale: Gtk.Scale) -> None:
        v = int(round(scale.get_value()))
        self.config.control_max_vibrate = max(1, min(20, v))
        self.max_vib_lbl.set_text(f"Limit max wibracji: {self.config.control_max_vibrate}")
        # ogranicz bieżący poziom
        if self.controller.state.vibrate > self.config.control_max_vibrate:
            self.controller.set_levels(
                vibrate=self.config.control_max_vibrate, immediate=True
            )
        self.config.save()

    def _sync_sliders_from_state(self) -> None:
        st = self.controller.state
        self._updating_sliders = True
        try:
            self.vib_scale.set_value(st.vibrate)
            self.pump_scale.set_value(st.pump)
            self.vib_lbl.set_text(f"Vibrate: {st.vibrate} / 20")
        finally:
            self._updating_sliders = False

    def _save_pattern(self) -> None:
        name = self.pattern_name_entry.get_text().strip()
        strength = self.pattern_entry.get_text().strip()
        if not strength:
            self.controller.log("Wpisz wzorzec przed zapisem")
            return
        try:
            interval = int(self.interval_entry.get_text().strip() or "200")
        except ValueError:
            interval = 200
        self.config.save_pattern(name or "Wzorzec", strength, interval)
        self.config.save()
        self._refresh_saved_patterns_dd()
        self.controller.log(f"Zapisano wzorzec: {name or 'Wzorzec'}")

    def _delete_saved_pattern(self) -> None:
        names = [p.name for p in self.config.get_saved_patterns()]
        if not names:
            return
        idx = self.saved_pattern_dd.get_selected()
        if idx < 0 or idx >= len(names):
            return
        name = names[idx]
        self.config.delete_pattern(name)
        self.config.save()
        self._refresh_saved_patterns_dd()
        self.controller.log(f"Usunięto wzorzec: {name}")

    def _play_saved_pattern(self) -> None:
        patterns = self.config.get_saved_patterns()
        if not patterns:
            self.controller.log("Brak zapisanych wzorców")
            return
        idx = self.saved_pattern_dd.get_selected()
        if idx < 0 or idx >= len(patterns):
            return
        p = patterns[idx]
        self.pattern_entry.set_text(p.strength)
        self.interval_entry.set_text(str(p.interval_ms))
        self.pattern_name_entry.set_text(p.name)
        self._bg(
            lambda: self.controller.pattern(p.strength, interval_ms=p.interval_ms)
        )

    def _refresh_saved_patterns_dd(self) -> None:
        names = [p.name for p in self.config.get_saved_patterns()]
        if not names:
            names = ["(brak)"]
        model = Gtk.StringList.new(names)
        self.saved_pattern_dd.set_model(model)
        self.saved_pattern_dd.set_selected(0)

    # ---- hotkey editor ----
    def _rebuild_hotkey_rows(self) -> None:
        # wyczyść
        child = self._hotkey_list_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._hotkey_list_box.remove(child)
            child = nxt
        self._hotkey_row_widgets.clear()

        current_group = None
        for action in HOTKEY_ACTIONS:
            if action.group != current_group:
                current_group = action.group
                g = Gtk.Label(
                    label=GROUP_LABELS.get(action.group, action.group),
                    xalign=0,
                )
                g.add_css_class("heading")
                g.set_margin_top(8)
                self._hotkey_list_box.append(g)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lab = Gtk.Label(label=action.label, xalign=0, hexpand=True)
            try:
                from gi.repository import Pango

                lab.set_ellipsize(Pango.EllipsizeMode.END)
            except Exception:
                pass
            row.append(lab)

            chord = self.config.chord_for(action.id)
            chord_b = Gtk.Button(label=format_chord_display(chord))
            chord_b.set_tooltip_text("Kliknij i naciśnij skrót chord (z Ctrl/Alt/Shift)")
            chord_b.set_size_request(140, -1)
            chord_b.connect(
                "clicked",
                lambda _b, aid=action.id: self._capture_hotkey(aid, kind="chord"),
            )
            row.append(chord_b)

            clear_c = Gtk.Button(label="×")
            clear_c.set_tooltip_text("Wyczyść chord")
            clear_c.connect(
                "clicked",
                lambda _b, aid=action.id: self._clear_hotkey(aid, kind="chord"),
            )
            row.append(clear_c)

            gkey = self.config.game_key_for(action.id)
            game_b = Gtk.Button(label=format_game_display(gkey))
            game_b.set_tooltip_text("Kliknij i naciśnij klawisz trybu gry")
            game_b.set_size_request(72, -1)
            game_b.connect(
                "clicked",
                lambda _b, aid=action.id: self._capture_hotkey(aid, kind="game"),
            )
            row.append(game_b)

            clear_g = Gtk.Button(label="×")
            clear_g.set_tooltip_text("Wyczyść klawisz gry")
            clear_g.connect(
                "clicked",
                lambda _b, aid=action.id: self._clear_hotkey(aid, kind="game"),
            )
            row.append(clear_g)

            self._hotkey_list_box.append(row)
            self._hotkey_row_widgets[action.id] = (chord_b, game_b)

    def _update_hotkey_row_labels(self, action_id: str) -> None:
        widgets = self._hotkey_row_widgets.get(action_id)
        if not widgets:
            return
        chord_b, game_b = widgets
        chord_b.set_label(format_chord_display(self.config.chord_for(action_id)))
        game_b.set_label(format_game_display(self.config.game_key_for(action_id)))

    def _clear_hotkey(self, action_id: str, kind: str) -> None:
        if kind == "chord":
            self.config.set_chord(action_id, "")
        else:
            self.config.set_game_key(action_id, "")
        self.config.save()
        self._update_hotkey_row_labels(action_id)
        self._restart_hotkeys()

    def _reset_hotkeys(self) -> None:
        self.config.reset_hotkeys_to_defaults()
        self.config.save()
        self._rebuild_hotkey_rows()
        self._restart_hotkeys()
        self.controller.log("Skróty przywrócone do domyślnych")

    def _restart_hotkeys(self) -> None:
        if self.hotkeys and self.config.hotkeys_enabled:
            self.hotkeys.restart()
        elif self.hotkeys:
            self.hotkeys.stop()

    def _on_hotkeys_enabled_sw(self, *_args) -> None:
        self.config.hotkeys_enabled = self.hotkeys_sw.get_active()
        self.config.save()
        self._restart_hotkeys()
        self.controller.log(
            "Skróty: " + ("WŁĄCZONE" if self.config.hotkeys_enabled else "wyłączone")
        )

    def _capture_hotkey(self, action_id: str, kind: str) -> None:
        """Dialog: naciśnij skrót (chord lub game)."""
        win = self.win
        if win is None:
            return

        action = next((a for a in HOTKEY_ACTIONS if a.id == action_id), None)
        title = action.label if action else action_id
        dlg = Gtk.Window(title=f"Skrót: {title}", transient_for=win, modal=True)
        dlg.set_default_size(380, 160)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dlg.set_child(box)

        kind_pl = "chord (np. Ctrl+Shift+S)" if kind == "chord" else "pojedynczy klawisz trybu gry"
        info = Gtk.Label(
            label=f"Naciśnij {kind_pl}\nEnter = zapisz · Esc = anuluj · Backspace = wyczyść",
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        box.append(info)
        preview = Gtk.Label(label="…")
        preview.add_css_class("title-2")
        box.append(preview)

        captured: dict[str, str | None] = {"value": None}

        def on_key(_ctrl, keyval, _keycode, state) -> bool:
            # Enter / Esc specjalne
            try:
                from gi.repository import Gdk
            except Exception:
                return False
            name = (Gdk.keyval_name(keyval) or "").lower()
            if name in ("return", "kp_enter"):
                if captured["value"] is not None:
                    self._apply_captured(action_id, kind, captured["value"])
                dlg.close()
                return True
            if name == "escape":
                dlg.close()
                return True
            if name == "backspace":
                captured["value"] = ""
                preview.set_text("(wyczyszczone — Enter aby zapisać)")
                return True

            if kind == "chord":
                chord = gtk_key_to_chord(keyval, int(state))
                if not chord:
                    return True
                captured["value"] = chord
                preview.set_text(format_chord_display(chord))
            else:
                gkey = gtk_key_to_game(keyval, int(state))
                if not gkey:
                    return True
                captured["value"] = gkey
                preview.set_text(format_game_display(gkey))
            return True

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", on_key)
        dlg.add_controller(controller)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.CENTER)
        ok_b = Gtk.Button(label="Zapisz")
        ok_b.add_css_class("suggested-action")

        def do_save(*_a):
            if captured["value"] is not None:
                self._apply_captured(action_id, kind, captured["value"])
            dlg.close()

        ok_b.connect("clicked", do_save)
        cancel_b = Gtk.Button(label="Anuluj")
        cancel_b.connect("clicked", lambda *_: dlg.close())
        btn_row.append(cancel_b)
        btn_row.append(ok_b)
        box.append(btn_row)

        dlg.present()

    def _apply_captured(self, action_id: str, kind: str, value: str | None) -> None:
        value = value if value is not None else ""
        # wykryj kolizje
        if value:
            if kind == "chord":
                for a in HOTKEY_ACTIONS:
                    if a.id != action_id and self.config.chord_for(a.id) == value:
                        self.controller.log(
                            f"Uwaga: chord {format_chord_display(value)} był też na „{a.label}” — przejęty"
                        )
                        self.config.set_chord(a.id, "")
                        self._update_hotkey_row_labels(a.id)
                self.config.set_chord(action_id, value)
            else:
                for a in HOTKEY_ACTIONS:
                    if a.id != action_id and self.config.game_key_for(a.id) == value:
                        self.controller.log(
                            f"Uwaga: klawisz {format_game_display(value)} był też na „{a.label}” — przejęty"
                        )
                        self.config.set_game_key(a.id, "")
                        self._update_hotkey_row_labels(a.id)
                self.config.set_game_key(action_id, value)
        else:
            if kind == "chord":
                self.config.set_chord(action_id, "")
            else:
                self.config.set_game_key(action_id, "")
        self.config.save()
        self._update_hotkey_row_labels(action_id)
        self._restart_hotkeys()
        shown = (
            format_chord_display(value)
            if kind == "chord"
            else format_game_display(value)
        )
        self.controller.log(f"Skrót {action_id} ({kind}): {shown}")

    # ---- audio / keys ----
    def _audio_mode_name(self) -> str:
        return "microphone" if self.audio_mode_dd.get_selected() == 1 else "playback"

    def _refresh_audio_device_list(self) -> None:
        mode = self._audio_mode_name()
        if mode == "microphone":
            self.audio_dev_lbl.set_text("Mikrofon:")
            labels = self._sources
            prefer = self.config.audio_source or default_source_name() or ""
        else:
            self.audio_dev_lbl.set_text("Wyjście (Firefox/gry):")
            labels = self._sinks
            prefer = self.config.audio_sink or default_sink_name() or ""
        model = Gtk.StringList.new(labels)
        self.sink_dd.set_model(model)
        if prefer in labels:
            self.sink_dd.set_selected(labels.index(prefer))
        else:
            self.sink_dd.set_selected(0)

    def _on_audio_mode(self, *_args) -> None:
        self._refresh_audio_device_list()
        # jeśli audio włączone — zrestartuj z nowym źródłem
        if self.audio_sw.get_active():
            self.audio.stop(send_zero=False)
            self._on_audio_sw()

    def _selected_audio_device(self) -> str:
        mode = self._audio_mode_name()
        labels = self._sources if mode == "microphone" else self._sinks
        idx = self.sink_dd.get_selected()
        if 0 <= idx < len(labels):
            s = labels[idx]
            if s.startswith("("):
                return (
                    (default_source_name() or "")
                    if mode == "microphone"
                    else (default_sink_name() or "")
                )
            return s
        return (
            (default_source_name() or "")
            if mode == "microphone"
            else (default_sink_name() or "")
        )

    def _on_audio_sw(self, *_args) -> None:
        if getattr(self, "_audio_sw_guard", False):
            return
        if self.audio_sw.get_active():
            mode = self._audio_mode_name()
            self.config.audio_mode = mode
            dev = self._selected_audio_device()
            if mode == "microphone":
                self.config.audio_source = dev
            else:
                self.config.audio_sink = dev
            self.config.audio_sensitivity = float(self.sens_scale.get_value())
            self.config.audio_gain = float(self.gain_scale.get_value())
            self.config.audio_pump_enabled = self.audio_pump_sw.get_active()
            self.config.save()
            ok, msg = self.audio.start()
            if not ok:
                self.controller.log(msg)
                self._audio_sw_guard = True
                try:
                    self.audio_sw.set_active(False)
                finally:
                    self._audio_sw_guard = False
            else:
                self.controller.log(
                    "Szukaj w logu: „GStreamer → aplikacje/głośniki: ….monitor” — wtedy to NIE mikrofon."
                )
        else:
            self.audio.stop(send_zero=True)
            self.config.save()

    def _sync_audio_switch_from_engine(self) -> None:
        """Po zmianie z remote/API ustaw przełącznik GUI bez pętli."""
        if not hasattr(self, "audio_sw"):
            return
        running = bool(self.audio.running or self.audio.enabled)
        if self.audio_sw.get_active() == running:
            return
        self._audio_sw_guard = True
        try:
            self.audio_sw.set_active(running)
        finally:
            self._audio_sw_guard = False

    def _toggle_audio_from_hotkey(self) -> None:
        def flip():
            # bezpośredni set na silniku — nie tylko flip switcha (odporne na desync)
            want = not (self.audio.running or self.audio.enabled)
            self.controller.set_audio_react(want)
            self._sync_audio_switch_from_engine()

        self._ui(flip)

    def _on_audio_level(self, rms: float, vibrate: int, pump: int) -> None:
        # throttle UI updates
        if self._audio_level_idle:
            return
        self._audio_level_idle = True

        def upd():
            self._audio_level_idle = False
            bar = int(min(20, max(0, rms * 40)))
            self.audio_level_lbl.set_text(
                f"Poziom: {'█' * bar}{'░' * (20 - bar)}  → V={vibrate} P={pump}"
            )
            # suwaki podążają za audio
            self._updating_sliders = True
            try:
                self.vib_scale.set_value(vibrate)
                self.pump_scale.set_value(pump)
                self.vib_lbl.set_text(f"Vibrate: {vibrate} / 20")
                self.pump_lbl.set_text(f"Pump: {pump} / 3")
            finally:
                self._updating_sliders = False

        self._ui(upd)

    def _on_game_keys_sw(self, *_args) -> None:
        self.config.hotkeys_game_mode = self.game_keys_sw.get_active()
        self.config.save()
        self._restart_hotkeys()
        self.controller.log(
            "Tryb gry klawiszy: " + ("WŁĄCZONY" if self.config.hotkeys_game_mode else "wyłączony")
        )

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
        info = (
            f"http://{self.config.game_api_host}:{self.config.game_api_port}  "
            f"token: {self.config.game_api_token}"
        )
        self.game_info.set_text(info)
        self.controller.log(f"Game API: {info}")

    def _stop_game_api(self) -> None:
        stop_server(self._game_handle)
        self._game_handle = None
        self.controller.state.game_api_active = False
        self.config.game_api_enabled = False
        self.config.save()
        self.game_info.set_text("Wyłączone")

    def _on_game_sw(self, *_args) -> None:
        if self.game_sw.get_active():
            self._start_game_api()
        else:
            self._stop_game_api()

    def _remote_links(self):
        from max2_controller.remote_links import build_remote_links

        return build_remote_links(self.config)

    def _partner_url(self) -> str:
        from max2_controller.internet_share import build_public_panel_link
        from max2_controller.remote_links import is_public_https_url

        base = self._sl_base_url()
        if is_public_https_url(base):
            return build_public_panel_link(base, self.config.remote_token)
        return self._remote_links().lan

    def _update_remote_link_ui(self) -> None:
        url = self._partner_url()
        if hasattr(self, "partner_url_entry"):
            self.partner_url_entry.set_text(url)
        running = bool(self._remote_handle and self._remote_handle.running)
        tun = getattr(self, "_internet_tunnel", None)
        tun_on = bool(tun and tun.running and getattr(tun, "public_base", None))
        if hasattr(self, "remote_status_lbl"):
            if running and tun_on:
                self.remote_status_lbl.set_text("Online — wyślij adres partnerce")
            elif running:
                self.remote_status_lbl.set_text("Panel włączony — czekam na publiczny adres…")
            else:
                self.remote_status_lbl.set_text("Wyłączone")
        self._update_sl_ui()

    def _sl_base_url(self) -> str:
        """Baza dla LSL: publiczny HTTPS tunelu, dopiero potem LAN (grid go nie widzi)."""
        from max2_controller.internet_share import panel_base_from_link
        from max2_controller.remote_links import pick_sl_base_url

        live = ""
        tun = getattr(self, "_internet_tunnel", None)
        if tun is not None and getattr(tun, "public_base", None):
            live = str(tun.public_base)
        field = ""
        if hasattr(self, "sl_tunnel_entry"):
            field = (self.sl_tunnel_entry.get_text() or "").strip()
        internet = ""
        if hasattr(self, "internet_link_entry"):
            internet = panel_base_from_link(self.internet_link_entry.get_text() or "")
        links = self._remote_links()
        base, _pub = pick_sl_base_url(
            field,
            live,
            self.config.tunnel_public_url or "",
            internet,
            lan_fallback=links.sl_base_lan,
        )
        return base or links.sl_base_lan

    def _update_sl_ui(self) -> None:
        from max2_controller.remote_links import is_public_https_url

        base = self._sl_base_url()
        url = self._partner_url()
        if hasattr(self, "partner_url_entry") and url:
            self.partner_url_entry.set_text(url)
        if hasattr(self, "sl_base_entry"):
            self.sl_base_entry.set_text(base)
        if hasattr(self, "sl_token_entry"):
            self.sl_token_entry.set_text(self.config.remote_token)
        if not hasattr(self, "sl_info"):
            return
        active = bool(
            self.config.remote_enabled
            or self.controller.state.remote_active
            or (self._remote_handle and self._remote_handle.running)
        )
        if not active:
            self.sl_info.set_text(
                "Włącz przełącznik. Partnerka otwiera adres w przeglądarce.\n"
                "W SL: skrypt wklej do HUD, notatkę wrzuć jako lovense.cfg."
            )
        elif is_public_https_url(base):
            self.sl_info.set_text(
                "Adres wyślij partnerce. W SL: skrypt → Contents HUD, "
                "notatka → lovense.cfg (token + URL już w środku)."
            )
        else:
            self.sl_info.set_text(
                "Czekam na publiczny adres internetowy… "
                "Potem skopiuj skrypt i notatkę (LAN nie zadziała z gridu SL)."
            )

    def _alert(self, title: str, detail: str) -> None:
        try:
            dialog = Gtk.AlertDialog()
            dialog.set_message(title)
            dialog.set_detail(detail)
            dialog.set_modal(True)
            dialog.show(self.win)
        except Exception:
            self.controller.log(f"{title}: {detail}")

    def _clipboard_set(self, text: str) -> None:
        display = None
        try:
            if self.win is not None:
                display = self.win.get_display()
        except Exception:
            display = None
        try:
            from gi.repository import Gdk

            if display is None:
                display = Gdk.Display.get_default()
            if display is not None:
                clipboard = display.get_clipboard()
                clipboard.set(text)
                return
        except Exception:
            pass
        # fallback — plik tymczasowy / log
        self.controller.log(f"(kopiuj ręcznie) {text[:120]}…")

    def _copy_sl_base(self) -> None:
        self._clipboard_set(self._sl_base_url())
        self.controller.log("Skopiowano BASE_URL do schowka")

    def _copy_sl_token(self) -> None:
        self._clipboard_set(self.config.remote_token)
        self.controller.log("Skopiowano TOKEN do schowka")

    def _copy_partner_url(self) -> None:
        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        url = self._partner_url()
        if hasattr(self, "partner_url_entry"):
            self.partner_url_entry.set_text(url)
        self._clipboard_set(url)
        self.controller.log(f"Skopiowano adres partnerki: {url}")

    def _copy_sl_script(self) -> None:
        from max2_controller.remote_links import is_public_https_url
        from max2_controller.secondlife import load_lsl_template

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        base = self._sl_base_url()
        if not is_public_https_url(base):
            self.controller.log(
                "Brak publicznego HTTPS — poczekaj aż pojawi się adres, potem skopiuj skrypt ponownie."
            )
        script = load_lsl_template(base_url=base, token=self.config.remote_token)
        self._clipboard_set(script)
        # też zapisz obok configu — wygodne wklejenie z pliku
        try:
            from max2_controller.config import CONFIG_DIR

            out = CONFIG_DIR / "LovenseController.lsl"
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            out.write_text(script, encoding="utf-8")
            self.controller.log(f"Skrypt LSL w schowku + zapis: {out}")
        except Exception:
            self.controller.log("Skrypt LSL skopiowany do schowka")

    def _copy_sl_notecard(self) -> None:
        """Notecard lovense.cfg — wrzuć do obiektu w SL zamiast edytować skrypt."""
        from max2_controller.secondlife import notecard_example

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        text = notecard_example(
            base_url=self._sl_base_url(),
            token=self.config.remote_token,
            panel_url=self._partner_url(),
        )
        self._clipboard_set(text)
        try:
            from max2_controller.config import CONFIG_DIR

            out = CONFIG_DIR / "lovense.cfg"
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            self.controller.log(
                f"Notecard lovense.cfg w schowku + zapis: {out} — w SL utwórz notecard o tej nazwie"
            )
        except Exception:
            self.controller.log("Notecard lovense.cfg skopiowany do schowka")

    def _test_sl_status(self) -> None:
        """Lokalny test /sl/status (bez gridu)."""
        import urllib.error
        import urllib.request
        from urllib.parse import quote

        if not (
            self.config.remote_enabled
            or self.controller.state.remote_active
            or (self._remote_handle and self._remote_handle.running)
        ):
            self.controller.log("Najpierw włącz panel zdalny")
            return
        url = (
            f"http://127.0.0.1:{self.config.remote_port}/sl/status"
            f"?token={quote(self.config.remote_token, safe='')}"
        )

        def work():
            try:
                with urllib.request.urlopen(url, timeout=4) as r:
                    body = r.read().decode("utf-8", errors="replace")[:300]
                    self.controller.log(f"SL test lokalny OK: {body}")
            except urllib.error.HTTPError as e:
                self.controller.log(f"SL test HTTP {e.code}: {e.read()[:200]!r}")
            except Exception as e:
                self.controller.log(f"SL test błąd: {e}")

        self._bg(work)

    def _diagnose_sl_connection(self) -> None:
        """Lokalnie + publiczny tunel z User-Agent jak z Second Life."""
        import urllib.error
        import urllib.request
        from urllib.parse import quote

        from max2_controller.internet_share import probe_sl_http
        from max2_controller.remote_links import is_public_https_url

        if not (self._remote_handle and self._remote_handle.running):
            if not self.remote_sw.get_active():
                self.remote_sw.set_active(True)
        port = int(self.config.remote_port)
        token = self.config.remote_token
        pub = self._sl_base_url()

        def work():
            self.controller.log("=== Diagnostyka połączenia (HUD / przeglądarka) ===")
            for label, url in (
                ("local /health", f"http://127.0.0.1:{port}/health"),
                ("local /sl/ping", f"http://127.0.0.1:{port}/sl/ping"),
                (
                    "local /sl/status",
                    f"http://127.0.0.1:{port}/sl/status?token={quote(token, safe='')}",
                ),
            ):
                try:
                    with urllib.request.urlopen(url, timeout=4) as r:
                        body = r.read().decode("utf-8", errors="replace")[:160]
                        self.controller.log(f"  {label}: HTTP {r.status} {body}")
                except urllib.error.HTTPError as e:
                    self.controller.log(f"  {label}: HTTP {e.code}")
                except Exception as e:
                    self.controller.log(f"  {label}: BŁĄD {e}")
            if is_public_https_url(pub):
                result = probe_sl_http(pub, token)
                self.controller.log(
                    f"  tunel {pub}: reachable={result.get('reachable')} "
                    f"sl_ok={result.get('ok')} blocked={result.get('sl_blocked')} "
                    f"— {result.get('message')}"
                )
                if result.get("sl_blocked"):
                    self._ui(
                        lambda: self._alert(
                            "Cloudflare blokuje Second Life",
                            result.get("message")
                            or "Zmień tryb tunelu na ngrok / Tailscale Funnel / Named.",
                        )
                    )
            else:
                self.controller.log(
                    f"  brak publicznego HTTPS (teraz: {pub or '—'}) — HUD z gridu się nie połączy"
                )

        self._bg(work)

    def _start_remote(self) -> None:
        if self._remote_handle and self._remote_handle.running:
            self._update_remote_link_ui()
            return
        # stary wątek po błędzie — wyczyść
        if self._remote_handle is not None:
            stop_server(self._remote_handle)
            self._remote_handle = None
        self.config.remote_enabled = True
        self.config.save()
        app = create_remote_app(self.controller, self.config)
        self._remote_handle = run_flask_in_thread(
            app, self.config.remote_host, self.config.remote_port, "remote"
        )
        err = getattr(self._remote_handle, "error", None)
        if err or not self._remote_handle.running:
            self.controller.state.remote_active = False
            msg = err or "serwer remote nie wystartował"
            self.controller.log(f"BŁĄD remote: {msg}")
            if hasattr(self, "remote_status_lbl"):
                self.remote_status_lbl.set_text(f"Status: BŁĄD — {msg}")
            # odłącz switch bez pętli
            self._remote_sw_guard = True
            try:
                self.remote_sw.set_active(False)
            finally:
                self._remote_sw_guard = False
            self.config.remote_enabled = False
            self.config.save()
            return
        self.controller.state.remote_active = True
        self._update_remote_link_ui()
        self.controller.log("Zdalne sterowanie włączone")

    def _stop_remote(self) -> None:
        self._stop_internet_share(silent=True)
        stop_server(self._remote_handle)
        self._remote_handle = None
        self.controller.state.remote_active = False
        self.config.remote_enabled = False
        self.config.save()
        self._update_sl_ui()
        if hasattr(self, "partner_url_entry"):
            self.partner_url_entry.set_text("")
        if hasattr(self, "remote_status_lbl"):
            self.remote_status_lbl.set_text("Wyłączone")
        self.controller.log("Zdalne sterowanie wyłączone")

    def _on_remote_sw(self, *_args) -> None:
        if self._remote_sw_guard:
            return
        if self.remote_sw.get_active():
            self.config.tunnel_auto_start = True
            self.config.save()
            self.controller.log("Udostępniam — tylko zaufanej osobie.")
            self._start_remote()
            if self._remote_handle and self._remote_handle.running:
                self._start_internet_share()
        else:
            self._stop_remote()

    def _regen_remote_token(self) -> None:
        import secrets

        self.config.remote_token = secrets.token_urlsafe(24)
        self.config.save()
        was_on = self.remote_sw.get_active()
        if was_on:
            self._stop_remote()
            # set_active(True) gdy już True nie odpala sygnału — wymuś cykl
            self._remote_sw_guard = True
            self.remote_sw.set_active(False)
            self._remote_sw_guard = False
            self.remote_sw.set_active(True)
        # Zawsze przebuduj linki z NOWYM tokenem (panel /r/…, SL, Tailscale)
        self._refresh_token_dependent_links()
        self.controller.log("Nowy link/token — stary przestaje działać (zaktualizowano pola linków)")

    def _refresh_token_dependent_links(self) -> None:
        """Po zmianie remote_token: LAN, internet /r/TOKEN, SL, Tailscale."""
        from max2_controller.internet_share import (
            build_public_panel_link,
            panel_base_from_link,
        )

        try:
            self._update_remote_link_ui()
        except Exception:
            logger.exception("update remote link ui after token")

        # baza tunnelu: config → pole SL → wyłuskaj z aktualnego internet linku
        base = (self.config.tunnel_public_url or "").strip().rstrip("/")
        if not base and hasattr(self, "sl_tunnel_entry"):
            base = (self.sl_tunnel_entry.get_text() or "").strip().rstrip("/")
        if not base and hasattr(self, "internet_link_entry"):
            base = panel_base_from_link(self.internet_link_entry.get_text() or "")

        if base and hasattr(self, "internet_link_entry"):
            panel = build_public_panel_link(base, self.config.remote_token)
            self.internet_link_entry.set_text(panel)
            # trzymaj spójny tunnel w polu SL (bez /r/token)
            if hasattr(self, "sl_tunnel_entry"):
                cur_sl = (self.sl_tunnel_entry.get_text() or "").strip()
                if not cur_sl or panel_base_from_link(cur_sl) != base:
                    # nie nadpisuj ręcznego innego hosta jeśli user ma coś innego
                    if not cur_sl or "trycloudflare.com" in cur_sl or "ngrok" in cur_sl or cur_sl.rstrip("/") == base:
                        self.sl_tunnel_entry.set_text(base)
            try:
                self._update_sl_ui()
            except Exception:
                logger.exception("update sl ui after token")

        try:
            self._refresh_tailscale_link(quiet=True)
        except Exception:
            logger.exception("refresh tailscale after token")

    def _copy_remote_link(self) -> None:
        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        links = self._remote_links()
        link = links.lan
        self.remote_link_entry.set_text(link)
        self._clipboard_set(link)
        self.controller.log(f"Skopiowano link Wi‑Fi: {link}")

    def _open_remote_share(self) -> None:
        """Strona z QR — pokaż partnerce na monitorze / otwórz na telefonie w LAN."""
        import webbrowser
        from urllib.parse import quote

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        links = self._remote_links()
        url = f"http://127.0.0.1:{links.port}/share?token={quote(links.token, safe='')}"
        try:
            webbrowser.open(url)
            self.controller.log(f"QR / share: {url}")
            self.controller.log(f"Partnerka skanuje QR albo dostaje: {links.lan}")
        except Exception as e:
            self.controller.log(f"Nie otwarto share: {e}")

    def _test_remote_health(self) -> None:
        """Sprawdź /health na LAN IP (symulacja dostępu z telefonu)."""
        import urllib.error
        import urllib.request

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        links = self._remote_links()
        url_local = f"http://127.0.0.1:{links.port}/health"
        url_lan = f"http://{links.host_ip}:{links.port}/health"

        def work():
            for label, url in (("local", url_local), ("LAN", url_lan)):
                try:
                    with urllib.request.urlopen(url, timeout=3) as r:
                        body = r.read().decode("utf-8", errors="replace")[:180]
                        self.controller.log(f"Test {label} OK ({url}): {body}")
                except urllib.error.HTTPError as e:
                    self.controller.log(f"Test {label} HTTP {e.code}: {url}")
                except Exception as e:
                    self.controller.log(f"Test {label} BŁĄD: {e} — {url}")
            self.controller.log(
                f"Na telefonie (ta sama Wi‑Fi) otwórz: {url_lan}  → powinno być ok:true"
            )

        self._bg(work)

    def _open_remote_browser(self) -> None:
        import webbrowser

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)
        links = self._remote_links()
        self.remote_link_entry.set_text(links.local)
        try:
            webbrowser.open(links.local)
            self.controller.log(f"Otwieram przeglądarkę: {links.local}")
        except Exception as e:
            self.controller.log(f"Nie udało się otworzyć przeglądarki: {e}")

    # ---- Sesje remote (kto online, kick, uprawnienia do zabawek) ----

    def _build_sessions_page(self, page: Gtk.Box) -> None:
        sec = self._section(page, "Kto jest połączony (panel partnerski)")
        self.sessions_summary_lbl = Gtk.Label(
            label="Brak aktywnych sesji. Gdy partnerka otworzy link i poda imię — pojawi się tutaj.",
            wrap=True,
            xalign=0,
        )
        sec.append(self.sessions_summary_lbl)

        self.sessions_list = Gtk.ListBox()
        self.sessions_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sessions_list.connect("row-selected", self._on_session_row)
        sc = Gtk.ScrolledWindow()
        sc.set_min_content_height(160)
        sc.set_max_content_height(280)
        sc.set_vexpand(True)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_child(self.sessions_list)
        sec.append(sc)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, cb in (
            ("Odśwież", self._refresh_sessions_ui),
            ("Wyrzuć + ban IP", self._kick_selected_session),
            ("Wstrzymaj sterowanie", lambda: self._set_selected_can_control(False)),
            ("Wznów sterowanie", lambda: self._set_selected_can_control(True)),
            ("Wyczyść bany IP", self._clear_remote_bans),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, c=cb: c())
            row.append(b)
        sec.append(row)

        sec2 = self._section(page, "Uprawnienia do zabawek (wybrana sesja)")
        self.session_detail_lbl = Gtk.Label(
            label="Wybierz sesję z listy powyżej.",
            wrap=True,
            xalign=0,
        )
        sec2.append(self.session_detail_lbl)

        self.session_toys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sec2.append(self.session_toys_box)

        perm_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, cb in (
            ("Wszystkie zabawki", lambda: self._set_selected_toys(None)),
            ("Żadna (tylko podgląd)", lambda: self._set_selected_toys([])),
            ("Zastosuj zaznaczenie", self._apply_selected_toy_checks),
        ):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, c=cb: c())
            perm_row.append(b)
        sec2.append(perm_row)

        def_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        def_row.append(Gtk.Label(label="Domyślnie dla NOWYCH sesji:", xalign=0, hexpand=True))
        b_all = Gtk.Button(label="Nowe = wszystkie zabawki")
        b_all.connect(
            "clicked",
            lambda *_: (
                self.controller.remote_sessions.set_default_allowed_toys(None),
                self.controller.log("Nowe sesje: dostęp do wszystkich zabawek"),
                self._refresh_sessions_ui(),
            ),
        )
        def_row.append(b_all)
        sec2.append(def_row)

        hint = Gtk.Label(
            label=(
                "Wyrzuć + ban IP: partnerka nie wejdzie z tego IP przez ~30 min "
                "(nawet po odświeżeniu strony).\n"
                "Wstrzymaj: zostaje na panelu, ale suwaki nie działają.\n"
                "Checkboxy: które z Twoich podłączonych zabawek może sterować."
            ),
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("dim-label")
        sec2.append(hint)

        self._session_toy_checks: dict[str, Gtk.CheckButton] = {}
        self._selected_session_id: str | None = None
        # odświeżaj listę co 2 s
        GLib.timeout_add(2000, self._sessions_tick)

    def _sessions_tick(self) -> bool:
        try:
            # tylko gdy okno żyje
            if self.win is not None:
                self._refresh_sessions_ui()
        except Exception:
            logger.exception("sessions tick")
        return True

    def _refresh_sessions_ui(self) -> None:
        if not hasattr(self, "sessions_list"):
            return
        mgr = self.controller.remote_sessions
        mgr.prune()
        snap = mgr.snapshot()
        online = snap.get("online_count") or 0
        bans = snap.get("ip_bans") or []
        self.sessions_summary_lbl.set_text(
            f"Online: {online}  ·  sesji łącznie: {len(snap.get('sessions') or [])}  ·  "
            f"bany IP: {len(bans)}"
            + (f" ({', '.join(b['ip'] for b in bans[:3])})" if bans else "")
        )

        prev = self._selected_session_id
        self._clear_listbox(self.sessions_list)
        self._session_rows: dict[str, Gtk.ListBoxRow] = {}

        for s in snap.get("sessions") or []:
            sid = s["id"]
            name = s.get("display_name") or "?"
            ip = s.get("remote_addr") or "?"
            idle = s.get("idle_sec", 0)
            online_f = s.get("online")
            kicked = s.get("kicked")
            ctrl = s.get("can_control")
            toys = s.get("allowed_toy_ids")
            if s.get("allow_all_toys"):
                toy_lab = "wszystkie zabawki"
            elif not toys:
                toy_lab = "brak zabawek"
            else:
                toy_lab = f"{len(toys)} zab."
            flags = []
            if kicked:
                flags.append("WYRZUCONY")
            elif not online_f:
                flags.append("idle")
            else:
                flags.append("online")
            if not ctrl:
                flags.append("bez sterowania")
            line = f"{name}  ·  {ip}  ·  {toy_lab}  ·  {', '.join(flags)}  ·  {idle}s"
            row = Gtk.ListBoxRow()
            row.session_id = sid  # type: ignore[attr-defined]
            lab = Gtk.Label(label=line, xalign=0)
            lab.set_margin_top(6)
            lab.set_margin_bottom(6)
            lab.set_margin_start(8)
            lab.set_margin_end(8)
            lab.set_wrap(True)
            row.set_child(lab)
            self.sessions_list.append(row)
            self._session_rows[sid] = row
            if prev and prev == sid:
                self.sessions_list.select_row(row)

        if not (snap.get("sessions") or []):
            self._selected_session_id = None
            self.session_detail_lbl.set_text("Brak sesji — wyślij link partnerce.")
            self._rebuild_session_toy_checks(None)

    def _on_session_row(self, _lb: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self._selected_session_id = None
            return
        sid = getattr(row, "session_id", None)
        self._selected_session_id = sid
        self._update_session_detail()

    def _update_session_detail(self) -> None:
        sid = self._selected_session_id
        if not sid:
            self.session_detail_lbl.set_text("Wybierz sesję z listy.")
            self._rebuild_session_toy_checks(None)
            return
        s = self.controller.remote_sessions.get(sid)
        if not s:
            self.session_detail_lbl.set_text("Sesja już nie istnieje.")
            self._rebuild_session_toy_checks(None)
            return
        d = s.to_dict()
        toys = d.get("allowed_toy_ids")
        if d.get("allow_all_toys"):
            toy_lab = "wszystkie"
        elif not toys:
            toy_lab = "żadna"
        else:
            toy_lab = ", ".join(toys)
        self.session_detail_lbl.set_text(
            f"{d['display_name']}  ·  {d['remote_addr']}\n"
            f"Sterowanie: {'TAK' if d['can_control'] else 'NIE'}  ·  "
            f"zabawki: {toy_lab}\n"
            f"Połączono: {d['connected_for_sec']}s temu  ·  idle {d['idle_sec']}s"
            + ("  ·  WYRZUCONY" if d["kicked"] else "")
        )
        self._rebuild_session_toy_checks(s)

    def _rebuild_session_toy_checks(self, session) -> None:
        # clear
        child = self.session_toys_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.session_toys_box.remove(child)
            child = nxt
        self._session_toy_checks = {}
        if session is None:
            return
        connected = [t for t in self.controller.state.toys if t.connected]
        if not connected:
            self.session_toys_box.append(
                Gtk.Label(label="(brak podłączonych zabawek u Ciebie)", xalign=0)
            )
            return
        allow_all = session.allowed_toy_ids is None
        allow_set = set() if allow_all else {a.upper() for a in (session.allowed_toy_ids or [])}
        for t in connected:
            cb = Gtk.CheckButton(label=t.short_label if hasattr(t, "short_label") else t.display_name)
            cb.set_active(allow_all or t.id.upper() in allow_set)
            self.session_toys_box.append(cb)
            self._session_toy_checks[t.id] = cb

    def _kick_selected_session(self) -> None:
        sid = self._selected_session_id
        if not sid:
            self.controller.log("Wybierz sesję do wyrzucenia")
            return
        s = self.controller.remote_sessions.get(sid)
        name = s.display_name if s else sid[:8]
        ok = self.controller.remote_sessions.kick(sid, ban_ip=True, ban_minutes=30)
        if ok:
            self.controller.log(f"Wyrzucono „{name}” + ban IP ~30 min")
            try:
                self.controller.stop()
            except Exception:
                pass
        self._refresh_sessions_ui()

    def _set_selected_can_control(self, enabled: bool) -> None:
        sid = self._selected_session_id
        if not sid:
            self.controller.log("Wybierz sesję")
            return
        if self.controller.remote_sessions.set_can_control(sid, enabled):
            self.controller.log(
                f"Sesja: sterowanie {'WŁĄCZONE' if enabled else 'WYŁĄCZONE'}"
            )
        self._refresh_sessions_ui()
        self._update_session_detail()

    def _set_selected_toys(self, toy_ids: list[str] | None) -> None:
        sid = self._selected_session_id
        if not sid:
            self.controller.log("Wybierz sesję")
            return
        if self.controller.remote_sessions.set_allowed_toys(sid, toy_ids):
            if toy_ids is None:
                self.controller.log("Sesja: dostęp do WSZYSTKICH zabawek")
            elif not toy_ids:
                self.controller.log("Sesja: brak zabawek (tylko podgląd)")
            else:
                self.controller.log(f"Sesja: zabawki {toy_ids}")
        self._refresh_sessions_ui()
        self._update_session_detail()

    def _apply_selected_toy_checks(self) -> None:
        sid = self._selected_session_id
        if not sid:
            self.controller.log("Wybierz sesję")
            return
        ids = [tid for tid, cb in self._session_toy_checks.items() if cb.get_active()]
        # jeśli zaznaczone wszystkie podłączone → traktuj jako „wszystkie” (None)
        connected = [t.id for t in self.controller.state.toys if t.connected]
        if connected and set(i.upper() for i in ids) >= set(i.upper() for i in connected):
            self._set_selected_toys(None)
        else:
            self._set_selected_toys(ids)

    def _clear_remote_bans(self) -> None:
        self.controller.remote_sessions.clear_bans()
        self.controller.log("Wyczyszczono bany IP remote")
        self._refresh_sessions_ui()

    # ---- Internet share (cloudflared / ngrok / Tailscale) ----

    def _ensure_internet_tunnel(self):
        if self._internet_tunnel is None:
            from max2_controller.internet_share import InternetTunnel

            t = InternetTunnel()
            t.on_log = lambda m: self.controller.log(m)
            t.on_progress = lambda m: self._ui(lambda msg=m: self._on_tunnel_progress(msg))
            t.on_error = lambda m: self._ui(lambda: self._on_tunnel_error(m))
            t.on_url = lambda url, kind: self._ui(lambda: self._on_tunnel_url(url, kind))
            self._internet_tunnel = t
        return self._internet_tunnel

    def _set_internet_busy(self, busy: bool) -> None:
        if hasattr(self, "_btn_internet_share"):
            self._btn_internet_share.set_sensitive(not busy)
            self._btn_internet_share.set_label(
                "⏳  Udostępniam…" if busy else "▶  Udostępnij przez internet"
            )

    def _on_tunnel_progress(self, msg: str) -> None:
        if hasattr(self, "internet_status_lbl"):
            self.internet_status_lbl.set_text(f"Internet: {msg}")

    def _on_tunnel_error(self, msg: str) -> None:
        self._set_internet_busy(False)
        if hasattr(self, "internet_status_lbl"):
            self.internet_status_lbl.set_text(f"Internet: błąd — {msg}")
        self.controller.log(f"Internet: {msg}")

    def _tunnel_mode_str(self) -> str:
        if not hasattr(self, "tunnel_mode_dd"):
            return (self.config.tunnel_mode or "quick").lower()
        idx = int(self.tunnel_mode_dd.get_selected())
        return {0: "quick", 1: "named", 2: "token", 3: "ngrok", 4: "funnel", 5: "ssh"}.get(
            idx, "quick"
        )

    def _on_tunnel_mode_dd(self, *_a) -> None:
        self.config.tunnel_mode = self._tunnel_mode_str()
        self.config.save()

    def _on_tunnel_auto_sw(self, *_a) -> None:
        self.config.tunnel_auto_start = bool(self.tunnel_auto_sw.get_active())
        self.config.save()

    def _save_tunnel_fields(self) -> None:
        if hasattr(self, "tunnel_host_entry"):
            self.config.tunnel_hostname = (self.tunnel_host_entry.get_text() or "").strip()
        if hasattr(self, "tunnel_token_entry"):
            self.config.tunnel_token = (self.tunnel_token_entry.get_text() or "").strip()
        self.config.tunnel_mode = self._tunnel_mode_str()
        try:
            self.config.save()
        except Exception:
            pass

    def _cloudflare_login(self) -> None:
        def work():
            tun = self._ensure_internet_tunnel()
            ok = tun.login_cloudflare(timeout=180)
            if ok:
                self.controller.log("Cloudflare login OK — możesz użyć trybu Named")
            else:
                self.controller.log("Cloudflare login nieudany — zobacz status")

        self.controller.log("Cloudflare login… (przeglądarka)")
        self._bg(work)

    def _on_tunnel_url(self, public_base: str, kind: str) -> None:
        from max2_controller.internet_share import build_public_panel_link

        self._set_internet_busy(False)
        base = public_base.rstrip("/")
        # zapisz stały URL (named/token) albo ostatni quick
        self.config.tunnel_public_url = base
        try:
            self.config.save()
        except Exception:
            pass
        panel = build_public_panel_link(base, self.config.remote_token)
        if hasattr(self, "internet_link_entry"):
            self.internet_link_entry.set_text(panel)
        mode = self._tunnel_mode_str()
        stable = "STAŁY" if mode in ("named", "token") else "tymczasowy"
        if hasattr(self, "internet_status_lbl"):
            self.internet_status_lbl.set_text("Czekam aż adres zacznie działać (DNS)…")
        if hasattr(self, "sl_tunnel_entry"):
            self.sl_tunnel_entry.set_text(base)
            self._update_sl_ui()
        self.controller.log(f"Adres tunelu: {panel} — czekam aż DNS i /health będą żywe…")
        if hasattr(self, "remote_status_lbl"):
            self.remote_status_lbl.set_text("Czekam aż adres zacznie działać (DNS)…")
        token = self.config.remote_token

        def probe():
            from max2_controller.internet_share import probe_sl_http, wait_public_http

            ok, msg = wait_public_http(base, timeout=50.0)
            if ok:
                self.controller.log(f"Adres partnerki gotowy: {panel}")
                self._ui(lambda: self._clipboard_set(panel))
                self._ui(self._update_remote_link_ui)
            else:
                self.controller.log(
                    f"Adres jeszcze nie odpowiada ({msg}). "
                    "Odśwież za chwilę albo wyłącz i włącz udostępnianie."
                )
                self._ui(
                    lambda: self.remote_status_lbl.set_text(
                        "Adres jeszcze nieosiągalny — odśwież za 15 s"
                    )
                    if hasattr(self, "remote_status_lbl")
                    else None
                )
            result = probe_sl_http(base, token)
            if result.get("sl_blocked"):
                self.controller.log(
                    "Cloudflare może blokować HUD SL — przeglądarka partnerki powinna działać."
                )
            elif result.get("ok"):
                self.controller.log("Tunel odpowiada także z User-Agent Second Life")
            elif result.get("message"):
                self.controller.log(f"Tunel probe: {result.get('message')}")

        self._bg(probe)

    def _start_internet_share(self) -> None:
        """Panel ON + cloudflared (quick/named/token) + link w schowku."""
        self._save_tunnel_fields()
        self._set_internet_busy(True)
        mode = self._tunnel_mode_str()
        if hasattr(self, "internet_status_lbl"):
            self.internet_status_lbl.set_text(f"Internet: start ({mode})…")
        if mode == "quick" and hasattr(self, "internet_link_entry"):
            self.internet_link_entry.set_text("")

        if not self.remote_sw.get_active():
            self.remote_sw.set_active(True)

        def work():
            import time as _time

            for _ in range(40):
                if self._remote_handle and self._remote_handle.running:
                    break
                _time.sleep(0.15)
            else:
                self._ui(
                    lambda: self._on_tunnel_error(
                        "Panel web nie wystartował (port 8787). Sprawdź Log."
                    )
                )
                return

            tun = self._ensure_internet_tunnel()
            if tun.running and tun.public_base:
                self._ui(lambda: self._on_tunnel_url(tun.public_base, tun.kind or "tunnel"))
                return

            port = int(self.config.remote_port)
            ok = tun.start(
                port,
                prefer="auto",
                auto_install=True,
                mode=mode,
                tunnel_name=self.config.tunnel_name or "lovense-controller",
                hostname=self.config.tunnel_hostname or "",
                token=self.config.tunnel_token or "",
                known_public_url=self.config.tunnel_public_url
                or (
                    f"https://{self.config.tunnel_hostname}"
                    if self.config.tunnel_hostname
                    else ""
                ),
            )
            if not ok:
                self._ui(lambda: self._set_internet_busy(False))
                return
            # named/token: URL od razu; quick: czekaj na trycloudflare
            wait_s = 45.0 if mode in ("quick", "ngrok", "ssh") else 8.0
            url = tun.wait_for_url(timeout=wait_s)
            if not url and mode in ("quick", "ngrok", "ssh"):
                self._ui(
                    lambda: self._on_tunnel_error(
                        "Timeout — brak publicznego URL. Sprawdź internet i Log."
                    )
                )
            elif url and mode != "quick":
                # already emitted via on_url often; ensure UI
                self._ui(lambda: self._on_tunnel_url(url, tun.kind or mode))

        self._bg(work)

    def _stop_internet_share(self, silent: bool = False) -> None:
        self._set_internet_busy(False)
        tun = self._internet_tunnel
        if tun is not None:
            try:
                tun.stop()
            except Exception:
                logger.exception("stop tunnel")
        if hasattr(self, "internet_link_entry"):
            self.internet_link_entry.set_text("")
        if hasattr(self, "internet_status_lbl") and not silent:
            self.internet_status_lbl.set_text("Internet: tunnel zatrzymany")
        elif hasattr(self, "internet_status_lbl") and silent:
            self.internet_status_lbl.set_text("Internet: wyłączone")
        if hasattr(self, "sl_tunnel_entry") and not silent:
            # nie czyść ręcznie wpisanego tunnelu usera jeśli nie nasz — tylko gdy pusty lub trycloudflare
            try:
                cur = (self.sl_tunnel_entry.get_text() or "").strip()
                if "trycloudflare.com" in cur or "ngrok" in cur or "lhr.life" in cur:
                    self.sl_tunnel_entry.set_text("")
                    self._update_sl_ui()
            except Exception:
                pass
        # quick URL umiera po restarcie — nie pokazuj go jako żywego
        pub = (self.config.tunnel_public_url or "")
        if "trycloudflare.com" in pub or "lhr.life" in pub:
            self.config.tunnel_public_url = ""
            try:
                self.config.save()
            except Exception:
                pass
        if not silent:
            self.controller.log("Tunnel internetowy zatrzymany")

    def _copy_internet_link(self) -> None:
        link = ""
        if hasattr(self, "internet_link_entry"):
            link = (self.internet_link_entry.get_text() or "").strip()
        if not link:
            tun = self._internet_tunnel
            if tun and tun.public_base:
                from max2_controller.internet_share import build_public_panel_link

                link = build_public_panel_link(tun.public_base, self.config.remote_token)
                self.internet_link_entry.set_text(link)
        if not link:
            self.controller.log("Brak linku internetowego — najpierw „Udostępnij przez internet”")
            return
        self._clipboard_set(link)
        self.controller.log(f"Skopiowano link internetowy: {link}")

    def _refresh_tailscale_link_quiet(self) -> bool:
        self._refresh_tailscale_link(quiet=True)
        return False

    def _refresh_tailscale_link(self, quiet: bool = False) -> None:
        from max2_controller.internet_share import (
            build_tailscale_panel_link,
            tailscale_status_summary,
        )

        summary = tailscale_status_summary()
        link = build_tailscale_panel_link(self.config.remote_port, self.config.remote_token)
        if hasattr(self, "tailscale_link_entry"):
            self.tailscale_link_entry.set_text(link or "")
        if link:
            if not quiet:
                self.controller.log(f"Tailscale OK: {summary}")
                self.controller.log(f"Link Tailscale (ta sama tailnet u partnerki): {link}")
            if hasattr(self, "internet_status_lbl") and not (
                self._internet_tunnel and self._internet_tunnel.running
            ):
                # nie nadpisuj statusu cloudflare jeśli tunnel leci
                cur = ""
                try:
                    cur = self.internet_status_lbl.get_text() or ""
                except Exception:
                    pass
                if "ONLINE" not in cur:
                    self.internet_status_lbl.set_text(
                        f"Internet: {summary} — możesz wysłać link Tailscale (oba urządzenia w sieci Tailscale)"
                    )
        else:
            if not quiet:
                self.controller.log(summary)
                self.controller.log(
                    "Brak IP Tailscale. U Ciebie: tailscale up · u partnerki: zainstaluj Tailscale i to samo konto / zaproszenie."
                )
            if hasattr(self, "internet_status_lbl") and not (
                self._internet_tunnel and getattr(self._internet_tunnel, "public_base", None)
            ):
                self.internet_status_lbl.set_text(f"Internet: {summary}")

    def _on_log(self, msg: str) -> None:
        def append():
            end = self.log_buf.get_end_iter()
            self.log_buf.insert(end, msg + "\n")
            # scroll
            mark = self.log_buf.get_insert()
            self.log_view.scroll_mark_onscreen(mark)

        self._ui(append)

    def _schedule_refresh_state(self) -> None:
        self._ui(self._refresh_state_labels)

    def _refresh_state_labels(self) -> None:
        st = self.controller.state
        backend = "BLE" if st.backend_name == "ble" else "Connect/Remote"
        n = getattr(st, "connected_count", 0) or (1 if st.connected else 0)
        if st.connected:
            mode = "wszystkie" if st.control_all else "wybrana"
            status = f"Status: {n} połączonych ({backend}) · sterowanie: {mode}"
        else:
            status = f"Status: brak połączenia ({backend}) — Skanuj / Połącz (można dodać 2+)"
        self.status_lbl.set_text(status)
        if getattr(self, "_dock_status", None) is not None:
            short = f"{n} online · {backend}" if st.connected else f"offline · {backend}"
            try:
                rs = self.controller.remote_sessions.count_online()
            except Exception:
                rs = 0
            remote_bit = f"  ·  remote:{rs}" if rs else ""
            audio_bit = "  ·  🎧" if self.controller.audio_react_enabled() else ""
            self._dock_status.set_text(f"{short}{remote_bit}{audio_bit}  ·  V={st.vibrate}  P={st.pump}")
        # synchronizacja switcha audio (remote / hotkey / API)
        try:
            self._sync_audio_switch_from_engine()
        except Exception:
            pass
        # czułość / gain z remote
        try:
            if hasattr(self, "sens_scale") and hasattr(self, "sens_lbl"):
                s = float(self.config.audio_sensitivity)
                if abs(self.sens_scale.get_value() - s) > 0.05:
                    self.sens_scale.set_value(s)
                    self.sens_lbl.set_text(f"Czułość: {s:.1f}")
            if hasattr(self, "gain_scale") and hasattr(self, "gain_lbl"):
                g = float(self.config.audio_gain)
                if abs(self.gain_scale.get_value() - g) > 0.05:
                    self.gain_scale.set_value(g)
                    self.gain_lbl.set_text(f"Wzmocnienie: {g:.1f}")
        except Exception:
            pass
        toy = self.controller.selected_toy()
        if toy and toy.battery is not None:
            self.battery_lbl.set_text(f"Bateria: {toy.battery}%")
        elif toy:
            self.battery_lbl.set_text("Bateria: ? (kliknij Bateria)")
        else:
            self.battery_lbl.set_text("Bateria: —")

        self._updating_sliders = True
        try:
            if int(round(self.vib_scale.get_value())) != st.vibrate:
                self.vib_scale.set_value(st.vibrate)
            if int(round(self.pump_scale.get_value())) != st.pump:
                self.pump_scale.set_value(st.pump)
            if hasattr(self, "auto_mode_lbl"):
                mode = getattr(st, "auto_mode", "none") or "none"
                labels = {
                    "none": "wyłączony",
                    "oscillate": "oscylacja",
                    "random": "losowy",
                    "ramp": "ramp",
                }
                self.auto_mode_lbl.set_text(f"Tryb: {labels.get(mode, mode)}")
            self.vib_lbl.set_text(f"Vibrate: {st.vibrate} / 20")
            toy = self.controller.selected_toy()
            mx = toy.secondary_max() if toy and toy.secondary != "none" else 3
            label = toy.secondary_label() if toy else "Druga funkcja"
            self.pump_lbl.set_text(f"{label}: {st.pump} / {mx or 3}")
            if toy:
                self._update_secondary_slider()
        finally:
            self._updating_sliders = False

    def _on_close(self, *_args) -> bool:
        try:
            self.audio.stop(send_zero=True)
        except Exception:
            pass
        if self.hotkeys:
            self.hotkeys.stop()
        try:
            self._stop_internet_share(silent=True)
        except Exception:
            pass
        self._stop_game_api()
        self._stop_remote()
        try:
            self.config.save()
            self.controller.shutdown()
        except Exception:
            pass
        self.quit()
        return False


def run_gtk(
    controller: "Max2Controller",
    config: "AppConfig",
    hotkeys: "HotkeyManager | None" = None,
) -> None:
    if HAS_ADW:
        Adw.init()
    app = Max2GtkApp(controller, config, hotkeys=hotkeys)
    app.run(None)
