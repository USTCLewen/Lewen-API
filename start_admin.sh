#!/usr/bin/env bash
# Launch standalone Paper Search admin panel server.
# Usage: bash start_admin.sh
#
# Default URL: http://localhost:4100/admin/panel
# Configure with ADMIN_HOST, ADMIN_PORT, and ADMIN_TARGET_API_BASE_URL.

cd "$(dirname "$0")"

export PYTHONUNBUFFERED=1
python admin_main.py
