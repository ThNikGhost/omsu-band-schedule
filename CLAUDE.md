# smart_band_10 — расписание ОмГУ на Xiaomi Smart Band 10

Показывает расписание пар ОмГУ на браслете Xiaomi Smart Band 10. У браслета нет своего
интернета (`@system.fetch` на Vela недоступен), поэтому данные идут по цепочке:

```
eservice.omsu.ru  --(раз в 3 ч)-->  server/  --(HTTP + токен)-->  astrobox-plugin/  --(BLE interconnect)-->  band-app/
```

Браслет обязан полностью работать офлайн по кэшу: на iOS синхронизация возможна только
когда AstroBox открыт на переднем плане.

## Каталоги

| Путь | Что это |
|---|---|
| `server/` | FastAPI-сервер: тянет API вуза, нормализует, отдаёт компактный JSON и ICS |
| `shared/` | Контракт между компонентами: `schema.json`, `example.json`, `bells.json` |
| `band-app/` | Vela quick app для браслета (`.rpk`), package `ru.omsu.bandschedule` |
| `astrobox-plugin/` | Плагин AstroBox v2: Rust → WebAssembly (`wasm32-wasip2`), пакет `.abp`. Собирается в WSL — Smart App Control блокирует cargo.exe |
| `reference/` | **Только чтение.** Код старого проекта StudyHelper, источник проверенных решений |
| `docs/` | `VELA-RULES.md` — правила платформы браслета; `DECISIONS.md` — журнал решений и ограничений; `ORIGINAL_SPEC.md` — исходное ТЗ |

## Команды

```bash
# band-app
cd band-app && npm install && npm run gen
npm test          # 151 тест чистой логики, без эмулятора
npm run build     # dist/ru.omsu.bandschedule.debug.1.0.0.rpk
npx http-server preview -p 8123   # превью экранов в браузере
```

```bash
# server
cd server && uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
uv run uvicorn app.main:app --reload --port 8080
uv run python -m app.cli check-names --group 5028   # проверить словарь сокращений

# деплой (OptiPlex)
docker compose up -d --build
```

## Правила

- **Перед любой правкой `band-app/` — прочитать `docs/VELA-RULES.md`.** Нарушение правил Vela
  не ловится ни тестами, ни компилятором: приложение молча показывает чёрный экран и может
  подвесить браслет целиком. Один раз это уже произошло.
- **Секреты только через env.** Токены, `.env`, ключи подписи не коммитим (см. `.gitignore`).
- **`reference/` не редактируем** — оттуда только копируем и адаптируем.
- Факт о платформе (Vela, AstroBox), не подтверждённый документацией или экспериментом,
  не используется в коде. Всё проверенное и все найденные ограничения — в `docs/DECISIONS.md`.
- `docs/ORIGINAL_SPEC.md` — исходное ТЗ, локальный файл вне репозитория; часть фактов в нём устарела
  (см. `docs/DECISIONS.md` → «Устаревшие источники»). При расхождении побеждает `DECISIONS.md`.
- Сервер запускается строго в один воркер: снапшоты, rate limiter и планировщик живут в памяти.
- В `band-app/src/common/*.js` **не должно быть ни одного `@system.*`** — это граница,
  которая позволяет тестировать всю логику на Node без эмулятора.
- `band-app/src/common/bells.js` и `mock.js` генерируются (`npm run gen`), править вручную нельзя.

## Ключевые факты

- Группа: `МБС-301-О-01`, `group_id=5028`. Подгруппа (`/1` или `/2`) — настройка на телефоне, не на сервере.
- Таймзона везде `Asia/Omsk`. «Сегодня» — только `datetime.now(ZoneInfo(tz)).date()`.
- API вуза отдаёт всю историю с 2023 года одним ответом на 1.5 МБ; вперёд публикует ~10 дней.
- Полезная нагрузка на браслет — 4372 байта на 14 дней (замер на реальных данных 5028).
