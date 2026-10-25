# vpn-metrics

Сбор и хранение метрик VPN-инфраструктуры: база бота (DE) + база x-ui (RU),
расчёт долей и динамики, хранение на отдельном RU-сервере. **В репозитории нет данных** —
только код: всё, что похоже на базу или дамп, в `.gitignore`.

## Как это работает

```
DE (бот)                        RU (вход)              второй RU (хранилище)
┌──────────────────┐   SSH    ┌──────────────┐   SSH   ┌────────────────────┐
│ collect.py       │─────────▶│ x-ui.db      │────────▶│ writer.py          │
│ vpn-bot.db       │  SELECT  │ (только чтение)│        │ metrics.db (SQLite)│
└──────────────────┘          └──────────────┘         │ categories/*.csv   │
        ▲                                              └────────────────────┘
        │ cron каждый час (17 * * * *)
        │ GitHub Actions раз в сутки — проверка кода и тесты
```

- `collector/collect.py` — снимает снимок, считает метрики, `telegram_id` заменяет на `sha256(salt:id)`;
  username, uuid и ссылки не выгружаются
- `collector/writer.py` — пишет снимок в SQLite: снимки, метрики, категории с долями,
  разбивку по инбаундам, обфусцированные факты, дневной свод, журнал запусков
- `collector/report.py` — отчёт: последний снимок, категории, динамика день ко дню, `daily_stats`
- `collector/schema.sql` — схема хранилища

## Категории (считаются все, включая тех, кто только зашёл в канал)

| категория | смысл |
|---|---|
| `active` | заходили в течение 7 дней |
| `silent_7d` | молчат 7–30 дней |
| `silent_30d` | молчат 30–90 дней |
| `silent_90d` | молчат больше 90 дней |
| `never_seen` | ни разу не заходили в бота |
| `no_key` | нет ключа |
| `unsubscribed` | отписались от канала |
| `banned` | забанены |

Доли (`share`) считаются делением на общее число пользователей, средние — на число клиентов.
Каждая категория дополнительно выгружается в `categories/<категория>.csv` — «распределены по разным базам».

## Метрики, которые считаются

`users_total`, `users_with_key`, `keys_enabled`, `clients_total`, `clients_enabled`,
`traffic_gb`, `share_active`, `share_banned`, `share_unsub`, `share_silent_30d`,
`share_never_seen`, `avg_traffic_gb_per_client`, `payments_sum`, `payments_count`, `arpu`, `conversion_key`.

## Установка

```bash
# 1) хранилище на втором RU-сервере
SINK_HOST=135.106.178.226 SINK_PORT=50222 ./deploy/install_sink.sh

# 2) код + cron каждый час на DE
DE_HOST=144.31.198.66 ./deploy/install_cron.sh

# 3) проверка
cd /opt/vpn-metrics-src && ./collector/collect.py --dry-run
./collector/collect.py
ssh -p 50222 root@135.106.178.226 'python3 /opt/vpn-metrics/report.py'
```

## GitHub Actions

`.github/workflows/metrics.yml` запускается ежедневно в 03:00 UTC и при ручном запуске.
Без секретов он только проверяет код и гоняет тесты — это безопасно для публичного репозитория.
Чтобы включить сбор из Actions, задай:

- secrets: `METRICS_SSH_KEY` (приватный ключ), `METRICS_SALT`
- vars: `METRICS_ENABLED=true`, `DE_HOST`, `RU_HOST`, `SINK_HOST`, `SINK_PORT`

Рекомендуемая схема — сбор по cron на самом DE (секреты не нужны в GitHub),
Actions отвечает за проверку кода и тесты.

## Требования

- Python 3.10+ (только стандартная библиотека)
- SSH-доступ: DE → RU (x-ui) и DE → второй RU (хранилище)
