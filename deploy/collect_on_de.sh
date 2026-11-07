#!/usr/bin/env bash
# Запуск сбора метрик на DE (вызывается из GitHub Actions или вручную).
# 07-11-26: код сборщика доставляется на DE из репозитория — раньше там лежала
# копия, положенная руками (/opt/vpn-metrics-src не был git-репозиторием),
# и правки из репо до прода не доезжали: джоб и часовой крон крутили старый код.
set -euo pipefail

: "${DE_HOST:?DE_HOST не задан}"
DE_PORT="${DE_SSH_PORT:-22}"
REPO_DIR="${REPO_DIR:-/opt/vpn-metrics-src}"
SSH_OPTS=(-p "$DE_PORT" -o BatchMode=yes -o ConnectTimeout=15)

echo "== доставка сборщика на ${DE_HOST}:${REPO_DIR}"
tar -czf - --exclude='__pycache__' collector deploy \
  | ssh "${SSH_OPTS[@]}" "root@${DE_HOST}" "mkdir -p '${REPO_DIR}' && tar -xzf - -C '${REPO_DIR}'"

echo "== сбор"
ssh "${SSH_OPTS[@]}" "root@${DE_HOST}" bash -s <<EOF
set -e
cd "${REPO_DIR}"
./collector/collect.py
EOF
