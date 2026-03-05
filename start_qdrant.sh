#!/usr/bin/env bash
# Start Qdrant server (binary deployment, no Docker).
# Usage: bash start_qdrant.sh   or   nohup bash start_qdrant.sh > logs/qdrant.log 2>&1 &

set -euo pipefail

cd "$(dirname "$0")"
mkdir -p corpus/qdrant_storage logs

QDRANT_BIN="./qdrant"
[[ -x "${QDRANT_BIN}" ]] || QDRANT_BIN="qdrant"

CONFIG_PATH="./config/qdrant_config.yaml"
[[ -f "${CONFIG_PATH}" ]] || { echo "❌ Config not found: ${CONFIG_PATH}"; exit 1; }

echo "🚀 Starting Qdrant (storage: corpus/qdrant_storage)"
exec "${QDRANT_BIN}" --config-path "${CONFIG_PATH}"
