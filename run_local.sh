#!/bin/bash
# Local runner for the OLX watcher (launchd calls this every 15 min).
#
# OLX blocks datacenter IPs, so the watcher can't live in GitHub Actions
# any more — it has to run from a residential connection. This wrapper
# supplies the Telegram credentials and keeps a rolling log.
cd "$(dirname "$0")" || exit 1

export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(cat .telegram_token 2>/dev/null)}"
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-$(cat .telegram_chat 2>/dev/null)}"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
/usr/bin/env python3 watcher.py
echo
