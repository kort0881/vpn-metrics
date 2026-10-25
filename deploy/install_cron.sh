#!/usr/bin/env bash
# Ставит на DE копию кода и cron-задание: сбор метрик каждый час.
#   DE_HOST=144.31.198.66 ./deploy/install_cron.sh
set -euo pipefail

: "${DE_HOST:?DE_HOST не задан}"
DE_PORT="${DE_SSH_PORT:-22}"
REPO_DIR="${REPO_DIR:-/opt/vpn-metrics-src}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "== копирую код на ${DE_HOST}:${REPO_DIR}"
ssh -p "$DE_PORT" "root@${DE_HOST}" "mkdir -p ${REPO_DIR}"
scp -P "$DE_PORT" -r "$SRC/collector" "$SRC/deploy" "root@${DE_HOST}:${REPO_DIR}/"
ssh -p "$DE_PORT" "root@${DE_HOST}" "chmod +x ${REPO_DIR}/collector/collect.py ${REPO_DIR}/deploy/*.sh"

echo "== ставлю cron (каждый час, лог /var/log/vpn-metrics.log)"
ssh -p "$DE_PORT" "root@${DE_HOST}" "bash -s" <<EOF
set -e
LINE='17 * * * * cd ${REPO_DIR} && /usr/bin/python3 ./collector/collect.py >> /var/log/vpn-metrics.log 2>&1'
( crontab -l 2>/dev/null | grep -v 'vpn-metrics' ; echo "\$LINE" ) | crontab -
crontab -l | grep vpn-metrics
EOF

echo "== готово. Первый прогон: cd ${REPO_DIR} && ./collector/collect.py"
