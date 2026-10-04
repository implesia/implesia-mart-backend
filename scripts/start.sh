#!/bin/sh
set -eu

# Moves the database forward to this image's head. See docs/rollback.md.
alembic upgrade head
python -m scripts.bootstrap_production

# Workers in this container add to the same request counters.
metrics_dir="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus}"
export PROMETHEUS_MULTIPROC_DIR="$metrics_dir"
rm -rf "$metrics_dir"
mkdir -p "$metrics_dir"

exec gunicorn app.main:app \
  --config app/gunicorn_config.py \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "${WEB_CONCURRENCY:-2}" \
  --bind "0.0.0.0:${PORT:-8000}" \
  --access-logfile - \
  --error-logfile -
