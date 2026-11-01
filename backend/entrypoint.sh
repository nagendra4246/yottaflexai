#!/bin/sh
set -eu

alembic upgrade head
if [ "${SEED_DATA:-true}" = "true" ] || [ "${SEED_DATA:-true}" = "1" ]; then
    python -m generator.load_data --data-dir /app/data/seed
fi
exec "$@"
