#!/bin/sh
# Seed the persistent volume from the shipped store on first launch, then hand PID 1 to uvicorn
# so SIGTERM from `docker compose stop` triggers FastAPI's shutdown hook and closes Relate cleanly.
set -eu

STATE="${FOREBEAR_STATE:-/data}"
DB="${FOREBEAR_DB:-$STATE/forebear.rl}"
SHIPPED=/app/data/forebear.rl

mkdir -p "$STATE/live"
if [ ! -f "$DB" ]; then
    echo "forebear: first launch, seeding $DB from the shipped store"
    cp "$SHIPPED" "$DB.seeding"
    chmod 600 "$DB.seeding"
    mv "$DB.seeding" "$DB"
else
    echo "forebear: using existing store $DB"
fi

exec python -m uvicorn forebear.api:app --host 0.0.0.0 --port "${PORT:-8765}" \
    --no-server-header --timeout-graceful-shutdown 10 "$@"
