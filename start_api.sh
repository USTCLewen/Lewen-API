#!/usr/bin/env bash
# Launch Paper Search API server.
# Usage: bash start_api.sh   or   ./start_api.sh
#
# Logs are managed by Python RotatingFileHandler (logs/api.log, max 50MB x 6).
# Console output is still printed for interactive use.
#
# Qdrant Server supports multi-worker; UVICORN_WORKERS can be 4+ for high concurrency.

cd "$(dirname "$0")"

export PYTHONUNBUFFERED=1
python main.py
