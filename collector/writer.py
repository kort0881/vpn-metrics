#!/usr/bin/env python3
"""Запись снимка метрик в SQLite на втором RU-сервере.

Вызывается collector.py по SSH: writer.py <payload.json>
Раскладывает данные по таблицам и экспортирует категории в отдельные CSV,
чтобы «каждый был посчитан и распределён» — активные, спящие, забаненные и т.д.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import time

BASE = os.environ.get("METRICS_DIR", "/opt/vpn-metrics")
DB = os.path.join(BASE, "data", "metrics.db")
CATDIR = os.path.join(BASE, "categories")
SCHEMA = os.path.join(BASE, "schema.sql")

CATEGORY_TITLES = {
    "active": "активны (заходили <=7 дней)",
    "silent_7d": "молчат 7-30 дней",
    "silent_30d": "молчат 30-90 дней",
    "silent_90d": "молчат >90 дней",
    "never_seen": "ни разу не заходили",
    "no_key": "нет ключа",
    "unsubscribed": "отписались от канала",
    "banned": "забанены",
}


def main() -> int:
    payload_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/metrics_payload.json"
    with open(payload_path, encoding="utf-8") as f:
        snap = json.load(f)

    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    os.makedirs(CATDIR, exist_ok=True)

    c = sqlite3.connect(DB)
    if os.path.exists(SCHEMA):
        c.executescript(open(SCHEMA, encoding="utf-8").read())

    run_id = c.execute(
        "insert into runs(started_at, status) values(?, 'ok')",
        (int(snap.get("started_at") or time.time() * 1000),),
    ).lastrowid

    cur = c.execute(
        "insert into snapshots(taken_at, source_host, users_total, clients_total) values(?,?,?,?)",
        (snap["taken_at"], snap.get("source_host", "?"), snap["users_total"], snap["clients_total"]),
    )
    sid = cur.lastrowid

    for name, value in snap["metrics"].items():
        c.execute("insert or replace into snapshot_metrics(snapshot_id, name, value) values(?,?,?)",
                  (sid, name, float(value)))

    total = max(snap["users_total"], 1)
    for cat, n in snap["categories"].items():
        c.execute("insert or replace into snapshot_categories(snapshot_id, category, count, share) values(?,?,?,?)",
                  (sid, cat, int(n), round(int(n) / total, 4)))

    for port, d in (snap.get("inbounds") or {}).items():
        c.execute("insert or replace into snapshot_inbounds(snapshot_id, port, clients_total, clients_enabled) values(?,?,?,?)",
                  (sid, int(port), int(d["total"]), int(d["enabled"])))

    c.executemany(
        "insert or replace into user_facts(snapshot_id, tg_hash, category, created_at, last_seen,"
        " days_silent, has_key, banned, unsubscribed) values(?,?,?,?,?,?,?,?,?)",
        [(sid, f["tg_hash"], f["category"], f["created_at"], f["last_seen"],
          f["days_silent"], f["has_key"], f["banned"], f["unsubscribed"]) for f in snap["facts"]],
    )

    # дневной свод: агрегируем в одну строку на дату
    day = time.strftime("%Y-%m-%d", time.localtime(snap["taken_at"] / 1000))
    m = snap["metrics"]
    c.execute(
        "insert into daily_stats(day, users_new, users_active, users_banned, keys_issued, traffic_gb, payments_sum, payments_count)"
        " values(?,?,?,?,?,?,?,?)"
        " on conflict(day) do update set"
        " users_active=excluded.users_active, users_banned=excluded.users_banned,"
        " keys_issued=excluded.keys_issued, traffic_gb=excluded.traffic_gb,"
        " payments_sum=excluded.payments_sum, payments_count=excluded.payments_count",
        (day, snap["categories"].get("active", 0), snap["categories"].get("active", 0),
         snap["categories"].get("banned", 0), m.get("keys_enabled", 0),
         m.get("traffic_gb", 0.0), m.get("payments_sum", 0.0), m.get("payments_count", 0)),
    )

    c.execute("update runs set finished_at=?, status='ok', detail=? where id=?",
              (int(time.time() * 1000), f"snapshot {sid}, facts {len(snap['facts'])}", run_id))
    c.commit()

    # распределение по разным файлам-базам, чтобы можно было смотреть категории отдельно
    for cat in set(snap["categories"]) | set(CATEGORY_TITLES):
        rows = [f for f in snap["facts"] if f["category"] == cat]
        path = os.path.join(CATDIR, f"{cat}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["tg_hash", "created_at", "last_seen", "days_silent", "has_key", "banned", "unsubscribed"])
            for f in rows:
                w.writerow([f["tg_hash"], f["created_at"], f["last_seen"], f["days_silent"],
                            f["has_key"], f["banned"], f["unsubscribed"]])

    # краткий отчёт в stdout — его видно в логе крона и в GitHub Actions
    print(f"snapshot={sid} facts={len(snap['facts'])} users_total={snap['users_total']}")
    for cat, n in sorted(snap["categories"].items(), key=lambda x: -x[1]):
        print(f"  {cat:14} {n:5}  {n / total * 100:5.1f}%  {CATEGORY_TITLES.get(cat, '')}")
    print(f"ключей включено: {m.get('keys_enabled')} | трафик: {m.get('traffic_gb')} ГБ"
          f" | ARPU: {m.get('arpu')}")
    print(f"БД: {DB} | категории: {CATDIR}")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
