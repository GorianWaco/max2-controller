"""Czego brakuje do działania i jak to doinstalować.

Dwie drogi:
- start programu (okno albo pytanie w terminalu)
- ``python -m max2_controller.setup_check --apply-system`` z install.sh
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]*$")

# Moduły, bez których okno, BLE albo panel się nie podniosą.
_PY_REQUIRED = ("flask", "werkzeug", "requests", "urllib3", "bleak", "numpy")
_PY_OPTIONAL = ("pynput",)
_PIP_SPEC = (
    "requests>=2.31.0",
    "flask>=3.0.0",
    "werkzeug",
    "pynput>=1.7.6",
    "urllib3>=2.0.0",
    "bleak>=0.22.0",
    "numpy>=1.26.0",
    "sounddevice>=0.4.6",
)

# id pozycji → rodzina dystrybucji → paczki. Puste = nic w menedżerze paczek (pip albo systemctl).
_TABLES: dict[str, dict[str, tuple[str, ...]]] = {
    "gtk": {
        "pacman": ("python-gobject", "gtk4", "python-cairo", "gobject-introspection"),
        "apt": ("python3-gi", "python3-gi-cairo", "gir1.2-gtk-4.0"),
        "dnf": ("python3-gobject", "gtk4", "python3-cairo", "gobject-introspection"),
    },
    "adw": {
        "pacman": ("libadwaita",),
        "apt": ("gir1.2-adw-1",),
        "dnf": ("libadwaita",),
    },
    "python": {"pacman": (), "apt": (), "dnf": ()},
    "bluez": {
        "pacman": ("bluez", "bluez-utils"),
        "apt": ("bluez",),
        "dnf": ("bluez",),
    },
    "bluetooth-service": {"pacman": (), "apt": (), "dnf": ()},
    "pw-dump": {
        "pacman": ("pipewire",),
        "apt": ("pipewire", "pipewire-bin"),
        "dnf": ("pipewire", "pipewire-utils"),
    },
    "pw-record": {
        "pacman": ("pipewire-audio",),
        "apt": ("pipewire-bin",),
        "dnf": ("pipewire-utils",),
    },
    "pactl": {
        "pacman": ("libpulse", "pipewire-pulse"),
        "apt": ("pulseaudio-utils", "pipewire-pulse"),
        "dnf": ("pulseaudio-utils", "pipewire-pulseaudio"),
    },
    "gst": {
        "pacman": ("gstreamer", "gst-plugins-base", "gst-plugins-good"),
        "apt": (
            "gstreamer1.0-tools",
            "gstreamer1.0-plugins-base",
            "gstreamer1.0-plugins-good",
        ),
        "dnf": ("gstreamer1", "gstreamer1-plugins-base", "gstreamer1-plugins-good"),
    },
    "pulsesrc": {
        "pacman": ("gst-plugins-good",),
        "apt": ("gstreamer1.0-plugins-good",),
        "dnf": ("gstreamer1-plugins-good",),
    },
    "ssh": {
        "pacman": ("openssh",),
        "apt": ("openssh-client",),
        "dnf": ("openssh-clients",),
    },
}


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    detail: str
    required: bool
    packages: tuple[str, ...] = ()


@dataclass
class Probe:
    """Wyniki odczytu systemu. Testy podają własne, start — live()."""

    os_release: str
    which: Callable[[str], bool]
    can_import: Callable[[str], bool]
    gtk_ok: bool
    adw_ok: bool
    pulsesrc_ok: bool
    bluetooth: str  # active | inactive | unknown
    has_pacman: bool
    has_apt: bool
    has_dnf: bool
    flatpak: bool
    python_exe: str
    requirements: str | None

    @staticmethod
    def live() -> Probe:
        os_release = ""
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8")
        except OSError:
            pass
        root = _repo_root()
        req = root / "requirements.txt" if root else None
        gtk_ok, adw_ok = _gtk_adw()
        return Probe(
            os_release=os_release,
            which=lambda cmd: shutil.which(cmd) is not None,
            can_import=_can_import,
            gtk_ok=gtk_ok,
            adw_ok=adw_ok,
            pulsesrc_ok=_pulsesrc_ok(),
            bluetooth=_bluetooth_state(),
            has_pacman=shutil.which("pacman") is not None,
            has_apt=shutil.which("apt-get") is not None,
            has_dnf=shutil.which("dnf") is not None,
            flatpak=in_flatpak(),
            python_exe=sys.executable,
            requirements=str(req) if req and req.is_file() else None,
        )


@dataclass
class Report:
    distro: str
    family: str  # pacman | apt | dnf | unknown
    items: list[Item] = field(default_factory=list)
    python_exe: str = ""
    requirements: str | None = None

    @property
    def should_prompt(self) -> bool:
        return any(item.required for item in self.items)

    def needs_pip(self, *, include_python: bool = True) -> bool:
        if not include_python:
            return False
        return any(item.id == "python" for item in self.items)

    def enable_bluetooth(self, *, include_python: bool = True) -> bool:
        del include_python
        return any(item.id in {"bluez", "bluetooth-service"} for item in self.items)


def in_flatpak() -> bool:
    return Path("/.flatpak-info").is_file() or bool(os.environ.get("FLATPAK_ID"))


def _repo_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    if (root / "requirements.txt").is_file() and (root / "src" / "max2_controller").is_dir():
        return root
    return None


def _can_import(name: str) -> bool:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        return False
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _gtk_adw() -> tuple[bool, bool]:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
    except Exception:
        return False, False
    try:
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw  # noqa: F401
        return True, True
    except Exception:
        return True, False


def _pulsesrc_ok() -> bool:
    if shutil.which("gst-inspect-1.0") is None:
        return False
    try:
        proc = subprocess.run(
            ["gst-inspect-1.0", "pulsesrc"],
            capture_output=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _bluetooth_state() -> str:
    if shutil.which("systemctl") is None:
        return "unknown"
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "bluetooth.service"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    state = (proc.stdout or "").strip()
    if state == "active":
        return "active"
    if state in {"inactive", "failed", "deactivating"}:
        return "inactive"
    return "unknown"


def parse_os_release(text: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key] = value.strip().strip('"').strip("'")
    return info


def detect_family(probe: Probe) -> str:
    info = parse_os_release(probe.os_release)
    ident = f"{info.get('ID', '')} {info.get('ID_LIKE', '')}".lower()
    if info.get("ID") in {"cachyos", "arch", "archlinux"} or "arch" in ident.split():
        return "pacman"
    if any(name in ident.split() for name in ("debian", "ubuntu", "linuxmint", "pop")):
        return "apt"
    if any(name in ident.split() for name in ("fedora", "rhel", "centos", "nobara")):
        return "dnf"
    if probe.has_pacman:
        return "pacman"
    if probe.has_apt:
        return "apt"
    if probe.has_dnf:
        return "dnf"
    return "unknown"


def distro_label(probe: Probe) -> str:
    info = parse_os_release(probe.os_release)
    if info.get("ID") == "cachyos":
        return "CachyOS"
    return info.get("PRETTY_NAME") or info.get("NAME") or "Linux"


def _pkgs(family: str, table: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    if family in table:
        return table[family]
    return table.get("pacman", ())


def _table(item_id: str, family: str) -> tuple[str, ...]:
    return _pkgs(family, _TABLES[item_id])


def _validate_packages(packages: tuple[str, ...]) -> tuple[str, ...]:
    clean: list[str] = []
    for name in packages:
        if not _PKG_RE.fullmatch(name):
            raise ValueError(f"zła nazwa pakietu: {name}")
        if name not in clean:
            clean.append(name)
    return tuple(clean)


def inspect_system(probe: Probe | None = None) -> Report:
    probe = probe or Probe.live()
    family = detect_family(probe)
    report = Report(
        distro=distro_label(probe),
        family=family,
        python_exe=probe.python_exe,
        requirements=probe.requirements,
    )
    if probe.flatpak:
        return report

    def add(item: Item) -> None:
        item = Item(
            id=item.id,
            title=item.title,
            detail=item.detail,
            required=item.required,
            packages=_validate_packages(item.packages),
        )
        report.items.append(item)

    if not probe.gtk_ok:
        add(
            Item(
                "gtk",
                "Okno programu",
                "PyGObject i GTK 4. venv musi widzieć pakiety systemowe "
                "(python3 -m venv --system-site-packages).",
                True,
                _table("gtk", family),
            )
        )
    if not probe.adw_ok:
        add(
            Item(
                "adw",
                "Wygląd libadwaita",
                "Program ruszy też bez tego, na zwykłym GTK.",
                False,
                _table("adw", family),
            )
        )

    missing_py = [name for name in _PY_REQUIRED if not probe.can_import(name)]
    missing_opt = [name for name in _PY_OPTIONAL if not probe.can_import(name)]
    if missing_py or missing_opt:
        names = missing_py + missing_opt
        add(
            Item(
                "python",
                "Biblioteki Pythona",
                "Brakuje: " + ", ".join(names) + ".",
                bool(missing_py),
                (),
            )
        )

    if not probe.which("bluetoothctl"):
        add(
            Item(
                "bluez",
                "Bluetooth",
                "Skan zabawki Lovense (bluez).",
                True,
                _table("bluez", family),
            )
        )
    elif probe.bluetooth == "inactive":
        add(
            Item(
                "bluetooth-service",
                "Usługa Bluetooth",
                "BlueZ jest, ale bluetooth.service nie działa. Włączę ją.",
                True,
                (),
            )
        )

    if not probe.which("pw-dump"):
        add(
            Item(
                "pw-dump",
                "Lista urządzeń audio",
                "Odczyt wyjść i wejść (PipeWire).",
                True,
                _table("pw-dump", family),
            )
        )
    if not probe.which("pw-record"):
        add(
            Item(
                "pw-record",
                "Jedna aplikacja",
                "Nasłuch dźwięku wybranego programu (pw-record).",
                True,
                _table("pw-record", family),
            )
        )
    if not probe.which("pactl"):
        add(
            Item(
                "pactl",
                "Zapasowa lista audio",
                "Gdy pw-dump nie odpowie, program czyta urządzenia przez pactl.",
                True,
                _table("pactl", family),
            )
        )
    if not probe.which("gst-launch-1.0"):
        add(
            Item(
                "gst",
                "Odczyt dźwięku",
                "GStreamer łapie to, co gra na głośnikach.",
                True,
                _table("gst", family),
            )
        )
    elif not probe.pulsesrc_ok:
        add(
            Item(
                "pulsesrc",
                "Wtyczka dźwięku pulsesrc",
                "Bez niej reakcja na głośniki nie startuje.",
                True,
                _table("pulsesrc", family),
            )
        )
    if not probe.which("ssh"):
        add(
            Item(
                "ssh",
                "Tunel SSH",
                "Tryb localhost.run dla panelu w przeglądarce. Cloudflare Quick działa bez tego.",
                False,
                _table("ssh", family),
            )
        )
    return report


def _unique(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def packages_for(report: Report, *, include_python: bool = True) -> list[str]:
    names: list[str] = []
    for item in report.items:
        if item.id == "python" and not include_python:
            continue
        names.extend(item.packages)
    return _unique(names)


def root_script(report: Report, *, include_python: bool = True) -> str:
    """Skrypt dla roota. Pusty, gdy nie ma czego instalować w systemie."""
    pkgs = packages_for(report, include_python=include_python)
    enable_bt = report.enable_bluetooth()
    lines: list[str] = []
    if pkgs:
        if report.family == "pacman":
            lines.append("pacman -S --needed --noconfirm " + " ".join(pkgs))
        elif report.family == "apt":
            lines.append("export DEBIAN_FRONTEND=noninteractive")
            lines.append("apt-get update -y")
            lines.append("apt-get install -y " + " ".join(pkgs))
        elif report.family == "dnf":
            lines.append("dnf install -y " + " ".join(pkgs))
    if enable_bt and report.family in {"pacman", "apt", "dnf"}:
        lines.append("systemctl daemon-reload || true")
        lines.append("systemctl enable --now bluetooth.service || true")
    if not lines:
        return ""
    return "set -euo pipefail\n" + "\n".join(lines) + "\n"


def _packages_as(report: Report, family: str, *, include_python: bool) -> list[str]:
    """Nazwy paczek tej listy braków, gdyby system był z podanej rodziny."""
    names: list[str] = []
    for item in report.items:
        if item.id == "python" and not include_python:
            continue
        names.extend(_TABLES.get(item.id, {}).get(family, ()))
    return _unique(names)


def user_commands(report: Report, *, include_python: bool = True) -> str:
    """Komendy do wklejenia, gdy program nie może zapytać o hasło sam."""
    lines: list[str] = []
    if report.family == "unknown":
        for family, prefix in (
            ("pacman", "# CachyOS / Arch:\nsudo pacman -S --needed --noconfirm "),
            ("apt", "# Debian / Ubuntu:\nsudo apt-get install -y "),
            ("dnf", "# Fedora:\nsudo dnf install -y "),
        ):
            names = _packages_as(report, family, include_python=include_python)
            if names:
                lines.append(prefix + " ".join(names))
    else:
        pkgs = packages_for(report, include_python=include_python)
        if pkgs and report.family == "pacman":
            lines.append("sudo pacman -S --needed --noconfirm " + " ".join(pkgs))
        elif pkgs and report.family == "apt":
            lines.append("sudo apt-get update && sudo apt-get install -y " + " ".join(pkgs))
        elif pkgs and report.family == "dnf":
            lines.append("sudo dnf install -y " + " ".join(pkgs))
    if report.enable_bluetooth():
        lines.append("sudo systemctl enable --now bluetooth.service")
    if report.needs_pip(include_python=include_python):
        py = report.python_exe or "python3"
        if report.requirements:
            lines.append(f"{py} -m pip install -r {report.requirements}")
        else:
            lines.append(f"{py} -m pip install " + " ".join(_PIP_SPEC))
    return "\n".join(lines)


def format_report(report: Report) -> str:
    if not report.items:
        return f"{report.distro}: wszystko potrzebne jest na miejscu."
    lines = [f"{report.distro}: brakuje tego, żeby program działał w całości.", ""]
    for item in report.items:
        kind = "potrzebne" if item.required else "opcjonalne"
        lines.append(f"• {item.title} ({kind})")
        lines.append(f"  {item.detail}")
    return "\n".join(lines)


def dialog_lines(report: Report) -> list[str]:
    """Tekst okna: nagłówek, zdanie, potem pozycje."""
    head = f"Na {report.distro} mogę to doinstalować. System zapyta o hasło raz."
    rows = [head]
    for item in report.items:
        mark = "" if item.required else " (opcjonalne)"
        rows.append(f"{item.title}{mark}")
        rows.append(item.detail)
    return rows


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return 1, str(exc)
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, text


def _tail(text: str, limit: int = 1500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def run_root(script: str, *, prefer_pkexec: bool) -> tuple[int, str]:
    if not script.strip():
        return 0, ""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return _run(["bash", "-c", script])
    if prefer_pkexec and shutil.which("pkexec"):
        code, out = _run(["pkexec", "bash", "-c", script])
        if code == 0:
            return 0, out
        if code in {126, 127}:
            return code, "Anulowano hasło.\n" + _tail(out)
        if shutil.which("sudo"):
            code2, out2 = _run(["sudo", "bash", "-c", script])
            return code2, _tail(out + "\n" + out2)
        return code, _tail(out)
    if shutil.which("sudo"):
        return _run(["sudo", "bash", "-c", script])
    return 1, "Nie ma pkexec ani sudo."


def _python_is_venv(python_exe: str) -> bool:
    if python_exe == sys.executable:
        return sys.prefix != sys.base_prefix
    proc = subprocess.run(
        [python_exe, "-c", "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def pip_install(report: Report) -> tuple[int, str]:
    py = report.python_exe or sys.executable
    code, out = _run([py, "-m", "pip", "--version"])
    if code != 0:
        code, out = _run([py, "-m", "ensurepip", "--upgrade"])
        if code != 0:
            return code, "Brak pip. " + _tail(out)
    cmd = [py, "-m", "pip", "install"]
    user_site = not _python_is_venv(py)
    if user_site:
        cmd.append("--user")
    if report.requirements:
        cmd.extend(["-r", report.requirements])
    else:
        cmd.extend(_PIP_SPEC)
    code, out = _run(cmd)
    if code == 0 and user_site and py == sys.executable:
        try:
            import site

            site.addsitedir(site.getusersitepackages())
        except Exception:
            pass
    return code, _tail(out)


def apply(report: Report, *, prefer_pkexec: bool, include_python: bool = True) -> tuple[int, str]:
    chunks: list[str] = []
    pkgs = packages_for(report, include_python=include_python)
    if report.family == "unknown" and (pkgs or report.enable_bluetooth()):
        text = "Nie rozpoznaję dystrybucji. Wklej komendę pasującą do systemu.\n"
        text += user_commands(report, include_python=include_python)
        return 1, text.strip()
    script = root_script(report, include_python=include_python)
    if script:
        code, out = run_root(script, prefer_pkexec=prefer_pkexec)
        if out:
            chunks.append(out)
        if code != 0:
            manual = user_commands(report, include_python=include_python)
            if manual:
                chunks.append(manual)
            return code, "\n".join(chunks).strip()
    if report.needs_pip(include_python=include_python):
        code, out = pip_install(report)
        if out:
            chunks.append(out)
        if code != 0:
            return code, "\n".join(chunks).strip()
    return 0, "\n".join(chunks).strip()


def _gtk_ready() -> bool:
    ok, _adw = _gtk_adw()
    if not ok:
        return False
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        checked = Gtk.init_check()
        if isinstance(checked, tuple):
            return bool(checked[0])
        return bool(checked)
    except Exception:
        return False


def _info_window(text: str) -> None:
    if not _gtk_ready():
        print(text)
        return
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    done = {"flag": False}
    win = Gtk.Window(title="Lovense Controller")
    win.set_default_size(420, 160)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    label = Gtk.Label(label=text)
    label.set_wrap(True)
    label.set_xalign(0)
    box.append(label)
    button = Gtk.Button(label="OK")
    button.add_css_class("suggested-action")
    box.append(button)
    win.set_child(box)
    loop = GLib.MainLoop()

    def close(*_args: object) -> bool:
        if not done["flag"]:
            done["flag"] = True
            loop.quit()
        return False

    button.connect("clicked", close)
    win.connect("close-request", close)
    win.present()
    loop.run()
    win.destroy()


def ask_graphical(report: Report, *, include_python: bool = True) -> str:
    """Okno: Zainstaluj albo Pomiń. Zwraca installed | skip."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    choice = {"value": "skip", "done": False}
    installing = {"on": False}
    win = Gtk.Window(title="Lovense Controller")
    win.set_default_size(560, 460)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_margin_top(16)
    root.set_margin_bottom(16)
    root.set_margin_start(16)
    root.set_margin_end(16)
    title = Gtk.Label(label="Brakuje rzeczy do działania")
    title.add_css_class("title-2")
    title.set_xalign(0)
    root.append(title)

    lines = dialog_lines(report)
    intro = Gtk.Label(label=lines[0])
    intro.set_wrap(True)
    intro.set_xalign(0)
    root.append(intro)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.set_min_content_height(180)
    listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    index = 1
    while index < len(lines):
        name = Gtk.Label(label=lines[index])
        name.set_xalign(0)
        name.add_css_class("heading")
        listing.append(name)
        if index + 1 < len(lines):
            detail = Gtk.Label(label=lines[index + 1])
            detail.set_wrap(True)
            detail.set_xalign(0)
            listing.append(detail)
        index += 2
    scroll.set_child(listing)
    root.append(scroll)

    status = Gtk.Label(label="")
    status.set_wrap(True)
    status.set_xalign(0)
    status.set_selectable(True)
    root.append(status)

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    buttons.set_halign(Gtk.Align.END)
    skip_btn = Gtk.Button(label="Pomiń")
    install_btn = Gtk.Button(label="Zainstaluj")
    install_btn.add_css_class("suggested-action")
    buttons.append(skip_btn)
    buttons.append(install_btn)
    root.append(buttons)
    win.set_child(root)

    loop = GLib.MainLoop()

    def finish(value: str) -> None:
        if choice["done"]:
            return
        choice["done"] = True
        choice["value"] = value
        loop.quit()

    def on_close(*_args: object) -> bool:
        if installing["on"]:
            return True
        finish("skip")
        return False

    def on_skip(*_args: object) -> None:
        if installing["on"]:
            return
        finish("skip")

    def on_install(*_args: object) -> None:
        if installing["on"]:
            return
        installing["on"] = True
        install_btn.set_sensitive(False)
        skip_btn.set_sensitive(False)
        status.set_text("Instaluję… system zapyta o hasło.")

        def work() -> None:
            code, out = apply(report, prefer_pkexec=True, include_python=include_python)

            def done() -> bool:
                installing["on"] = False
                if code == 0:
                    finish("installed")
                    return False
                status.set_text(
                    "Nie udało się dokończyć instalacji.\n" + (out or user_commands(report))
                )
                install_btn.set_sensitive(True)
                skip_btn.set_sensitive(True)
                return False

            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()

    skip_btn.connect("clicked", on_skip)
    install_btn.connect("clicked", on_install)
    win.connect("close-request", on_close)
    win.present()
    loop.run()
    win.destroy()
    return choice["value"]


def ask_terminal(report: Report, *, include_python: bool = True) -> str:
    print(format_report(report))
    print()
    manual = user_commands(report, include_python=include_python)
    if manual:
        print("Albo wklej to w terminalu:")
        print(manual)
        print()
    if not sys.stdin.isatty():
        print("Brak terminala — pomijam instalację.")
        return "skip"
    try:
        answer = input("Zainstalować teraz? [T/n] ").strip().lower()
    except EOFError:
        return "skip"
    if answer not in {"", "t", "ta", "tak", "y", "yes"}:
        return "skip"
    code, out = apply(report, prefer_pkexec=False, include_python=include_python)
    if out:
        print(out)
    if code == 0:
        return "installed"
    print("Instalacja nie doszła do końca.")
    return "skip"


def ask(report: Report, *, include_python: bool = True) -> str:
    if _gtk_ready():
        try:
            return ask_graphical(report, include_python=include_python)
        except Exception as exc:
            print(f"Okno instalacji nie wstało ({exc}). Pytam w terminalu.")
    return ask_terminal(report, include_python=include_python)


def ensure_ready(*, force: bool = False) -> str:
    """``ok`` — leć dalej. ``exit`` — brak GTK albo Pythona, start nic nie da."""
    if in_flatpak():
        return "ok"
    report = inspect_system()
    if force and not report.items:
        _info_window(f"{report.distro}: wszystko potrzebne jest na miejscu.")
        return "ok"
    if not report.should_prompt and not (force and report.items):
        return "ok"
    choice = ask(report)
    if choice != "installed":
        return "ok"
    again = inspect_system()
    if any(item.id in {"gtk", "python"} and item.required for item in again.items):
        print(format_report(again))
        print()
        print(user_commands(again))
        print("Uruchom program jeszcze raz, gdy te paczki będą na miejscu.")
        return "exit"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sprawdź zależności Lovense Controller i doinstaluj braki."
    )
    parser.add_argument(
        "--apply-system",
        action="store_true",
        help="Doinstaluj pakiety systemowe (sudo), bez pip",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Doinstaluj pakiety systemowe i biblioteki Pythona",
    )
    parser.add_argument(
        "--print-cmd",
        action="store_true",
        help="Wypisz komendy, nic nie instaluj",
    )
    args = parser.parse_args(argv)
    if in_flatpak():
        print("Flatpak ma zależności w paczce.")
        return 0
    report = inspect_system()
    include_python = bool(args.apply) and not args.apply_system
    if not args.apply and not args.apply_system:
        print(format_report(report))
        manual = user_commands(report)
        if manual:
            print()
            print(manual)
        return 1 if report.should_prompt else 0
    if args.print_cmd:
        print(format_report(report))
        manual = user_commands(report, include_python=include_python)
        if manual:
            print()
            print(manual)
        return 0
    actionable = [item for item in report.items if include_python or item.id != "python"]
    if not actionable:
        print("Zależności systemowe są na miejscu.")
        return 0
    print("Doinstalowuję: " + ", ".join(item.title for item in actionable))
    code, out = apply(report, prefer_pkexec=False, include_python=include_python)
    if out:
        print(out)
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
