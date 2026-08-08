"""
Bezpośrednie sterowanie Lovense przez Bluetooth LE (bez telefonu / Connect).

Obsługa WIELU zabawek naraz (np. Max 2 + Lush).

Protokół: https://buttplug.io/stpihkal/protocols/lovense/
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from max2_controller.models import CommandResult, ToyInfo

logger = logging.getLogger(__name__)

_LOVENSE_UUID_MARKERS = (
    "4bd4-bbd5-a6920e4c5653",
    "0000fff0-0000-1000-8000-00805f9b34fb",
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
)

# Specjalne ID w GUI / API: steruj wszystkimi połączonymi
TOY_ALL = "__ALL__"


def _is_lovense_name(name: str | None) -> bool:
    if not name:
        return False
    n = name.strip()
    upper = n.upper()
    return (
        n.startswith("LVS-")
        or n.startswith("LOVE-")
        or "LVS" in upper
        or "MAX" in upper
        or "LOVENSE" in upper
    )


def _is_lovense_uuids(uuids: list[str] | None) -> bool:
    if not uuids:
        return False
    joined = " ".join(u.lower() for u in uuids)
    return any(m in joined for m in _LOVENSE_UUID_MARKERS)


def _unpack(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value"):
        return _unpack(value.value)
    if isinstance(value, (list, tuple)):
        return [_unpack(v) for v in value]
    if isinstance(value, dict):
        return {k: _unpack(v) for k, v in value.items()}
    return value


def pump_to_air(pump: int) -> int:
    p = max(0, min(3, int(pump)))
    return {0: 0, 1: 2, 2: 3, 3: 5}[p]


def _addr_key(address: str) -> str:
    return address.strip().upper()


@dataclass
class _Conn:
    """Jedna połączona zabawka."""

    address: str
    name: str = ""
    client: Any = None
    tx_char: Any = None
    rx_char: Any = None
    device_type: str = ""
    info: ToyInfo | None = None
    secondary: str = "none"
    _rx_buf: str = ""
    _last_reply: str = ""
    _reply_event: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class _BleHub:
    """Wspólna pętla asyncio + wiele połączeń BLE."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ble-lovense-hub")
        self._thread.start()
        self.conns: dict[str, _Conn] = {}  # address upper -> conn
        self._hub_lock = asyncio.Lock()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coro, timeout: float = 30.0):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        try:
            self.call(self.disconnect_all(), timeout=15)
        except Exception:
            logger.exception("ble hub stop")
        self.loop.call_soon_threadsafe(self.loop.stop)

    def connected_keys(self) -> list[str]:
        return [
            k
            for k, c in self.conns.items()
            if c.client is not None and getattr(c.client, "is_connected", False)
        ]

    def is_any_connected(self) -> bool:
        return bool(self.connected_keys())

    def get_conn(self, address: str | None) -> _Conn | None:
        if not address or address == TOY_ALL:
            return None
        return self.conns.get(_addr_key(address))

    def target_conns(self, toy: str | None) -> list[_Conn]:
        """toy=None / TOY_ALL → wszystkie; inaczej jedna."""
        if toy is None or toy == TOY_ALL or toy == "":
            return [self.conns[k] for k in self.connected_keys()]
        c = self.get_conn(toy)
        if c and c.client and c.client.is_connected:
            return [c]
        return []

    # --- notify per device ---
    def _make_notify(self, conn: _Conn):
        def _on_notify(_char: Any, data: bytearray) -> None:
            try:
                text = bytes(data).decode("utf-8", errors="ignore")
            except Exception:
                return
            conn._rx_buf += text
            if ";" in conn._rx_buf:
                parts = conn._rx_buf.split(";")
                conn._rx_buf = parts[-1]
                for p in parts[:-1]:
                    if p.strip():
                        conn._last_reply = p.strip() + ";"
                        self.loop.call_soon_threadsafe(conn._reply_event.set)

        return _on_notify

    async def _bluez_known_lovense(self) -> list[dict[str, Any]]:
        try:
            from bleak.backends.bluezdbus.manager import get_global_bluez_manager
        except Exception:
            logger.exception("bluez manager")
            return []

        mgr = await get_global_bluez_manager()
        out: list[dict[str, Any]] = []
        props = getattr(mgr, "_properties", {}) or {}
        for path, ifaces in props.items():
            dev = ifaces.get("org.bluez.Device1")
            if not dev:
                continue
            name = _unpack(dev.get("Name")) or _unpack(dev.get("Alias")) or ""
            addr = _unpack(dev.get("Address"))
            if not addr:
                continue
            uuids = _unpack(dev.get("UUIDs")) or []
            uuids = [str(u) for u in uuids]
            connected = bool(_unpack(dev.get("Connected")))
            if not (_is_lovense_uuids(uuids) or _is_lovense_name(str(name))):
                continue
            out.append(
                {
                    "address": str(addr),
                    "name": str(name) or str(addr),
                    "path": str(path),
                    "connected": connected,
                    "uuids": uuids,
                    "rssi": "",
                    "source": "bluez",
                }
            )
        return out

    async def scan(self, timeout: float = 8.0) -> list[dict[str, Any]]:
        from bleak import BleakScanner

        found: dict[str, dict[str, Any]] = {}
        for d in await self._bluez_known_lovense():
            found[d["address"].upper()] = d

        def _cb(device, adv):
            name = device.name or (getattr(adv, "local_name", None) if adv else None) or ""
            uuids = []
            if adv is not None:
                su = getattr(adv, "service_uuids", None) or []
                uuids = [str(u) for u in su]
            if not (_is_lovense_name(name) or _is_lovense_uuids(uuids)):
                return
            key = device.address.upper()
            prev = found.get(key, {})
            found[key] = {
                "address": device.address,
                "name": name or prev.get("name") or device.address,
                "path": prev.get("path", ""),
                "connected": prev.get("connected", False),
                "uuids": uuids or prev.get("uuids", []),
                "rssi": str(getattr(adv, "rssi", "") or ""),
                "source": "scan",
            }

        try:
            scanner = BleakScanner(detection_callback=_cb)
            await scanner.start()
            await asyncio.sleep(timeout)
            await scanner.stop()
        except Exception:
            logger.exception("BLE advertisement scan")

        # oznacz już połączone w appce
        for key in self.connected_keys():
            if key in found:
                found[key]["connected"] = True
                found[key]["app_connected"] = True
            else:
                c = self.conns[key]
                found[key] = {
                    "address": c.address,
                    "name": c.name or c.address,
                    "path": "",
                    "connected": True,
                    "app_connected": True,
                    "uuids": [],
                    "rssi": "",
                    "source": "app",
                }
        return list(found.values())

    async def _resolve_ble_device(self, address: str, name: str = ""):
        from bleak.backends.device import BLEDevice

        address_u = address.upper()
        for d in await self._bluez_known_lovense():
            if d["address"].upper() == address_u and d.get("path"):
                return BLEDevice(d["address"], name or d.get("name") or address, {"path": d["path"]})
        path = f"/org/bluez/hci0/dev_{address.replace(':', '_')}"
        return BLEDevice(address, name or address, {"path": path})

    async def _find_tx_rx(self, client: Any):
        tx = rx = None
        for service in client.services:
            su = service.uuid.lower()
            chars = {c.uuid.lower(): c for c in service.characteristics}
            if "fff0" in su:
                rx = chars.get("0000fff1-0000-1000-8000-00805f9b34fb") or rx
                tx = chars.get("0000fff2-0000-1000-8000-00805f9b34fb") or tx
            if "6e400001" in su:
                rx = chars.get("6e400003-b5a3-f393-e0a9-e50e24dcca9e") or rx
                tx = chars.get("6e400002-b5a3-f393-e0a9-e50e24dcca9e") or tx
            if "4bd4-bbd5-a6920e4c5653" in su or ("300001" in su and "4bd4" in su):
                for ch in service.characteristics:
                    cu = ch.uuid.lower()
                    props = [p.lower() for p in (ch.properties or [])]
                    if "300002" in cu and ("write" in props or "write-without-response" in props):
                        tx = ch
                    if "300003" in cu and ("notify" in props or "indicate" in props):
                        rx = ch
                    if not tx and ("write" in props or "write-without-response" in props):
                        tx = ch
                    if not rx and "notify" in props:
                        rx = ch
        if not tx:
            for service in client.services:
                if not any(x in service.uuid.lower() for x in ("4bd4", "fff0", "6e400001")):
                    continue
                for ch in service.characteristics:
                    props = [p.lower() for p in (ch.properties or [])]
                    if "write" in props or "write-without-response" in props:
                        tx = tx or ch
                    if "notify" in props:
                        rx = rx or ch
        return tx, rx

    async def connect(self, address: str, name: str = "") -> ToyInfo:
        """
        Podłącz kolejną zabawkę BEZ rozłączania już trzymanych.
        Każdy adres MAC = osobne połączenie BLE.
        """
        from bleak import BleakClient

        key = _addr_key(address)
        # Szybki check bez długiego locka — inne urządzenia zostają
        existing = self.conns.get(key)
        if existing and existing.client and existing.client.is_connected:
            if existing.info:
                existing.info.app_connected = True
                return existing.info
            return ToyInfo(id=address, name=name or address, status="1", app_connected=True)

        async with self._hub_lock:
            existing = self.conns.get(key)
            if existing and existing.client and existing.client.is_connected:
                if existing.info:
                    existing.info.app_connected = True
                    return existing.info

            # tylko ten sam adres — nie ruszamy innych kluczy w self.conns
            if existing and existing.client:
                try:
                    await existing.client.disconnect()
                except Exception:
                    pass
                self.conns.pop(key, None)

            device = await self._resolve_ble_device(address, name=name)
            client = BleakClient(device, timeout=25.0)
            await client.connect()
            # daj GATT chwilę (ważne przy 2. urządzeniu na tym samym adapterze)
            await asyncio.sleep(0.15)
            tx, rx = await self._find_tx_rx(client)
            if not tx:
                await client.disconnect()
                raise RuntimeError("Brak charakterystyki TX — czy to Lovense?")

            conn = _Conn(address=address, name=name or getattr(device, "name", None) or address)
            conn.client = client
            conn.tx_char = tx
            conn.rx_char = rx
            if rx:
                try:
                    await client.start_notify(rx, self._make_notify(conn))
                except Exception:
                    logger.warning("start_notify failed for %s", address)

            self.conns[key] = conn

            dtype = ""
            try:
                dtype = await self.command(conn, "DeviceType;", wait=True, timeout=3.0) or ""
            except Exception:
                pass
            conn.device_type = dtype
            battery = None
            try:
                bat = await self.command(conn, "Battery;", wait=True, timeout=2.5) or ""
                m = re.search(r"(\d{1,3})", bat)
                if m:
                    battery = int(m.group(1))
            except Exception:
                pass

            info = ToyInfo.from_device_type(address, conn.name, dtype, battery=battery)
            info.app_connected = True
            info.status = "1"
            conn.info = info
            conn.secondary = info.secondary
            logger.info(
                "BLE connected %s model=%s secondary=%s total=%s",
                address,
                info.model_name,
                info.secondary,
                len(self.connected_keys()),
            )
            return info

    async def disconnect_one(self, address: str) -> None:
        key = _addr_key(address)
        conn = self.conns.pop(key, None)
        if not conn:
            return
        if conn.client and getattr(conn.client, "is_connected", False):
            try:
                disc = getattr(conn.client, "disconnect", None)
                if callable(disc):
                    await disc()
            except Exception:
                logger.exception("disconnect %s", address)

    async def disconnect_all(self) -> None:
        keys = list(self.conns.keys())
        for k in keys:
            await self.disconnect_one(k)

    async def command(self, conn: _Conn, cmd: str, wait: bool = False, timeout: float = 2.0) -> str:
        if not conn.client or not conn.client.is_connected or not conn.tx_char:
            raise RuntimeError("Brak połączenia BLE")
        if not cmd.endswith(";"):
            cmd = cmd + ";"
        async with conn._lock:
            conn._last_reply = ""
            conn._reply_event = asyncio.Event()
            data = cmd.encode("utf-8")
            try:
                await conn.client.write_gatt_char(conn.tx_char, data, response=False)
            except Exception:
                await conn.client.write_gatt_char(conn.tx_char, data, response=True)
            if not wait or not conn.rx_char:
                return ""
            try:
                await asyncio.wait_for(conn._reply_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return ""
            return conn._last_reply


class LovenseBleBackend:
    """Backend BLE — wiele zabawek Lovense jednocześnie."""

    name = "ble"

    def __init__(self) -> None:
        self._hub = _BleHub()
        self._scan_cache: list[dict[str, Any]] = []
        self._pattern_stop = threading.Event()
        self._pattern_thread: threading.Thread | None = None
        # kompatybilność: „primary” secondary z ostatnio użytej zabawki
        self._secondary = "none"
        self._connected_info: ToyInfo | None = None

    def close(self) -> None:
        self._stop_pattern()
        self._hub.stop()

    def is_connected(self) -> bool:
        return self._hub.is_any_connected()

    def connected_count(self) -> int:
        return len(self._hub.connected_keys())

    def connected_infos(self) -> list[ToyInfo]:
        out = []
        for k in self._hub.connected_keys():
            c = self._hub.conns[k]
            if c.info:
                c.info.status = "1"
                c.info.app_connected = True
                out.append(c.info)
            else:
                out.append(
                    ToyInfo(
                        id=c.address,
                        name=c.name or c.address,
                        status="1",
                        app_connected=True,
                        model_name="Lovense",
                    )
                )
        return out

    def scan(self, timeout: float = 8.0) -> tuple[list[ToyInfo], CommandResult]:
        try:
            devices = self._hub.call(self._hub.scan(timeout=timeout), timeout=timeout + 10)
            self._scan_cache = devices
            toys: list[ToyInfo] = []
            connected_map = {_addr_key(t.id): t for t in self.connected_infos()}
            for d in devices:
                addr = d["address"]
                key = _addr_key(addr)
                if key in connected_map:
                    toys.append(connected_map[key])
                    continue
                label = d.get("name") or "Lovense"
                nick = label
                if d.get("uuids") and _is_lovense_uuids(list(d.get("uuids") or [])):
                    if not _is_lovense_name(label):
                        nick = f"{label} (Lovense)"
                toys.append(
                    ToyInfo(
                        id=addr,
                        name=label,
                        nick_name=nick,
                        status="1" if d.get("connected") or d.get("app_connected") else "0",
                        full_functions=["Vibrate"],
                        model_name="Lovense",
                        secondary="none",
                    )
                )
            # dodaj połączone, których nie ma w skanie
            seen = {_addr_key(t.id) for t in toys}
            for t in self.connected_infos():
                if _addr_key(t.id) not in seen:
                    toys.insert(0, t)

            n_app = self.connected_count()
            if toys:
                msg = (
                    f"Skan: {len(toys)} widocznych, {n_app} połączonych w appce. "
                    f"Wybierz i „Połącz BLE” (można dodać kolejne)."
                )
            else:
                msg = "Skan BLE: nic — włącz zabawki blisko PC."
            return toys, CommandResult(ok=True, message=msg, raw=devices)
        except Exception as e:
            logger.exception("BLE scan")
            return [], CommandResult(ok=False, message=f"Skan BLE nieudany: {e}")

    def connect(self, address: str, name: str = "") -> CommandResult:
        self._stop_pattern()
        try:
            info = self._hub.call(self._hub.connect(address, name=name), timeout=30)
            self._connected_info = info
            self._secondary = info.secondary
            n = self.connected_count()
            return CommandResult(
                ok=True,
                message=(
                    f"Połączono: {info.display_name} · {info.model_name} [{info.secondary}] "
                    f"— łącznie {n} zabawk(i)"
                ),
                raw={"address": address, "model": info.model_name, "connected_total": n},
            )
        except Exception as e:
            logger.exception("BLE connect")
            return CommandResult(ok=False, message=f"Połączenie BLE nieudane: {e}")

    def disconnect(self, address: str | None = None) -> CommandResult:
        self._stop_pattern()
        try:
            if address and address != TOY_ALL:
                self._hub.call(self._hub.disconnect_one(address), timeout=10)
                msg = f"Rozłączono {address}"
            else:
                self._hub.call(self._hub.disconnect_all(), timeout=15)
                msg = "Rozłączono wszystkie zabawki BLE"
            infos = self.connected_infos()
            self._connected_info = infos[0] if infos else None
            self._secondary = self._connected_info.secondary if self._connected_info else "none"
            return CommandResult(ok=True, message=msg)
        except Exception as e:
            return CommandResult(ok=False, message=str(e))

    def get_toys(self) -> tuple[list[ToyInfo], CommandResult]:
        """
        Zwraca: połączone (app) + widoczne w ostatnim skanie (do dodania kolejnych).
        Dzięki temu po połączeniu 1. zabawki nadal widać 2. na liście skanu.
        """
        connected = self.connected_infos()
        by_id = {_addr_key(t.id): t for t in connected}

        for d in self._scan_cache:
            addr = d["address"]
            key = _addr_key(addr)
            if key in by_id:
                continue
            label = d.get("name") or "Lovense"
            nick = label
            if d.get("uuids") and _is_lovense_uuids(list(d.get("uuids") or [])):
                if not _is_lovense_name(label):
                    nick = f"{label} (Lovense)"
            # spróbuj odgadnąć model z nazwy (Lush3/Gemini/Max…)
            info = ToyInfo.from_device_type(addr, label, "", battery=None)
            info.status = "0"
            info.app_connected = False
            info.nick_name = nick
            by_id[key] = info

        toys = list(by_id.values())
        # połączone na górze
        toys.sort(key=lambda t: (0 if t.app_connected else 1, t.display_name.lower()))
        n = len(connected)
        if toys:
            return toys, CommandResult(
                ok=True,
                message=f"BLE: {n} połączonych, {len(toys)} na liście (skan+połączone)",
                raw={},
            )
        return [], CommandResult(
            ok=False,
            message="BLE: pusto — Skanuj BLE, potem Połącz (dodaj) kolejne urządzenia",
        )

    def _send_one(self, conn: _Conn, cmd: str, wait: bool = False) -> CommandResult:
        try:
            reply = self._hub.call(self._hub.command(conn, cmd, wait=wait), timeout=5)
            ok = True
            if reply and "ERR" in reply.upper():
                ok = False
            return CommandResult(ok=ok, message=reply or "OK", raw=reply)
        except Exception as e:
            return CommandResult(ok=False, message=f"{conn.address}: {e}")

    def _send(self, cmd: str, toy: str | None = None, wait: bool = False) -> CommandResult:
        targets = self._hub.target_conns(toy)
        if not targets:
            return CommandResult(ok=False, message="BLE: brak połączonych zabawek")
        results = [self._send_one(c, cmd, wait=wait) for c in targets]
        ok = all(r.ok for r in results)
        if len(results) == 1:
            return results[0]
        msg = f"{sum(1 for r in results if r.ok)}/{len(results)} OK — {cmd}"
        return CommandResult(ok=ok, message=msg)

    def _secondary_of(self, conn: _Conn) -> str:
        if conn.info:
            return conn.info.secondary
        return conn.secondary or "none"

    def _send_secondary_one(self, conn: _Conn, level: int) -> CommandResult:
        sec = self._secondary_of(conn)
        if sec == "pump":
            return self._send_one(conn, f"Air:Level:{pump_to_air(level)};")
        if sec == "rotate":
            return self._send_one(conn, f"Rotate:{max(0, min(20, int(level)))};")
        if sec == "vibrate2":
            return self._send_one(conn, f"Vibrate2:{max(0, min(20, int(level)))};")
        return CommandResult(ok=True, message="skip secondary")

    def set_vibrate(self, level: int, time_sec: float = 0, toy: str | None = None, **_) -> CommandResult:
        self._stop_pattern()
        level = max(0, min(20, int(level)))
        r = self._send(f"Vibrate:{level};", toy=toy)
        if r.ok and time_sec and time_sec > 0:
            self._schedule_stop(float(time_sec), only_vibrate=True, toy=toy)
        return r

    def set_pump(self, level: int, time_sec: float = 0, toy: str | None = None, **_) -> CommandResult:
        self._stop_pattern()
        targets = self._hub.target_conns(toy)
        if not targets:
            return CommandResult(ok=False, message="BLE: niepołączony")
        results = [self._send_secondary_one(c, level) for c in targets]
        ok = all(r.ok for r in results)
        r = CommandResult(ok=ok, message=results[0].message if len(results) == 1 else f"secondary x{len(results)}")
        if r.ok and time_sec and time_sec > 0:
            self._schedule_stop(float(time_sec), only_pump=True, toy=toy)
        return r

    def set_both(
        self,
        vibrate: int,
        pump: int,
        time_sec: float = 0,
        toy: str | None = None,
        **_,
    ) -> CommandResult:
        """
        vibrate = silnik 1 / główne wibracje
        pump    = druga funkcja zależnie od modelu:
                  Max 2 → Air, Nora → Rotate, Gemini/Edge → Vibrate2, Lush → ignorowane
        """
        self._stop_pattern()
        v = max(0, min(20, int(vibrate)))
        targets = self._hub.target_conns(toy)
        if not targets:
            return CommandResult(ok=False, message="BLE: niepołączony")
        ok = True
        parts = []
        for c in targets:
            sec = self._secondary_of(c)
            tag = (c.info.model_name if c.info else c.name) or c.address[:8]
            if sec == "vibrate2":
                # Gemini / Edge — dwa silniki
                r1 = self._send_one(c, f"Vibrate1:{v};")
                if not r1.ok:
                    r1 = self._send_one(c, f"Vibrate:{v};")
                r2 = self._send_one(c, f"Vibrate2:{max(0, min(20, int(pump)))};")
                ok = ok and r1.ok and r2.ok
                parts.append(f"{tag}:V1={v}/V2={pump}")
            elif sec == "pump":
                r1 = self._send_one(c, f"Vibrate:{v};")
                r2 = self._send_secondary_one(c, pump)
                ok = ok and r1.ok and r2.ok
                parts.append(f"{tag}:V={v}/Air")
            elif sec == "rotate":
                r1 = self._send_one(c, f"Vibrate:{v};")
                r2 = self._send_secondary_one(c, pump)
                ok = ok and r1.ok and r2.ok
                parts.append(f"{tag}:V={v}/R={pump}")
            else:
                # Lush 3 itd. — tylko wibracje
                r1 = self._send_one(c, f"Vibrate:{v};")
                ok = ok and r1.ok
                parts.append(f"{tag}:V={v}")
        msg = ", ".join(parts)
        if ok and time_sec and time_sec > 0:
            self._schedule_stop(float(time_sec), toy=toy)
        return CommandResult(ok=ok, message=msg)

    def stop(self, toy: str | None = None) -> CommandResult:
        self._stop_pattern()
        targets = self._hub.target_conns(toy)
        if not targets:
            return CommandResult(ok=False, message="BLE: niepołączony")
        ok = True
        for c in targets:
            sec = self._secondary_of(c)
            if sec == "vibrate2":
                ok = self._send_one(c, "Vibrate1:0;").ok and ok
                ok = self._send_one(c, "Vibrate2:0;").ok and ok
                ok = self._send_one(c, "Vibrate:0;").ok and ok
            else:
                ok = self._send_one(c, "Vibrate:0;").ok and ok
            if sec == "pump":
                ok = self._send_one(c, "Air:Level:0;").ok and ok
            elif sec == "rotate":
                ok = self._send_one(c, "Rotate:0;").ok and ok
        n = len(targets)
        return CommandResult(ok=ok, message=f"STOP BLE ({n} zab.)")

    def function(self, action: str, time_sec: float = 0, toy: str | None = None, **_) -> CommandResult:
        if action.strip().lower() == "stop":
            return self.stop(toy=toy)
        v = None
        p = None
        for part in action.split(","):
            part = part.strip()
            if ":" not in part:
                continue
            key, val = part.split(":", 1)
            key = key.strip().lower()
            try:
                num = int(float(val.strip().split("-")[0]))
            except ValueError:
                continue
            if key == "vibrate":
                v = num
            elif key in ("pump", "rotate", "vibrate2"):
                p = num
            elif key == "all":
                v = num
        if v is None and p is None:
            return CommandResult(ok=False, message=f"Nieobsługiwane action: {action}")
        if v is not None and p is not None:
            return self.set_both(v, p, time_sec=time_sec, toy=toy)
        if v is not None:
            return self.set_vibrate(v, time_sec=time_sec, toy=toy)
        return self.set_pump(p or 0, time_sec=time_sec, toy=toy)

    def preset(self, name: str, time_sec: float = 0, toy: str | None = None) -> CommandResult:
        from max2_controller.models import PRESET_ALIASES, PRESET_PATTERNS

        name = name.lower().strip()
        name = PRESET_ALIASES.get(name, name)
        if name not in PRESET_PATTERNS:
            return CommandResult(ok=False, message=f"Nieznany preset: {name}")
        seq, interval = PRESET_PATTERNS[name]
        strength = ";".join(str(x) for x in seq)
        return self.pattern(strength, time_sec=time_sec or 10, interval_ms=interval, toy=toy)

    def pattern(
        self,
        strength: str,
        time_sec: float = 0,
        toy: str | None = None,
        interval_ms: int = 200,
        features: str = "v,p",
        **_,
    ) -> CommandResult:
        parts = [p.strip() for p in strength.replace(",", ";").split(";") if p.strip()]
        levels: list[int] = []
        for p in parts:
            try:
                levels.append(max(0, min(20, int(float(p)))))
            except ValueError:
                return CommandResult(ok=False, message=f"Zła wartość pattern: {p}")
        if not levels:
            return CommandResult(ok=False, message="Pusty pattern")

        self._stop_pattern()
        self._pattern_stop.clear()
        duration = float(time_sec) if time_sec and time_sec > 0 else 10.0
        interval = max(0.05, interval_ms / 1000.0)
        use_pump = "p" in (features or "v,p").lower()
        toy_ref = toy

        def runner() -> None:
            end = time.time() + duration
            i = 0
            while not self._pattern_stop.is_set() and time.time() < end:
                lv = levels[i % len(levels)]
                try:
                    self._send(f"Vibrate:{lv};", toy=toy_ref)
                    if use_pump:
                        for c in self._hub.target_conns(toy_ref):
                            if self._secondary_of(c) == "pump":
                                air = 0 if lv == 0 else max(1, min(5, lv // 4))
                                self._send_one(c, f"Air:Level:{air};")
                except Exception:
                    logger.exception("pattern step")
                    break
                i += 1
                self._pattern_stop.wait(interval)
            try:
                self.stop(toy=toy_ref)
            except Exception:
                pass

        self._pattern_thread = threading.Thread(target=runner, daemon=True, name="ble-pattern")
        self._pattern_thread.start()
        n = len(self._hub.target_conns(toy))
        return CommandResult(ok=True, message=f"Pattern BLE {len(levels)} kroków × {n} zab. ({duration}s)")

    def get_battery(self, toy: str | None = None) -> tuple[int | None, CommandResult]:
        targets = self._hub.target_conns(toy)
        if not targets:
            # jeśli wybrana jedna, ale target_conns puste — spróbuj get_conn
            if toy and toy != TOY_ALL:
                c = self._hub.get_conn(toy)
                targets = [c] if c else []
        if not targets:
            return None, CommandResult(ok=False, message="BLE: niepołączony")
        # bateria z pierwszej / wybranej
        conn = targets[0]
        try:
            last = ""
            for _ in range(3):
                reply = self._hub.call(
                    self._hub.command(conn, "Battery;", wait=True, timeout=2.5), timeout=5
                )
                last = reply or ""
                m = re.fullmatch(r"(\d{1,3});?", last.strip()) or re.search(r"(\d{1,3})", last)
                if m:
                    level = int(m.group(1))
                    if 0 <= level <= 100:
                        if conn.info:
                            conn.info.battery = level
                        return level, CommandResult(ok=True, message=f"{level}%", raw=reply)
                time.sleep(0.15)
            return None, CommandResult(ok=False, message=f"Brak baterii: {last!r}")
        except Exception as e:
            return None, CommandResult(ok=False, message=str(e))

    def _stop_pattern(self) -> None:
        self._pattern_stop.set()
        t = self._pattern_thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._pattern_thread = None

    def _schedule_stop(
        self,
        seconds: float,
        only_vibrate: bool = False,
        only_pump: bool = False,
        toy: str | None = None,
    ) -> None:
        def later() -> None:
            time.sleep(seconds)
            if only_vibrate:
                self._send("Vibrate:0;", toy=toy)
            elif only_pump:
                self.set_pump(0, toy=toy)
            else:
                self.stop(toy=toy)

        threading.Thread(target=later, daemon=True).start()
