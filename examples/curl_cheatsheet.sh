#!/usr/bin/env bash
# Ściąga komend curl do integracji z grami / skryptami
# TOKEN i opcjonalnie HOST ustaw w env

HOST="${MAX2_API:-http://127.0.0.1:8765}"
TOKEN="${MAX2_TOKEN:?Ustaw MAX2_TOKEN}"

H=(-H "Content-Type: application/json" -H "X-API-Token: ${TOKEN}")

echo "== toys =="
curl -sS "${H[@]}" "${HOST}/toys" | python3 -m json.tool

echo "== vibrate 12, 3s =="
curl -sS "${H[@]}" -d '{"level":12,"time_sec":3}' "${HOST}/vibrate"

echo "== both =="
curl -sS "${H[@]}" -d '{"vibrate":10,"pump":2,"time_sec":5}' "${HOST}/function"

echo "== preset pulse =="
curl -sS "${H[@]}" -d '{"name":"pulse","time_sec":8}' "${HOST}/preset"

echo "== pattern =="
curl -sS "${H[@]}" -d '{"strength":"20;5;15;0","interval_ms":200,"time_sec":6}' "${HOST}/pattern"

echo "== stop =="
curl -sS "${H[@]}" -X POST "${HOST}/stop"
