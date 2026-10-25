#!/usr/bin/env python3
"""Сборщик метрик VPN-инфраструктуры.

Запускается на DE (где живёт бот). Читает:
  - локальную базу бота  /opt/vpn-bot-telegam/data/vpn-bot.db
  - базу x-ui на RU       по SSH (только SELECT, база не копируется целиком)

Формирует JSON-снимок и отдаёт его writer.py на второй RU-сервер по SSH.
Персональные данные не выгружаются: telegram_id заменяется на sha256-хеш с солью,
username/ссылки/uuid не передаются вовсе.

Использование:
    ./collect.py            # полный цикл: собрать и записать
    ./collect.py --dry-run  # собрать и напечатать сводку, никуда не писать
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BOT_DB = "/opt/vpn-bot-telegam/data/vpn-bot.db"
RU_HOST = os.environ.get("RU_HOST", "88.151.114.24")
SALT = os.environ.get("METRICS_SALT", "vpn-metrics-static-salt")
SINK_HOST = os.environ.get("SINK_HOST", "135.106.178.226")
SINK_PORT = os.environ.get("SINK_PORT", "50222")
SINK_DIR = os.environ.get("SINK_DIR", "/opt/vpn-metrics")
# SSH-ключи: на DE доступ к RU и к хранилищу идёт своим ключом
RU_KEY = os.environ.get("RU_SSH_KEY", "/root/.ssh/id_de2ru")
SINK_KEY = os.environ.get("SINK_SSH_KEY", "/root/.ssh/id_de2ru")


def _key_args(path: str) -> list:
    return ["-i", path] if path and os.path.exists(path) else []

DAY = 86400
NOW_MS = int(time.time() * 1000)


def tg_hash(tg_id) -> str:
    return hashlib.sha256(f"{SALT}:{tg_id}".encode()).hexdigest()[:32]


def ms_to_days(ts_ms) -> int | None:
    if not ts_ms:
        return None
    return int((NOW_MS - int(ts_ms)) / 1000 / DAY)


# ---------------------------------------------------------------- бот (DE)
def read_bot(sqlite_path: str = BOT_DB) -> dict:
    import sqlite3

    c = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    users = [dict(r) for r in c.execute(
        "select telegram_id, email, client_uuid, created_at, last_seen,"
        " is_active, banned, unsubscribed_at, visits from users"
    )]
    pay = c.execute(
        "select count(*), coalesce(sum(case when amount > 0 then amount else 0 end), 0)"
        " from payments").fetchone()
    claims = c.execute("select count(*) from payments where amount = 0").fetchone()[0]
    c.close()
    return {"users": users, "payments_count": pay[0], "payments_sum": float(pay[1] or 0),
            "claims_count": claims}


# ---------------------------------------------------------------- x-ui (RU)
RU_QUERY = r"""
import sqlite3, json
c = sqlite3.connect("file:/etc/x-ui/x-ui.db?mode=ro", uri=True)
out = {"clients": [], "inbounds": []}
for port, in c.execute("select port from inbounds where enable=1"):
    out["inbounds"].append(port)
try:
    rows = c.execute(
        "select cl.email, cl.enable, cl.expiry_time, cl.total_gb, cl.limit_ip,"
        " coalesce(ct.up,0), coalesce(ct.down,0), coalesce(ct.total,0), ct.enable, coalesce(ct.last_online,0)"
        " from clients cl left join client_traffics ct on ct.email = cl.email"
    ).fetchall()
except Exception as e:
    out["error"] = str(e)
    rows = []
for r in rows:
    out["clients"].append({
        "email": r[0], "enable": r[1], "expiry": r[2], "total_gb": r[3],
        "limit_ip": r[4], "up": r[5], "down": r[6], "total": r[7], "ct_enable": r[8],
        "last_online": r[9],
    })
print(json.dumps(out))
"""


def read_ru() -> dict:
    p = subprocess.run(["ssh"] + _key_args(RU_KEY) + ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        f"root@{RU_HOST}", "python3 -"], input=RU_QUERY,
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"SSH к RU не удался: {p.stderr.strip()[:200]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- метрики
def classify(bot: dict, ru: dict) -> dict:
    users = bot["users"]
    by_email = {}
    for cl in ru.get("clients", []):
        e = cl.get("email")
        if e:
            by_email[e] = cl

    cats: dict[str, int] = {}
    facts = []
    traffic_bytes = 0
    keys_ok = 0

    for u in users:
        email = u.get("email") or ""
        cl = by_email.get(email)
        # активность: точнее брать last_online из x-ui (бот last_seen почти не пишет)
        online = (cl or {}).get("last_online") or 0
        seen_ms = max(int(u.get("last_seen") or 0), int(online))
        silent = ms_to_days(seen_ms)
        unsub = 1 if (u.get("unsubscribed_at") or 0) else 0
        banned = 1 if u.get("banned") else 0
        has_key = bool(u.get("client_uuid")) and bool(cl)

        if cl:
            traffic_bytes += (cl.get("up") or 0) + (cl.get("down") or 0)
            if cl.get("enable") and cl.get("ct_enable"):
                keys_ok += 1

        if banned:
            cat = "banned"
        elif unsub:
            cat = "unsubscribed"
        elif not u.get("client_uuid") or not cl:
            cat = "no_key"
        elif silent is None:
            cat = "never_seen"
        elif silent > 90:
            cat = "silent_90d"
        elif silent > 30:
            cat = "silent_30d"
        elif silent > 7:
            cat = "silent_7d"
        else:
            cat = "active"

        cats[cat] = cats.get(cat, 0) + 1
        facts.append({
            "tg_hash": tg_hash(u.get("telegram_id")),
            "category": cat,
            "created_at": u.get("created_at") or 0,
            "last_seen": u.get("last_seen") or 0,
            "days_silent": silent if silent is not None else -1,
            "has_key": int(has_key),
            "banned": banned,
            "unsubscribed": unsub,
        })

    total = len(users) or 1
    # клиенты x-ui, которых нет в базе бота — тоже считаем, иначе картина неполная
    seen_emails = {(u.get("email") or "") for u in users}
    client_only = 0
    for email, cl in by_email.items():
        if not email or email in seen_emails:
            continue
        client_only += 1
        silent = ms_to_days(cl.get("last_online") or 0)
        cat = "never_seen" if silent is None else ("silent_90d" if silent > 90 else
                                                   "silent_30d" if silent > 30 else
                                                   "silent_7d" if silent > 7 else "active")
        cats[cat] = cats.get(cat, 0) + 1
        facts.append({
            "tg_hash": tg_hash(f"email:{email}"),
            "category": cat,
            "created_at": 0,
            "last_seen": cl.get("last_online") or 0,
            "days_silent": silent if silent is not None else -1,
            "has_key": 1,
            "banned": 0,
            "unsubscribed": 0,
        })

    if client_only:
        total = len(users) + client_only
    metrics = {
        "users_total": total,
        "users_in_bot": len(users),
        "clients_only": client_only,
        "users_with_key": sum(1 for f in facts if f["has_key"]),
        "keys_enabled": keys_ok,
        "clients_total": len(ru.get("clients", [])),
        "clients_enabled": sum(1 for c in ru.get("clients", []) if c.get("enable")),
        "traffic_gb": round(traffic_bytes / 1024 ** 3, 2),
        # деления: доли и средние
        "share_active": round(cats.get("active", 0) / total, 4),
        "share_banned": round(cats.get("banned", 0) / total, 4),
        "share_unsub": round(cats.get("unsubscribed", 0) / total, 4),
        "share_silent_30d": round((cats.get("silent_30d", 0) + cats.get("silent_90d", 0)) / total, 4),
        "share_never_seen": round(cats.get("never_seen", 0) / total, 4),
        "avg_traffic_gb_per_client": round(traffic_bytes / 1024 ** 3 / max(len(ru.get("clients", [])), 1), 2),
        "payments_sum": bot["payments_sum"],
        "payments_count": bot["payments_count"],
        "claims_count": bot.get("claims_count", 0),
        "arpu": round(bot["payments_sum"] / total, 2),
        "conversion_key": round(sum(1 for f in facts if f["has_key"]) / total, 4),
    }

    inbounds: dict[int, dict] = {}
    for cl in ru.get("clients", []):
        port = 2087  # клиенты в этой сборке привязаны к основному инбаунду
        d = inbounds.setdefault(port, {"total": 0, "enabled": 0})
        d["total"] += 1
        d["enabled"] += 1 if (cl.get("enable") and cl.get("ct_enable")) else 0

    return {"metrics": metrics, "categories": cats, "facts": facts,
            "inbounds": inbounds, "users_total": len(users)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bot-db", default=BOT_DB)
    args = ap.parse_args()

    started = NOW_MS
    bot = read_bot(args.bot_db)
    ru = read_ru()
    data = classify(bot, ru)

    snapshot = {
        "taken_at": started,
        "source_host": os.uname().nodename,
        "users_total": data["metrics"]["users_total"],
        "clients_total": data["metrics"]["clients_total"],
        "metrics": data["metrics"],
        "categories": data["categories"],
        "inbounds": data["inbounds"],
        "facts": data["facts"],
        "started_at": started,
    }

    if args.dry_run:
        print(json.dumps({k: v for k, v in snapshot.items() if k != "facts"},
                         ensure_ascii=False, indent=2))
        print(f"фактов: {len(snapshot['facts'])}")
        return 0

    payload = json.dumps(snapshot, ensure_ascii=False)
    cmd = (f"mkdir -p {SINK_DIR}/data {SINK_DIR}/categories && "
           f"cat > /tmp/metrics_payload.json && "
           f"python3 {SINK_DIR}/writer.py /tmp/metrics_payload.json")
    p = subprocess.run(["ssh"] + _key_args(SINK_KEY) + ["-p", SINK_PORT, "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=15", f"root@{SINK_HOST}", cmd],
                       input=payload, capture_output=True, text=True, timeout=300)
    print(p.stdout.strip()[-2000:])
    if p.returncode != 0:
        print("ОШИБКА записи:", p.stderr.strip()[:400], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
