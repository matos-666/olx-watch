#!/bin/bash
# Local runner for the OLX watcher (launchd calls this every 15 min).
# OLX blocks datacenter IPs, so this has to run on a residential connection.
cd "$(dirname "$0")" || exit 1
set -a; [ -f .env ] && . ./.env; set +a
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
/usr/bin/env python3 watcher.py
echo
