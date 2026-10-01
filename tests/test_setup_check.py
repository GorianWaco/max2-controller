"""Lista braków i komendy instalacji — bez odpalania pacmana."""

from __future__ import annotations

from max2_controller.setup_check import (
    Probe,
    Report,
    _packages_as,
    apply,
    dialog_lines,
    distro_label,
    ensure_ready,
    format_report,
    inspect_system,
    main,
    packages_for,
    root_script,
    user_commands,
)


def _probe(**overrides: object) -> Probe:
    base: dict[str, object] = {
        "os_release": 'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\nPRETTY_NAME="CachyOS"\n',
        "which": lambda _cmd: True,
        "can_import": lambda _name: True,
        "gtk_ok": True,
        "adw_ok": True,
        "pulsesrc_ok": True,
        "bluetooth": "active",
        "has_pacman": True,
        "has_apt": False,
        "has_dnf": False,
        "flatpak": False,
        "python_exe": "/tmp/venv/bin/python",
        "requirements": "/tmp/lovense/requirements.txt",
    }
    base.update(overrides)
    return Probe(**base)  # type: ignore[arg-type]


def _missing(*cmds: str):
    def which(cmd: str) -> bool:
        return cmd not in cmds

    return which


def test_cachyos_complete_is_silent() -> None:
    report = inspect_system(_probe())
    assert report.distro == "CachyOS"
    assert report.family == "pacman"
    assert report.items == []
    assert report.should_prompt is False
    assert "na miejscu" in format_report(report)


def test_arch_family_and_label() -> None:
    probe = _probe(os_release='ID=arch\nPRETTY_NAME="Arch Linux"\n')
    assert distro_label(probe) == "Arch Linux"
    report = inspect_system(probe)
    assert report.family == "pacman"


def test_pw_record_on_cachyos_is_pipewire_audio() -> None:
    report = inspect_system(_probe(which=_missing("pw-record")))
    assert report.should_prompt is True
    assert packages_for(report) == ["pipewire-audio"]
    script = root_script(report)
    assert "pacman -S --needed --noconfirm pipewire-audio" in script
    assert "sudo" not in script
    assert "pw-record" in user_commands(report) or "pipewire-audio" in user_commands(report)


def test_bluez_install_also_enables_the_service() -> None:
    report = inspect_system(_probe(which=_missing("bluetoothctl")))
    assert [item.id for item in report.items] == ["bluez"]
    assert packages_for(report) == ["bluez", "bluez-utils"]
    script = root_script(report)
    assert "bluez bluez-utils" in script
    assert "systemctl enable --now bluetooth.service" in script
    assert "sudo systemctl enable --now bluetooth.service" in user_commands(report)


def test_inactive_bluetooth_service_has_no_packages() -> None:
    report = inspect_system(_probe(bluetooth="inactive"))
    assert [item.id for item in report.items] == ["bluetooth-service"]
    assert packages_for(report) == []
    script = root_script(report)
    assert "pacman" not in script
    assert "systemctl enable --now bluetooth.service" in script


def test_only_ssh_does_not_block_startup() -> None:
    report = inspect_system(_probe(which=_missing("ssh")))
    assert [item.id for item in report.items] == ["ssh"]
    assert report.items[0].required is False
    assert report.should_prompt is False
    assert packages_for(report) == ["openssh"]


def test_gst_missing_includes_pulsesrc_package_once() -> None:
    report = inspect_system(_probe(which=_missing("gst-launch-1.0"), pulsesrc_ok=False))
    ids = [item.id for item in report.items]
    assert "gst" in ids
    assert "pulsesrc" not in ids
    assert packages_for(report).count("gst-plugins-good") == 1


def test_pulsesrc_alone_when_gst_launch_exists() -> None:
    report = inspect_system(_probe(pulsesrc_ok=False))
    assert [item.id for item in report.items] == ["pulsesrc"]
    assert packages_for(report) == ["gst-plugins-good"]


def test_ubuntu_dedupes_pipewire_bin() -> None:
    report = inspect_system(
        _probe(
            os_release='ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04"\n',
            has_pacman=False,
            has_apt=True,
            which=_missing("pw-dump", "pw-record"),
        )
    )
    assert report.family == "apt"
    assert report.distro == "Ubuntu 24.04"
    names = packages_for(report)
    assert names.count("pipewire-bin") == 1
    assert "pipewire" in names
    script = root_script(report)
    assert "apt-get install -y" in script
    assert "sudo" not in script


def test_fedora_pw_tools() -> None:
    report = inspect_system(
        _probe(
            os_release='ID=fedora\nPRETTY_NAME="Fedora"\n',
            has_pacman=False,
            has_dnf=True,
            which=_missing("pw-dump", "pactl"),
        )
    )
    assert report.family == "dnf"
    names = packages_for(report)
    assert "pipewire-utils" in names
    assert "pulseaudio-utils" in names
    assert "pipewire-pulseaudio" in names


def test_python_modules_go_to_pip_not_pacman() -> None:
    def can_import(name: str) -> bool:
        return name != "flask"

    report = inspect_system(_probe(can_import=can_import))
    assert any(item.id == "python" and item.required for item in report.items)
    assert packages_for(report) == []
    assert root_script(report) == ""
    cmd = user_commands(report)
    assert "/tmp/venv/bin/python -m pip install -r /tmp/lovense/requirements.txt" in cmd
    assert "pacman" not in cmd


def test_only_pynput_is_optional() -> None:
    def can_import(name: str) -> bool:
        return name != "pynput"

    report = inspect_system(_probe(can_import=can_import))
    assert [item.id for item in report.items] == ["python"]
    assert report.should_prompt is False


def test_flatpak_reports_nothing() -> None:
    report = inspect_system(
        _probe(flatpak=True, gtk_ok=False, which=_missing("pw-record"), can_import=lambda _n: False)
    )
    assert report.items == []


def test_unknown_distro_lists_cachyos_and_apt() -> None:
    report = inspect_system(
        _probe(
            os_release="",
            has_pacman=False,
            has_apt=False,
            has_dnf=False,
            which=_missing("pw-record"),
        )
    )
    assert report.family == "unknown"
    text = user_commands(report)
    assert "pipewire-audio" in text
    assert "pipewire-bin" in text
    assert "pipewire-utils" in text
    code, out = apply(report, prefer_pkexec=False)
    assert code == 1
    assert "Nie rozpoznaję dystrybucji" in out
    assert "pipewire-audio" in out


def test_dialog_lines_mark_optional() -> None:
    report = inspect_system(_probe(which=_missing("bluetoothctl", "ssh")))
    lines = dialog_lines(report)
    assert lines[0].startswith("Na CachyOS")
    assert "Bluetooth" in lines
    assert "Tunel SSH (opcjonalne)" in lines
    assert len(lines) % 2 == 1


def test_packages_as_switches_family() -> None:
    report = inspect_system(_probe(which=_missing("ssh")))
    assert _packages_as(report, "apt", include_python=True) == ["openssh-client"]
    assert _packages_as(report, "dnf", include_python=True) == ["openssh-clients"]


def test_ensure_ready_stays_quiet_when_complete(monkeypatch) -> None:
    monkeypatch.setattr("max2_controller.setup_check.in_flatpak", lambda: False)
    monkeypatch.setattr(
        "max2_controller.setup_check.inspect_system",
        lambda: Report(distro="CachyOS", family="pacman"),
    )
    called = {"n": 0}
    monkeypatch.setattr(
        "max2_controller.setup_check.ask",
        lambda *_a, **_k: called.__setitem__("n", called["n"] + 1),
    )
    assert ensure_ready() == "ok"
    assert called["n"] == 0


def test_ensure_ready_asks_when_bluetooth_missing(monkeypatch) -> None:
    report = inspect_system(_probe(which=_missing("bluetoothctl")))
    monkeypatch.setattr("max2_controller.setup_check.in_flatpak", lambda: False)
    monkeypatch.setattr("max2_controller.setup_check.inspect_system", lambda: report)
    monkeypatch.setattr("max2_controller.setup_check.ask", lambda *_a, **_k: "skip")
    assert ensure_ready() == "ok"


def test_main_apply_system_skips_python_only(monkeypatch, capsys) -> None:
    def can_import(name: str) -> bool:
        return name != "numpy"

    report = inspect_system(_probe(can_import=can_import))
    monkeypatch.setattr("max2_controller.setup_check.in_flatpak", lambda: False)
    monkeypatch.setattr("max2_controller.setup_check.inspect_system", lambda: report)
    assert main(["--apply-system"]) == 0
    assert "na miejscu" in capsys.readouterr().out


def test_main_report_exits_nonzero_when_required(monkeypatch, capsys) -> None:
    report = inspect_system(_probe(which=_missing("pw-record")))
    monkeypatch.setattr("max2_controller.setup_check.in_flatpak", lambda: False)
    monkeypatch.setattr("max2_controller.setup_check.inspect_system", lambda: report)
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "pipewire-audio" in out
    assert "Jedna aplikacja" in out
