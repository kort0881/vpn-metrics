#!/usr/bin/env bash
# Печать отчёта со второго RU-сервера (сводка без персональных данных).
set -euo pipefail

: "${SINK_HOST:?SINK_HOST не задан}"
SINK_PORT="${SINK_PORT:-50222}"

ssh -p "$SINK_PORT" -o BatchMode=yes -o ConnectTimeout=15 "root@${SINK_HOST}" \
  'python3 /opt/vpn-metrics/report.py --days 1'
