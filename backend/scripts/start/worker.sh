#!/bin/bash
set -e -x

CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-2}"
uv run celery -A app.main:celery_app worker --loglevel=info --pool=threads \
  -c "$CONCURRENCY" \
  -Q default,sdk_sync,garmin_sync,webhook_sync
