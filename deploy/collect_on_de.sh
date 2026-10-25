#!/usr/bin/env bash
# Запуск сбора метрик на DE (вызывается из GitHub Actions или вручную).
set -euo pipefail

: "${DE_HOST:?DE_HOST не задан}"
DE_PORT="${DE_SSH_PORT:-22}"
REPO_DIR="${REPO_DIR:-/opt/vpn-metrics-src}"

ssh -p "$DE_PORT" -o BatchMode=yes -o ConnectTimeout=15 "root@${DE_HOST}" bash -s <<EOF
set -e
cd "$REPO_DIR"
./collector/collect.py
EOF
