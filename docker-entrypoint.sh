#!/bin/sh
set -e

# Create tables and seed the exercise library once, before gunicorn forks workers.
# `init-db` waits for the database itself and exits with a clear message on
# config or schema problems, so there's nothing to retry here.
flask init-db --wait 30

exec "$@"
