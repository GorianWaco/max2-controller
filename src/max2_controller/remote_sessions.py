"""Sesje panelu zdalnego: kto jest online, kick, uprawnienia do zabawek."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RemoteSession:
    id: str
    display_name: str
    remote_addr: str
    user_agent: str = ""
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    # False = tylko podgląd / zablokowane sterowanie
    can_control: bool = True
    # None = wszystkie aktualnie połączone; frozenset() = żadna; ids = wybrane
    allowed_toy_ids: frozenset[str] | None = None
    kicked: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        age = max(0, int(time.time() - self.connected_at))
        idle = max(0, int(time.time() - self.last_seen))
        return {
            "id": self.id,
            "display_name": self.display_name,
            "remote_addr": self.remote_addr,
            "user_agent": (self.user_agent or "")[:120],
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "connected_for_sec": age,
            "idle_sec": idle,
            "can_control": self.can_control,
            "allowed_toy_ids": None if self.allowed_toy_ids is None else sorted(self.allowed_toy_ids),
            "allow_all_toys": self.allowed_toy_ids is None,
            "kicked": self.kicked,
            "note": self.note,
            "online": idle < 12 and not self.kicked,
        }


class RemoteSessionManager:
    """
    Współdzielone z create_remote_app i GUI hosta.
    Sesje wygasają po braku heartbeat; kick + opcjonalny ban IP.
    """

    STALE_SEC = 20.0
    DEFAULT_BAN_MIN = 30

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, RemoteSession] = {}
        # ip -> unix time ban_until
        self._ip_bans: dict[str, float] = {}
        # domyślne dla NOWEJ sesji: None = wszystkie zabawki
        self.default_allowed_toy_ids: frozenset[str] | None = None
        self.default_can_control: bool = True
        self._listeners: list = []

    def on_change(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def _prune_unlocked(self) -> None:
        now = time.time()
        dead = [
            sid
            for sid, s in self._sessions.items()
            if (now - s.last_seen) > self.STALE_SEC and not s.kicked
        ]
        # kicked trzymamy dłużej żeby nie wracali tym samym id
        kicked_old = [
            sid
            for sid, s in self._sessions.items()
            if s.kicked and (now - s.last_seen) > 3600
        ]
        for sid in dead + kicked_old:
            self._sessions.pop(sid, None)
        # wygasłe bany
        for ip, until in list(self._ip_bans.items()):
            if until <= now:
                self._ip_bans.pop(ip, None)

    def prune(self) -> None:
        with self._lock:
            self._prune_unlocked()

    def is_ip_banned(self, ip: str) -> bool:
        with self._lock:
            until = self._ip_bans.get(ip or "")
            return bool(until and until > time.time())

    def ban_ip(self, ip: str, minutes: float | None = None) -> None:
        if not ip or ip in ("127.0.0.1", "::1"):
            return
        mins = self.DEFAULT_BAN_MIN if minutes is None else float(minutes)
        with self._lock:
            self._ip_bans[ip] = time.time() + mins * 60
            self._notify()

    def unban_ip(self, ip: str) -> None:
        with self._lock:
            self._ip_bans.pop(ip, None)
            self._notify()

    def clear_bans(self) -> None:
        with self._lock:
            self._ip_bans.clear()
            self._notify()

    def list_bans(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            out = []
            for ip, until in self._ip_bans.items():
                if until > now:
                    out.append({"ip": ip, "until": until, "remaining_sec": int(until - now)})
            return out

    def join(
        self,
        display_name: str,
        remote_addr: str,
        user_agent: str = "",
        session_id: str | None = None,
    ) -> tuple[RemoteSession | None, str | None]:
        """
        Zwraca (session, error).
        """
        ip = (remote_addr or "").split("%")[0].strip()
        with self._lock:
            self._prune_unlocked()
            if self.is_ip_banned(ip):
                return None, "banned"
            name = (display_name or "Partner").strip()[:40] or "Partner"
            # reuse session if still valid
            if session_id and session_id in self._sessions:
                s = self._sessions[session_id]
                if s.kicked:
                    return None, "kicked"
                s.display_name = name
                s.remote_addr = ip or s.remote_addr
                s.user_agent = (user_agent or s.user_agent)[:200]
                s.last_seen = time.time()
                self._notify()
                return s, None
            sid = secrets.token_urlsafe(16)
            s = RemoteSession(
                id=sid,
                display_name=name,
                remote_addr=ip or "?",
                user_agent=(user_agent or "")[:200],
                can_control=self.default_can_control,
                allowed_toy_ids=self.default_allowed_toy_ids,
            )
            self._sessions[sid] = s
            self._notify()
            return s, None

    def heartbeat(self, session_id: str, remote_addr: str = "") -> RemoteSession | None:
        with self._lock:
            self._prune_unlocked()
            s = self._sessions.get(session_id or "")
            if not s or s.kicked:
                return None
            if self.is_ip_banned(s.remote_addr):
                s.kicked = True
                return None
            s.last_seen = time.time()
            if remote_addr:
                s.remote_addr = remote_addr.split("%")[0].strip() or s.remote_addr
            return s

    def get(self, session_id: str) -> RemoteSession | None:
        with self._lock:
            return self._sessions.get(session_id or "")

    def list_sessions(self, include_kicked: bool = True) -> list[RemoteSession]:
        with self._lock:
            self._prune_unlocked()
            items = list(self._sessions.values())
            if not include_kicked:
                items = [s for s in items if not s.kicked]
            items.sort(key=lambda s: s.connected_at, reverse=True)
            return items

    def kick(self, session_id: str, ban_ip: bool = True, ban_minutes: float = 30) -> bool:
        with self._lock:
            s = self._sessions.get(session_id or "")
            if not s:
                return False
            s.kicked = True
            s.can_control = False
            s.last_seen = time.time()
            if ban_ip:
                ip = s.remote_addr
                if ip and ip not in ("127.0.0.1", "::1", "?"):
                    self._ip_bans[ip] = time.time() + float(ban_minutes) * 60
            self._notify()
            return True

    def remove(self, session_id: str) -> bool:
        """Usuń sesję bez bana (leave)."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions.pop(session_id, None)
                self._notify()
                return True
            return False

    def set_can_control(self, session_id: str, enabled: bool) -> bool:
        with self._lock:
            s = self._sessions.get(session_id or "")
            if not s or s.kicked:
                return False
            s.can_control = bool(enabled)
            self._notify()
            return True

    def set_allowed_toys(self, session_id: str, toy_ids: list[str] | None) -> bool:
        """
        toy_ids=None → wszystkie zabawki
        toy_ids=[] → żadna
        toy_ids=[id,…] → tylko te
        """
        with self._lock:
            s = self._sessions.get(session_id or "")
            if not s or s.kicked:
                return False
            if toy_ids is None:
                s.allowed_toy_ids = None
            else:
                s.allowed_toy_ids = frozenset(str(t) for t in toy_ids if t)
            self._notify()
            return True

    def set_default_allowed_toys(self, toy_ids: list[str] | None) -> None:
        with self._lock:
            if toy_ids is None:
                self.default_allowed_toy_ids = None
            else:
                self.default_allowed_toy_ids = frozenset(str(t) for t in toy_ids if t)
            self._notify()

    def set_name(self, session_id: str, name: str) -> bool:
        with self._lock:
            s = self._sessions.get(session_id or "")
            if not s:
                return False
            s.display_name = (name or s.display_name).strip()[:40]
            self._notify()
            return True

    def check_control(
        self, session_id: str
    ) -> tuple[RemoteSession | None, str | None]:
        """(session, error_code) error: missing|kicked|banned|no_control"""
        with self._lock:
            self._prune_unlocked()
            if not session_id:
                return None, "missing"
            s = self._sessions.get(session_id)
            if not s:
                return None, "missing"
            if s.kicked:
                return s, "kicked"
            if self.is_ip_banned(s.remote_addr):
                return s, "banned"
            if not s.can_control:
                return s, "no_control"
            s.last_seen = time.time()
            return s, None

    def resolve_target_toys(
        self,
        session: RemoteSession,
        requested_toy: str | None,
        connected_toy_ids: list[str],
    ) -> tuple[list[str], str | None]:
        """
        Zwraca (lista id zabawek, error_code|None).
        Pusta lista + error = brak uprawnień / offline.
        """
        connected = [t for t in connected_toy_ids if t]
        conn_map = {c.upper(): c for c in connected}

        if session.allowed_toy_ids is None:
            allowed_keys = set(conn_map.keys())
        else:
            want = {a.upper() for a in session.allowed_toy_ids}
            allowed_keys = want & set(conn_map.keys()) if conn_map else want

        if requested_toy:
            ru = requested_toy.upper()
            if session.allowed_toy_ids is not None and ru not in {a.upper() for a in session.allowed_toy_ids}:
                return [], "toy_not_allowed"
            if conn_map and ru not in conn_map:
                return [], "toy_offline"
            return [conn_map.get(ru, requested_toy)], None

        if not allowed_keys and session.allowed_toy_ids is not None:
            return [], "no_toys_allowed"

        if not conn_map:
            # backend nie podał listy — pozwól na domyślne sterowanie (caller użyje TOY_ALL)
            if session.allowed_toy_ids is None:
                return [], None  # pusta = „wszystkie / domyślne”
            return list(session.allowed_toy_ids), None

        return [conn_map[k] for k in sorted(allowed_keys)], None

    def count_online(self) -> int:
        with self._lock:
            self._prune_unlocked()
            return sum(1 for s in self._sessions.values() if not s.kicked and (time.time() - s.last_seen) < 12)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._prune_unlocked()
            return {
                "sessions": [s.to_dict() for s in sorted(self._sessions.values(), key=lambda x: -x.connected_at)],
                "online_count": sum(
                    1
                    for s in self._sessions.values()
                    if not s.kicked and (time.time() - s.last_seen) < 12
                ),
                "ip_bans": self.list_bans(),
                "default_allow_all_toys": self.default_allowed_toy_ids is None,
                "default_allowed_toy_ids": (
                    None
                    if self.default_allowed_toy_ids is None
                    else sorted(self.default_allowed_toy_ids)
                ),
                "default_can_control": self.default_can_control,
            }
