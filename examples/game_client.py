#!/usr/bin/env python3
"""
Przykład integracji z grą / skryptem.

Użycie:
  export MAX2_TOKEN='twój-token-z-gui'
  python examples/game_client.py

Albo w grze: wywołuj te same endpointy HTTP gdy postać dostaje damage / score.
"""

from __future__ import annotations

import os
import sys
import time

import requests

BASE = os.environ.get("MAX2_API", "http://127.0.0.1:8765")
TOKEN = os.environ.get("MAX2_TOKEN", "")


def api(method: str, path: str, **json):
    headers = {"X-API-Token": TOKEN, "Content-Type": "application/json"}
    r = requests.request(method, f"{BASE}{path}", headers=headers, json=json or None, timeout=5)
    print(method, path, r.status_code, r.text[:300])
    r.raise_for_status()
    return r.json()


def on_damage(intensity: float = 0.5) -> None:
    """intensity 0.0–1.0 → wibracja + pump."""
    v = max(0, min(20, int(intensity * 20)))
    p = max(0, min(3, int(intensity * 3)))
    api("POST", "/function", vibrate=v, pump=p, time_sec=1.5)


def on_score() -> None:
    api("POST", "/preset", name="pulse", time_sec=3)


def panic() -> None:
    api("POST", "/stop")


def main() -> None:
    if not TOKEN:
        print("Ustaw MAX2_TOKEN (skopiuj z GUI → API do gier)", file=sys.stderr)
        sys.exit(1)

    print("Status:", api("GET", "/status"))
    print("--- symulacja gry ---")
    on_damage(0.3)
    time.sleep(2)
    on_damage(0.8)
    time.sleep(2)
    on_score()
    time.sleep(3)
    panic()
    print("OK")


if __name__ == "__main__":
    main()
