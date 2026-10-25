#!/usr/bin/env python3
"""Отчёты по накопленным метрикам: динамика, доли, сравнение дня ко дню.

    ./report.py              # последний снимок + динамика
    ./report.py --days 7     # сравнить с состоянием N дней назад
"""
from __future__ import annotations

import argparse
import os
import sqlite3

BASE = os.environ.get("METRICS_DIR", "/opt/vpn-metrics")
DB = os.path.join(BASE, "data", "metrics.db")


def pct(a: float, b: float) -> str:
    if not b:
        return "—"
    return f"{(a - b) / b * 100:+.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"БД не найдена: {args.db}")
        return 1

    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    snaps = c.execute("select id, taken_at, users_total, clients_total from snapshots order by taken_at desc limit 2").fetchall()
    if not snaps:
        print("снимков нет")
        return 1

    sid, taken, ut, ct = snaps[0]
    print(f"последний снимок: {sid}, users={ut}, clients={ct}")

    print("\nкатегории:")
    for cat, n, share in c.execute("select category, count, share from snapshot_categories where snapshot_id=? order by count desc", (sid,)):
        print(f"  {cat:14} {n:5}  {share * 100:5.1f}%")

    print("\nключевые метрики:")
    for name, value in c.execute("select name, value from snapshot_metrics where snapshot_id=? order by name", (sid,)):
        print(f"  {name:28} {value}")

    if len(snaps) > 1:
        sid2, _, ut2, ct2 = snaps[1]
        print(f"\nдинамика к предыдущему снимку ({sid2}):")
        print(f"  users:   {ut} ({pct(ut, ut2)})")
        print(f"  clients: {ct} ({pct(ct, ct2)})")
        m_now = dict(c.execute("select name, value from snapshot_metrics where snapshot_id=?", (sid,)))
        m_old = dict(c.execute("select name, value from snapshot_metrics where snapshot_id=?", (sid2,)))
        for name in ("traffic_gb", "keys_enabled", "share_active", "arpu"):
            if name in m_now and name in m_old:
                print(f"  {name:16} {m_now[name]} ({pct(m_now[name], m_old[name])})")

    print("\nдни (daily_stats):")
    for day, new, act, ban, keys, gb, pay, pc in c.execute(
            "select day, users_new, users_active, users_banned, keys_issued, traffic_gb, payments_sum, payments_count"
            " from daily_stats order by day desc limit 7"):
        print(f"  {day}: активных {act}, забанено {ban}, ключей {keys}, трафик {gb} ГБ, платежи {pay} ({pc})")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
