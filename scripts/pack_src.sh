#!/usr/bin/env bash
# Сборка исходного архива поставки (ревизия 4 §1.6).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/../NestCraft_Studio_V0.0.18_src.zip}"
cd "$ROOT"
rm -f "$OUT"
zip -r "$OUT" . \
  -x '*/__pycache__/*' \
  -x '__pycache__/*' \
  -x '*/*.pyc' \
  -x '*.pyc' \
  -x '*/*.pyo' \
  -x '*/.pytest_cache/*' \
  -x '.pytest_cache/*' \
  -x '*/.ruff_cache/*' \
  -x '.ruff_cache/*' \
  -x '*/.mypy_cache/*' \
  -x '.mypy_cache/*' \
  -x '*/.git/*' \
  -x '.git/*' \
  -x '*.log' \
  -x 'data/catalog/*.db' \
  -x 'data/catalog/*.db-*' \
  -x '*.zip' \
  >/dev/null
echo "Wrote $OUT"
if unzip -l "$OUT" | grep -E '__pycache__|\.pyc|\.pytest_cache|\.ruff_cache|\.log$' >/dev/null; then
  echo "ERROR: archive contains excluded paths" >&2
  unzip -l "$OUT" | grep -E '__pycache__|\.pyc|\.pytest_cache|\.ruff_cache|\.log$' >&2
  exit 1
fi
echo "Hygiene OK"
ls -la "$OUT"
