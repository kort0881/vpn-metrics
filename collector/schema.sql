-- Схема хранилища метрик (SQLite на втором RU-сервере).
-- Персональные данные не хранятся: только telegram_id (хеш) и агрегаты.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- Каждый запуск сборщика = снимок
CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at        INTEGER NOT NULL,          -- unix ms
    source_host     TEXT    NOT NULL,           -- откуда снято
    users_total     INTEGER NOT NULL DEFAULT 0,
    clients_total   INTEGER NOT NULL DEFAULT 0,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken ON snapshots(taken_at);

-- Метрики по снимку: name -> value (считаются в report.py)
CREATE TABLE IF NOT EXISTS snapshot_metrics (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    value           REAL    NOT NULL,
    PRIMARY KEY (snapshot_id, name)
);

-- Категории пользователей: у каждого снимка своё распределение
CREATE TABLE IF NOT EXISTS snapshot_categories (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    category        TEXT    NOT NULL,
    count           INTEGER NOT NULL,
    share           REAL    NOT NULL,          -- доля от users_total (деление)
    PRIMARY KEY (snapshot_id, category)
);

-- Разбивка клиентов по инбаундам
CREATE TABLE IF NOT EXISTS snapshot_inbounds (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    port            INTEGER NOT NULL,
    clients_total   INTEGER NOT NULL,
    clients_enabled INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, port)
);

-- Обфусцированные записи для истории (без username/ссылок/uuid)
CREATE TABLE IF NOT EXISTS user_facts (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    tg_hash         TEXT    NOT NULL,          -- sha256(telegram_id + salt)
    category        TEXT    NOT NULL,
    created_at      INTEGER,
    last_seen       INTEGER,
    days_silent     INTEGER,
    has_key         INTEGER NOT NULL DEFAULT 0,
    banned          INTEGER NOT NULL DEFAULT 0,
    unsubscribed    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, tg_hash)
);
CREATE INDEX IF NOT EXISTS idx_user_facts_cat ON user_facts(category);

-- Ежедневный свод (для графиков и «деления»: retention, отток)
CREATE TABLE IF NOT EXISTS daily_stats (
    day             TEXT PRIMARY KEY,          -- YYYY-MM-DD
    users_new       INTEGER NOT NULL DEFAULT 0,
    users_active    INTEGER NOT NULL DEFAULT 0,
    users_banned    INTEGER NOT NULL DEFAULT 0,
    keys_issued     INTEGER NOT NULL DEFAULT 0,
    traffic_gb      REAL    NOT NULL DEFAULT 0,
    payments_sum    REAL    NOT NULL DEFAULT 0,
    payments_count  INTEGER NOT NULL DEFAULT 0
);

-- Журнал запусков: чтобы видеть, что крон реально работает
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    status      TEXT NOT NULL,                 -- ok / error
    detail      TEXT
);
