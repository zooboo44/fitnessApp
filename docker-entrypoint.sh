#!/bin/sh
set -e

# Create tables and seed the exercise library once, before gunicorn forks workers.
# Retries so the app can start before Postgres is accepting connections.
attempt=1
until flask init-db; do
  if [ "$attempt" -ge 10 ]; then
    echo "Database not reachable after $attempt attempts, giving up." >&2
    exit 1
  fi
  echo "Database not ready (attempt $attempt), retrying in 3s..." >&2
  attempt=$((attempt + 1))
  sleep 3
done

exec "$@"
