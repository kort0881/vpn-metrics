import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITER = os.path.join(ROOT, "collector", "writer.py")
SCHEMA = os.path.join(ROOT, "collector", "schema.sql")


def make_payload():
    return {
        "taken_at": 1792930000000,
        "started_at": 1792930000000,
        "source_host": "test-host",
        "users_total": 4,
        "clients_total": 3,
        "metrics": {
            "users_total": 4,
            "keys_enabled": 2,
            "traffic_gb": 12.5,
            "share_active": 0.25,
            "arpu": 0.0,
        },
        "categories": {"active": 1, "silent_30d": 1, "banned": 1, "no_key": 1},
        "inbounds": {"2053": {"total": 3, "enabled": 2}},
        "facts": [
            {"tg_hash": "a" * 32, "category": "active", "created_at": 1, "last_seen": 2,
             "days_silent": 1, "has_key": 1, "banned": 0, "unsubscribed": 0},
            {"tg_hash": "b" * 32, "category": "banned", "created_at": 1, "last_seen": 2,
             "days_silent": 40, "has_key": 1, "banned": 1, "unsubscribed": 0},
        ],
    }


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="metrics-test-")
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)
        with open(os.path.join(self.tmp, "schema.sql"), "w") as f:
            f.write(open(SCHEMA).read())
        self.payload = os.path.join(self.tmp, "payload.json")
        with open(self.payload, "w") as f:
            json.dump(make_payload(), f)

    def test_writes_snapshot_and_categories(self):
        env = dict(os.environ, METRICS_DIR=self.tmp)
        p = subprocess.run([sys.executable, WRITER, self.payload],
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

        db = os.path.join(self.tmp, "data", "metrics.db")
        c = sqlite3.connect(db)
        self.assertEqual(c.execute("select count(*) from snapshots").fetchone()[0], 1)
        # доли посчитаны делением от users_total
        share = c.execute("select share from snapshot_categories where category='active'").fetchone()[0]
        self.assertAlmostEqual(share, 0.25, places=4)
        # все категории с ненулевым счётчиком сохранены
        cats = {r[0] for r in c.execute("select category from snapshot_categories")}
        self.assertEqual(cats, {"active", "silent_30d", "banned", "no_key"})
        # факты и CSV по категориям
        self.assertEqual(c.execute("select count(*) from user_facts").fetchone()[0], 2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "categories", "active.csv")))
        # запуск отмечен как успешный
        self.assertEqual(c.execute("select status from runs").fetchone()[0], "ok")
        c.close()

    def test_second_run_keeps_history(self):
        env = dict(os.environ, METRICS_DIR=self.tmp)
        for _ in range(2):
            subprocess.run([sys.executable, WRITER, self.payload], env=env,
                           capture_output=True, text=True)
        c = sqlite3.connect(os.path.join(self.tmp, "data", "metrics.db"))
        self.assertEqual(c.execute("select count(*) from snapshots").fetchone()[0], 2)
        # daily_stats агрегируется в одну строку на день, а не дублируется
        self.assertEqual(c.execute("select count(*) from daily_stats").fetchone()[0], 1)
        c.close()


if __name__ == "__main__":
    unittest.main()
