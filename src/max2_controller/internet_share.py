"""Udostępnianie panelu remote przez internet (Cloudflare Tunnel / ngrok / Tailscale).

Jeden przycisk: w razie potrzeby sam pobiera cloudflared do katalogu użytkownika
(bez sudo), startuje tunnel i zwraca publiczny link https://….trycloudflare.com
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

logger = logging.getLogger(__name__)

# cloudflared quick tunnel
_CF_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")
# any https host (named hostname)
_HTTPS_URL_RE = re.compile(r"https://[a-zA-Z0-9][a-zA-Z0-9._-]+(?::\d+)?(?:/[^\s\"']*)?")
# ngrok
_NGROK_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.ngrok(?:-free)?\.(?:app|io|dev)")
# localhost.run / lhr.life
_LHR_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.(?:lhr\.life|localhost\.run)")
# tailscale funnel / ts.net
_TS_URL_RE = re.compile(r"https://[a-zA-Z0-9._-]+\.ts\.net(?::\d+)?")

# UA jak z llHTTPRequest — Cloudflare Bot Fight często to blokuje
SL_USER_AGENT = (
    "Second-Life-LSL/2024-03-18.8333615376 (https://secondlife.com) LovenseHUD/1.4"
)

_CLOUDFLARED_DIR = Path.home() / ".cloudflared"
_APP_CF_CONFIG = Path.home() / ".config" / "max2-controller" / "cloudflared.yml"

# Oficjalne binarne z GitHub Releases (bez konta Cloudflare)
_CF_RELEASE_BASE = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download"
)


def _config_bin_dir() -> Path:
    """~/.local/share/max2-controller/bin — bez sudo."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    d = Path(base) / "max2-controller" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cloudflared_asset_name() -> str:
    machine = platform.machine().lower()
    # linux amd64 / arm64
    if machine in ("x86_64", "amd64"):
        return "cloudflared-linux-amd64"
    if machine in ("aarch64", "arm64"):
        return "cloudflared-linux-arm64"
    if machine in ("armv7l", "armhf"):
        return "cloudflared-linux-arm"
    # fallback
    return "cloudflared-linux-amd64"


def bundled_cloudflared_path() -> Path:
    return _config_bin_dir() / "cloudflared"


def ensure_cloudflared(
    on_progress: Callable[[str], None] | None = None,
    force_download: bool = False,
) -> str:
    """
    Zwraca ścieżkę do cloudflared.
    Kolejność: PATH → lokalny bin użytkownika → pobranie z GitHub (bez sudo).
    """
    def prog(msg: str) -> None:
        logger.info("%s", msg)
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    # 1) system
    which = shutil.which("cloudflared")
    if which and not force_download:
        prog(f"cloudflared: {which}")
        return which

    # 2) już pobrany
    local = bundled_cloudflared_path()
    if local.is_file() and os.access(local, os.X_OK) and not force_download:
        # szybki smoke: --version
        try:
            subprocess.check_output([str(local), "--version"], timeout=5, stderr=subprocess.STDOUT)
            prog(f"cloudflared (lokalny): {local}")
            return str(local)
        except Exception:
            prog("Lokalny cloudflared uszkodzony — pobieram ponownie…")

    # 3) download
    asset = _cloudflared_asset_name()
    url = f"{_CF_RELEASE_BASE}/{asset}"
    prog(f"Pobieram cloudflared ({asset})… to chwilę potrwa (pierwszy raz).")
    tmp = local.with_suffix(".download")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "LovenseController/1.0 (max2-controller)"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            chunk = 256 * 1024
            with open(tmp, "wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if total > 0 and done % (1024 * 1024) < chunk:
                        pct = 100.0 * done / total
                        prog(f"Pobieranie cloudflared… {pct:.0f}%")
        tmp.replace(local)
        local.chmod(local.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # verify
        ver = subprocess.check_output(
            [str(local), "--version"], timeout=8, stderr=subprocess.STDOUT, text=True
        ).strip()
        prog(f"Gotowe: {ver[:80]}")
        return str(local)
    except Exception as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise RuntimeError(
            f"Nie udało się pobrać cloudflared: {e}\n"
            f"URL: {url}\n"
            "Sprawdź internet albo zainstaluj: sudo pacman -S cloudflared"
        ) from e


@dataclass
class TunnelInfo:
    public_base: str  # https://xxx.trycloudflare.com
    kind: str  # cloudflared | ngrok | tailscale
    panel_path: str = ""  # /r/TOKEN
    token: str = ""

    @property
    def panel_url(self) -> str:
        base = self.public_base.rstrip("/")
        if self.panel_path:
            return f"{base}{self.panel_path}"
        if self.token:
            return f"{base}/r/{quote(self.token, safe='')}"
        return base

    @property
    def health_url(self) -> str:
        return f"{self.public_base.rstrip('/')}/health"

    @property
    def share_url(self) -> str:
        tok = quote(self.token, safe="") if self.token else ""
        if tok:
            return f"{self.public_base.rstrip('/')}/share?token={tok}"
        return self.public_base


class InternetTunnel:
    """
    Quick tunnel: cloudflared (preferowane) lub ngrok.
    Proces w tle; URL wyłapywany z stdout/stderr.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.public_base: str | None = None
        self.kind: str | None = None
        self.error: str | None = None
        self._stop_flag = threading.Event()
        self.on_url: Callable[[str, str], None] | None = None  # (url, kind)
        self.on_log: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_progress: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _log(self, msg: str) -> None:
        logger.info("%s", msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _progress(self, msg: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(msg)
            except Exception:
                pass
        self._log(msg)

    def _emit_error(self, msg: str) -> None:
        self.error = msg
        logger.warning("%s", msg)
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass

    @staticmethod
    def cloudflared_path() -> str | None:
        which = shutil.which("cloudflared")
        if which:
            return which
        local = bundled_cloudflared_path()
        if local.is_file() and os.access(local, os.X_OK):
            return str(local)
        return None

    @staticmethod
    def ngrok_path() -> str | None:
        return shutil.which("ngrok")

    @staticmethod
    def has_any_tunnel_binary() -> bool:
        return bool(InternetTunnel.cloudflared_path() or InternetTunnel.ngrok_path())

    @staticmethod
    def install_hint() -> str:
        return (
            "Brak cloudflared — aplikacja spróbuje pobrać go automatycznie "
            "przy „Udostępnij przez internet” (bez sudo)."
        )

    def ensure_ready(self) -> str:
        """Pobierz cloudflared jeśli trzeba; zwróć ścieżkę."""
        return ensure_cloudflared(on_progress=self._progress)

    @staticmethod
    def is_logged_in() -> bool:
        return (_CLOUDFLARED_DIR / "cert.pem").is_file()

    def login_cloudflare(self, timeout: float = 180.0) -> bool:
        """
        cloudflared tunnel login — otwiera przeglądarkę (raz na konto).
        Blokuje do cert.pem lub timeout.
        """
        try:
            cf = self.ensure_ready()
        except Exception as e:
            self._emit_error(str(e))
            return False
        if self.is_logged_in():
            self._progress("Cloudflare: już zalogowany (cert.pem OK)")
            return True
        self._progress("Cloudflare login — otwórz przeglądarkę i zatwierdź domenę…")
        try:
            proc = subprocess.Popen(
                [cf, "tunnel", "login"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as e:
            self._emit_error(f"login failed: {e}")
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_logged_in():
                try:
                    proc.terminate()
                except Exception:
                    pass
                self._progress("Cloudflare: login OK")
                return True
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        try:
            proc.terminate()
        except Exception:
            pass
        if self.is_logged_in():
            return True
        self._emit_error("Login Cloudflare nieukończony (brak cert.pem). Spróbuj ponownie.")
        return False

    def _run_cf(self, args: list[str], timeout: float = 60.0) -> tuple[int, str]:
        cf = self.cloudflared_path() or self.ensure_ready()
        try:
            out = subprocess.check_output(
                [cf, *args],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
            return 0, out
        except subprocess.CalledProcessError as e:
            return e.returncode, (e.output or str(e))
        except Exception as e:
            return 1, str(e)

    def list_named_tunnels(self) -> list[dict]:
        """[{id, name}, …] z `cloudflared tunnel list`."""
        code, out = self._run_cf(["tunnel", "list"], timeout=30)
        if code != 0:
            return []
        rows = []
        for line in out.splitlines():
            # ID NAME CREATED CONNECTIONS
            parts = line.split()
            if len(parts) >= 2 and re.match(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                parts[0],
                re.I,
            ):
                rows.append({"id": parts[0], "name": parts[1]})
        return rows

    def ensure_named_tunnel(self, name: str, hostname: str, local_port: int) -> tuple[bool, str, str]:
        """
        Utwórz named tunnel + DNS + config.yml.
        Zwraca (ok, tunnel_id, public_url_or_error).
        Wymaga: login + domena w Cloudflare + hostname.
        """
        name = (name or "lovense-controller").strip()
        hostname = (hostname or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if not hostname or "." not in hostname:
            return False, "", "Podaj hostname DNS w Cloudflare (np. lovense.twojadomena.com)"
        if not self.is_logged_in():
            if not self.login_cloudflare():
                return False, "", "Najpierw zaloguj Cloudflare (cert.pem)"
        try:
            cf = self.ensure_ready()
        except Exception as e:
            return False, "", str(e)

        tunnels = self.list_named_tunnels()
        tid = ""
        for t in tunnels:
            if t["name"] == name:
                tid = t["id"]
                break
        if not tid:
            self._progress(f"Tworzę named tunnel „{name}”…")
            code, out = self._run_cf(["tunnel", "create", name], timeout=60)
            if code != 0:
                return False, "", f"create tunnel: {out[-400:]}"
            # Created tunnel NAME with id UUID
            m = re.search(
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                out,
                re.I,
            )
            if not m:
                # list again
                for t in self.list_named_tunnels():
                    if t["name"] == name:
                        tid = t["id"]
                        break
            else:
                tid = m.group(1)
            if not tid:
                return False, "", f"Nie odczytano UUID tunnelu: {out[-300:]}"
            self._progress(f"Tunnel utworzony: {tid}")
        else:
            self._progress(f"Tunnel „{name}” już istnieje ({tid})")

        # DNS route
        self._progress(f"DNS: {hostname} → tunnel {name}")
        code, out = self._run_cf(["tunnel", "route", "dns", name, hostname], timeout=60)
        if code != 0 and "already exists" not in (out or "").lower() and "CNAME" not in out:
            # często OK gdy rekord już jest
            if "error" in (out or "").lower() or "failed" in (out or "").lower():
                self._log(f"route dns ostrzeżenie: {out[-300:]}")

        # config.yml
        cred = _CLOUDFLARED_DIR / f"{tid}.json"
        if not cred.is_file():
            # credentials czasem w innym miejscu
            alt = list(_CLOUDFLARED_DIR.glob(f"*{tid}*.json")) if _CLOUDFLARED_DIR.is_dir() else []
            if alt:
                cred = alt[0]
            else:
                return False, tid, f"Brak pliku credentials: {cred}"

        _APP_CF_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        yml = (
            f"tunnel: {tid}\n"
            f"credentials-file: {cred}\n"
            f"\n"
            f"ingress:\n"
            f"  - hostname: {hostname}\n"
            f"    service: http://127.0.0.1:{int(local_port)}\n"
            f"  - service: http_status:404\n"
        )
        _APP_CF_CONFIG.write_text(yml, encoding="utf-8")
        public = f"https://{hostname}"
        self._progress(f"Config zapisany → {public}")
        return True, tid, public

    def start(
        self,
        local_port: int,
        prefer: str = "auto",
        auto_install: bool = True,
        *,
        mode: str = "quick",
        tunnel_name: str = "lovense-controller",
        hostname: str = "",
        token: str = "",
        known_public_url: str = "",
    ) -> bool:
        """
        mode:
          quick  — trycloudflare (URL losowy; przeglądarka OK, SL często blokowany)
          named  — stały hostname (wymaga domeny CF + login)
          token  — cloudflared tunnel run --token … (Zero Trust)
          ngrok  — ngrok http PORT (lepszy do Second Life)
          funnel — Tailscale Funnel
          ssh    — localhost.run (SSH reverse; fallback pod SL)
        """
        self.stop()
        self.error = None
        self.public_base = None
        self.kind = None
        self._stop_flag.clear()
        mode = (mode or "quick").lower().strip()

        cf = self.cloudflared_path()
        ng = self.ngrok_path()

        if prefer in ("auto", "cloudflared") and not cf and auto_install:
            try:
                cf = self.ensure_ready()
            except Exception as e:
                self._emit_error(str(e))
                if prefer == "auto" and ng and mode == "quick":
                    pass
                else:
                    return False

        cmd: list[str] | None = None
        kind = ""
        preset_url = ""

        if mode == "funnel":
            self._progress("Startuję Tailscale Funnel…")
            ok, pub_or_err = start_tailscale_funnel(local_port)
            if not ok:
                self._emit_error(pub_or_err)
                return False
            self.kind = "tailscale-funnel"
            with self._lock:
                self.public_base = pub_or_err
            self._progress(f"Publiczny URL (Funnel): {pub_or_err}")
            if self.on_url:
                try:
                    self.on_url(pub_or_err, self.kind)
                except Exception:
                    logger.exception("on_url")
            return True

        if mode == "ssh":
            if not shutil.which("ssh"):
                self._emit_error("Brak ssh — potrzebny do localhost.run")
                return False
            cmd = [
                "ssh",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "ExitOnForwardFailure=yes",
                "-T",
                "-R",
                f"80:127.0.0.1:{int(local_port)}",
                "nokey@localhost.run",
            ]
            kind = "localhost.run"

        elif mode == "ngrok":
            if not ng:
                self._emit_error(
                    "Brak ngrok. Zainstaluj: https://ngrok.com/download "
                    "albo: yay -S ngrok"
                )
                return False
            cmd = [ng, "http", str(int(local_port)), "--log=stdout", "--log-format=logfmt"]
            kind = "ngrok"

        elif mode == "token":
            if not cf:
                self._emit_error(self.install_hint())
                return False
            tok = (token or "").strip()
            if not tok:
                self._emit_error(
                    "Tryb token: wklej tunnel_token z Cloudflare Zero Trust "
                    "(Networks → Tunnels → Configure → token)."
                )
                return False
            cmd = [cf, "tunnel", "--no-autoupdate", "run", "--token", tok]
            kind = "cloudflared-token"
            preset_url = (known_public_url or "").strip().rstrip("/")
            if preset_url and not preset_url.startswith("http"):
                preset_url = "https://" + preset_url

        elif mode == "named":
            if not cf:
                self._emit_error(self.install_hint())
                return False
            ok, tid, pub_or_err = self.ensure_named_tunnel(tunnel_name, hostname, local_port)
            if not ok:
                self._emit_error(pub_or_err)
                return False
            preset_url = pub_or_err.rstrip("/")
            cmd = [
                cf,
                "tunnel",
                "--config",
                str(_APP_CF_CONFIG),
                "--no-autoupdate",
                "run",
                tid or tunnel_name,
            ]
            kind = "cloudflared-named"

        else:
            # quick
            if prefer in ("auto", "cloudflared") and cf:
                cmd = [
                    cf,
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{int(local_port)}",
                    "--no-autoupdate",
                ]
                kind = "cloudflared"
            elif prefer in ("auto", "ngrok") and ng:
                cmd = [ng, "http", str(int(local_port)), "--log=stdout", "--log-format=logfmt"]
                kind = "ngrok"
            else:
                self._emit_error(self.install_hint())
                return False

        self._progress(f"Startuję tunnel ({kind}, mode={mode})…")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except Exception as e:
            self._emit_error(f"Nie uruchomiono tunnel: {e}")
            self._proc = None
            return False

        self.kind = kind
        # named/token: URL znamy z góry
        if preset_url:
            with self._lock:
                self.public_base = preset_url
            self._progress(f"Publiczny URL (stały): {preset_url}")
            if self.on_url:
                try:
                    self.on_url(preset_url, kind)
                except Exception:
                    logger.exception("on_url")

        self._thread = threading.Thread(
            target=self._reader_loop, args=(kind, mode), daemon=True, name="internet-tunnel"
        )
        self._thread.start()
        return True

    def _reader_loop(self, kind: str, mode: str = "quick") -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._stop_flag.is_set():
                    break
                line = (line or "").rstrip()
                if not line:
                    continue
                low = line.lower()
                if (
                    "err" in low
                    or "failed" in low
                    or "trycloudflare" in low
                    or "ngrok" in low
                    or "registered" in low
                    or "connIndex" in line
                    or "connection" in low
                ):
                    self._log(f"[tunnel] {line[:220]}")

                url = None
                if "cloudflared" in kind or kind == "cloudflared":
                    m = _CF_URL_RE.search(line)
                    if m:
                        url = m.group(0)
                    elif mode == "quick":
                        pass
                else:
                    m = (
                        _NGROK_URL_RE.search(line)
                        or _LHR_URL_RE.search(line)
                        or _TS_URL_RE.search(line)
                        or _CF_URL_RE.search(line)
                    )
                    if m:
                        url = m.group(0)

                if url and (not self.public_base or mode == "quick"):
                    # quick: nadpisz gdy pojawi się trycloudflare
                    # named: nie nadpisuj stałego hostname
                    if mode in ("named", "token") and self.public_base:
                        continue
                    with self._lock:
                        self.public_base = url.rstrip("/")
                    self._progress(f"Publiczny URL: {self.public_base}")
                    if self.on_url:
                        try:
                            self.on_url(self.public_base, kind)
                        except Exception:
                            logger.exception("on_url callback")
        except Exception:
            logger.exception("tunnel reader")
        finally:
            code = proc.poll()
            if code is not None and code != 0 and not self._stop_flag.is_set():
                self._emit_error(f"Tunnel zakończył się kodem {code}")

    def wait_for_url(self, timeout: float = 35.0) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.public_base:
                return self.public_base
            if not self.running and not self.public_base:
                return None
            time.sleep(0.2)
        return self.public_base

    def stop(self) -> None:
        self._stop_flag.set()
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # nie kasuj public_base dla named — GUI i tak trzyma config
        self.kind = None
        self._log("Tunnel zatrzymany")


def tailscale_ip() -> str | None:
    """Zwraca IPv4 Tailscale (100.x) albo None."""
    path = shutil.which("tailscale")
    if not path:
        return None
    try:
        out = subprocess.check_output(
            [path, "ip", "-4"],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        ).strip()
        for line in out.splitlines():
            ip = line.strip()
            if ip.startswith("100."):
                return ip
        if out and re.match(r"^\d+\.\d+\.\d+\.\d+$", out.split()[0]):
            return out.split()[0]
    except Exception:
        logger.debug("tailscale ip failed", exc_info=True)
    return None


def tailscale_status_summary() -> str:
    path = shutil.which("tailscale")
    if not path:
        return "Tailscale nie zainstalowany (opcjonalny)"
    try:
        out = subprocess.check_output(
            [path, "status", "--self"],
            text=True,
            timeout=4,
            stderr=subprocess.STDOUT,
        ).strip()
        if not out or "Logged out" in out or "logged out" in out.lower():
            return "Tailscale: wylogowany — opcjonalnie: tailscale up"
        ip = tailscale_ip()
        if ip:
            return f"Tailscale: online · {ip}"
        return f"Tailscale: {out.splitlines()[0][:80]}"
    except subprocess.CalledProcessError as e:
        msg = (e.output or str(e))[:120]
        if "Logged out" in msg or "logged out" in msg.lower():
            return "Tailscale: wylogowany (opcjonalny)"
        return f"Tailscale: {msg}"
    except Exception as e:
        return f"Tailscale: {e}"


def flush_local_dns() -> None:
    """Flush NXDOMAIN cache only when already root.

    `resolvectl flush-caches` wymaga polkit — w GUI wyskakiwało
    „Authentication is required to flush DNS caches” i znikało po 3 s.
    """
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return
    for cmd in (
        ["resolvectl", "flush-caches"],
        ["systemd-resolve", "--flush-caches"],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(
                cmd,
                timeout=3,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        return


def wait_public_http(base_url: str, timeout: float = 50.0) -> tuple[bool, str]:
    """Czekaj aż nowy hostname tunelu się rozwiąże i /health odpowie.

    cloudflared wypisuje URL zanim DNS trycloudflare jest widoczny.
    systemd-resolved zapamiętuje NXDOMAIN i przeglądarka pokazuje
    Error 1016 / „witryna nieosiągalna” przez wiele minut — i to na
    *starym* hoście po restarcie tunelu.
    """
    from urllib.error import HTTPError, URLError

    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False, "brak URL"
    if not base.startswith("http"):
        base = "https://" + base
    health = base + "/health"
    deadline = time.time() + timeout
    last = "timeout"
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                health,
                headers={"User-Agent": "LovenseController/1.5", "Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                if 200 <= code < 500:
                    return True, f"HTTP {code}"
                last = f"HTTP {code}"
        except HTTPError as e:
            if int(e.code or 0) < 500:
                return True, f"HTTP {e.code}"
            last = f"HTTP {e.code}"
        except URLError as e:
            last = str(e.reason or e)
        except Exception as e:
            last = str(e)
        time.sleep(1.2)
    return False, last


def probe_sl_http(base_url: str, token: str = "", timeout: float = 10.0) -> dict:
    """Sprawdź publiczny URL tak, jak zrobi to grid SL (User-Agent LSL).

    Zwraca dict: ok, reachable, sl_blocked, status, message.
    sl_blocked=True → Cloudflare (lub inny WAF) rzuca challenge; przeglądarka
    może działać, HUD w Second Life nie.
    """
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote

    base = (base_url or "").strip().rstrip("/")
    out: dict = {
        "ok": False,
        "reachable": False,
        "sl_blocked": False,
        "status": 0,
        "message": "",
        "body": "",
    }
    if not base:
        out["message"] = "brak publicznego URL"
        return out
    if not base.startswith("http"):
        base = "https://" + base

    def _read(url: str, ua: str) -> tuple[int, str]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")[:800]
                return int(getattr(resp, "status", 200) or 200), body
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:800]
            except Exception:
                pass
            return int(e.code or 0), body
        except URLError as e:
            raise RuntimeError(str(e.reason or e)) from e

    try:
        code, body = _read(f"{base}/health", "LovenseController/1.4 probe")
        out["status"] = code
        out["body"] = body
        if code >= 200 and code < 300:
            out["reachable"] = True
        else:
            out["message"] = f"/health HTTP {code}"
    except Exception as e:
        out["message"] = f"tunel nie odpowiada: {e}"
        return out

    sl_path = f"{base}/sl/ping"
    if token:
        sl_path = f"{base}/sl/status?token={quote(token, safe='')}"
    try:
        code, body = _read(sl_path, SL_USER_AGENT)
        out["status"] = code
        out["body"] = body
        low = (body or "").lower()
        cf = (
            "just a moment" in low
            or "cf-ray" in low
            or "cloudflare" in low
            or "attention required" in low
            or "managed_challenge" in low
            or (code in (403, 503) and "challenge" in low)
        )
        if cf or (code == 403 and "remote disabled" not in low and "unauthorized" not in low):
            # 403 HTML od CF vs 403 JSON od naszej apki
            if "remote disabled" in low or '"error"' in low:
                out["ok"] = True
                out["reachable"] = True
                out["message"] = "serwer OK, panel remote wyłączony w GUI"
                return out
            if cf or "<html" in low or "just a moment" in low:
                out["sl_blocked"] = True
                out["message"] = (
                    "Cloudflare Bot Fight blokuje Second Life (LSL). "
                    "Przeglądarka może działać, HUD nie. "
                    "Użyj: ngrok, Tailscale Funnel albo Named tunnel "
                    "(wyłącz Bot Fight na domenie)."
                )
                return out
        if code in (401,):
            out["ok"] = True
            out["reachable"] = True
            out["message"] = "tunel OK, zły token"
            return out
        if 200 <= code < 300:
            out["ok"] = True
            out["reachable"] = True
            out["message"] = "tunel OK dla Second Life"
            return out
        out["message"] = f"SL probe HTTP {code}"
        return out
    except Exception as e:
        out["message"] = f"SL probe błąd: {e}"
        return out


def start_tailscale_funnel(local_port: int) -> tuple[bool, str]:
    """Włącz Tailscale Funnel na porcie panelu. Zwraca (ok, url_or_error)."""
    path = shutil.which("tailscale")
    if not path:
        return False, "Brak tailscale — sudo pacman -S tailscale && sudo tailscale up"
    try:
        subprocess.check_output(
            [path, "funnel", "--bg", str(int(local_port))],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=25,
        )
    except subprocess.CalledProcessError as e:
        out = (e.output or str(e)).strip()
        # już włączony bywa exit != 0
        if "already" not in out.lower() and "on" not in out.lower():
            return False, f"tailscale funnel: {out[-400:]}"
    except Exception as e:
        return False, f"tailscale funnel: {e}"
    try:
        st = subprocess.check_output(
            [path, "funnel", "status"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=12,
        )
    except Exception as e:
        return False, f"funnel status: {e}"
    m = _TS_URL_RE.search(st or "")
    if m:
        return True, m.group(0).rstrip("/")
    m = _HTTPS_URL_RE.search(st or "")
    if m:
        return True, m.group(0).rstrip("/")
    return False, f"Nie odczytano URL Funnel:\n{(st or '')[:300]}"


def build_public_panel_link(public_base: str, token: str) -> str:
    base = public_base.rstrip("/")
    return f"{base}/r/{quote(token, safe='')}"


def panel_base_from_link(link: str) -> str:
    """Z pełnego linku panelu (…/r/TOKEN, …/panel?token=) wyciągnij sam origin/base."""
    raw = (link or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import urlparse

        # dopisz scheme jeśli ktoś wkleił host bez https://
        candidate = raw if "://" in raw else f"https://{raw}"
        p = urlparse(candidate)
        if not p.netloc:
            return raw.rstrip("/")
        base = f"{p.scheme}://{p.netloc}"
        # zachowaj ścieżkę tylko gdy to nie /r/… /panel /sl/…
        path = (p.path or "").rstrip("/")
        if path and not path.startswith(("/r/", "/r")) and path not in (
            "/panel",
            "/share",
            "/sl",
            "/sl/",
        ):
            # np. reverse-proxy prefix — rzadkie; domyślnie origin
            pass
        return base.rstrip("/")
    except Exception:
        s = raw
        for marker in ("/r/", "/panel", "/share", "/sl/", "?"):
            i = s.find(marker)
            if i > 0:
                s = s[:i]
                break
        return s.rstrip("/")


def build_tailscale_panel_link(port: int, token: str) -> str | None:
    ip = tailscale_ip()
    if not ip:
        return None
    return f"http://{ip}:{int(port)}/r/{quote(token, safe='')}"
