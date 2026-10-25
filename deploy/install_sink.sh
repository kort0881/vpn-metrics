#!/usr/bin/env bash
# Разворачивает приёмник метрик на втором RU-сервере (по умолчанию Selectel).
#   SINK_HOST=135.106.178.226 SINK_PORT=50222 ./deploy/install_sink.sh
set -euo pipefail

: "${SINK_HOST:?SINK_HOST не задан}"
SINK_PORT="${SINK_PORT:-50222}"
DEST="${DEST:-/opt/vpn-metrics}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "== копирую schema.sql и скрипты в ${SINK_HOST}:${DEST}"
ssh -p "$SINK_PORT" "root@${SINK_HOST}" "mkdir -p ${DEST}/data ${DEST}/categories"
scp -P "$SINK_PORT" "$SRC/collector/schema.sql" "$SRC/collector/writer.py" "$SRC/collector/report.py" \
    "root@${SINK_HOST}:${DEST}/"

echo "== инициализирую БД"
ssh -p "$SINK_PORT" "root@${SINK_HOST}" "python3 - <<'PY'
import sqlite3, os
os.makedirs('/opt/vpn-metrics/data', exist_ok=True)
c = sqlite3.connect('/opt/vpn-metrics/data/metrics.db')
c.executescript(open('/opt/vpn-metrics/schema.sql').read())
c.commit()
print('таблицы:', [r[0] for r in c.execute(\"select name from sqlite_master where type='table' order by name\")])
PY"

echo "== готово: ${DEST}/data/metrics.db"
