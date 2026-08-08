#!/usr/bin/env bash
# Połączenie Max 2 przez Bluetooth (bez telefonu) przez lokalne API programu
set -euo pipefail
HOST="${MAX2_API:-http://127.0.0.1:8765}"
TOKEN="${MAX2_TOKEN:?Ustaw MAX2_TOKEN z GUI/config.json}"
H=(-H "Content-Type: application/json" -H "X-API-Token: ${TOKEN}")

echo "== backend BLE =="
curl -sS "${H[@]}" -d '{"backend":"ble"}' "${HOST}/backend" | python3 -m json.tool

echo "== skan (ok. 8s) =="
curl -sS "${H[@]}" -d '{"timeout":8}' "${HOST}/ble/scan" | python3 -m json.tool

if [[ -n "${1:-}" ]]; then
  ADDR="$1"
else
  echo "Podaj adres MAC z wyniku skanu:  $0 AA:BB:CC:DD:EE:FF"
  exit 0
fi

echo "== connect $ADDR =="
curl -sS "${H[@]}" -d "{\"address\":\"${ADDR}\"}" "${HOST}/ble/connect" | python3 -m json.tool

echo "== test vibrate =="
curl -sS "${H[@]}" -d '{"vibrate":8,"pump":1,"time_sec":2}' "${HOST}/function" | python3 -m json.tool
