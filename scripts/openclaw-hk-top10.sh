#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

exec docker compose exec -T backend \
  python -m app.scripts.daily_scan_digest --market HK --top 10 "$@"
