"""Kolejka energii — zapis wibracji bez zabawki i odtwarzanie."""

from __future__ import annotations

from pathlib import Path

from max2_controller.charge_bank import ChargeBank, item_energy, item_duration


def test_enqueue_and_energy(tmp_path: Path) -> None:
    bank = ChargeBank(path=tmp_path / "bank.json")
    n = bank.enqueue({"action": "vibrate", "level": 10, "time": 4})
    assert n == 1
    assert bank.count == 1
    assert 0 < bank.energy <= 100
    bank.enqueue({"action": "stop"})
    assert bank.count == 1
    bank.enqueue({"action": "intensity", "i": 0.8, "time": 6})
    assert bank.count == 2
    snap = bank.snapshot()
    assert snap["bank"] == 2
    assert snap["energy"] == bank.energy


def test_ingest_packed_from_lsl(tmp_path: Path) -> None:
    bank = ChargeBank(path=tmp_path / "bank.json")
    n = bank.ingest_packed("i|0.5|4^v|10|6^p|pulse|8")
    assert n == 3
    assert bank.count == 3
    bank.clear()
    assert bank.count == 0
    assert bank.energy == 0


def test_persist_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "bank.json"
    a = ChargeBank(path=path)
    a.enqueue({"action": "preset", "name": "wave", "time": 5})
    b = ChargeBank(path=path)
    b.load()
    assert b.count == 1
    assert b._items[0]["name"] == "wave"


def test_item_helpers() -> None:
    assert item_duration({"time": 3}) == 3
    assert item_energy({"action": "vibrate", "level": 20, "time": 10}) > item_energy(
        {"action": "vibrate", "level": 1, "time": 1}
    )
