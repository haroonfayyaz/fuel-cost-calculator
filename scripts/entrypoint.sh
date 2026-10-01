#!/bin/sh
set -e

python /app/scripts/wait_for_db.py

python manage.py migrate --noinput

exec "$@"
