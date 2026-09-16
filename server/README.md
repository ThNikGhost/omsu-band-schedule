# band-schedule server

Pulls the OmSU schedule every 3 hours, normalises it, and serves a compact JSON
payload (about 4.4 KB for 14 days) plus an ICS feed.

## Why a server at all

The university API answers with **1.5 MB** of history going back to September 2023
in a single response, subject names up to 67 characters, `"-"` for missing
teachers and `"4-0"` for unknown rooms. None of that fits a 212x520 watch screen
or a BLE link. The server does that work once, on a machine that has memory and
a real network.

## Quick start

```bash
cd server && uv sync
cp .env.example .env    # then fill in API_TOKENS
```

```bash
uv run python -m pytest -q && uv run ruff check .
```

```bash
uv run uvicorn app.main:app --reload --port 8080
```

Generate tokens with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/schedule?group=&days=&subgroup=` | Bearer or `?token=` | `ETag` = `h`, supports `If-None-Match` -> 304 |
| GET | `/api/v1/calendar/{group}.ics?token=&subgroup=` | `?token=` | Subscribe from a phone calendar |
| GET | `/api/v1/bells` | Bearer or `?token=` | The bell schedule the watch uses |
| GET | `/health` | none | 200 even when the university is down |
| POST | `/api/v1/admin/refresh?group=` | `ADMIN_TOKEN` | Forces a sync |

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/schedule?group=5028&days=14&subgroup=1" | python -m json.tool
```

A second request with `If-None-Match: "<h>"` must come back `304`.

### Response shape

Keys are short because this eventually travels over BLE. See `shared/schema.json`
for the full contract and `shared/example.json` for a real sample.

```json
{"v":1,"gid":5028,"g":"МБС-301-О-01","gen":"...","src":"...","stale":false,"h":"70bbe23f4e25",
 "days":[{"d":"2026-09-16","l":[{"p":1,"n":"Методы вычислений","t":"Практ","r":"4-303","tc":"Макаров С. Е.","sg":null}]}]}
```

Things clients must handle:

* **`days` may be shorter than requested, or empty.** The university publishes
  only about ten days ahead. This is normal, not an error.
* **`r` and `tc` may be `null`** — the API genuinely has lessons with no known
  room (`4-0`, 233 of them) and no teacher (`-`, 189 of them).
* **`stale: true`** means the upstream has been unreachable for more than two
  fetch intervals. The data is the last good snapshot; show it, but say it is old.

## Configuration

Everything comes from the environment; see `.env.example` for the full list with
comments. The ones worth thinking about:

| Variable | Default | Meaning |
|---|---|---|
| `GROUPS` | `5028` | Group ids this instance will serve. Nothing else is accepted. |
| `API_TOKENS` | — | Comma separated. One per person, so they rotate independently. |
| `ADMIN_TOKEN` | empty | Empty disables `/admin/refresh` entirely. |
| `FETCH_INTERVAL_HOURS` | `3` | Also drives when data is considered stale (2x). |
| `DAYS_AHEAD_MAX` | `21` | Upper bound for `?days=`. |
| `ICS_PAST_DAYS` | `14` | History kept for the calendar feed only. |

## CLI

```bash
uv run python -m app.cli check-names --group 5028
```

Prints every subject through `abbreviations.yaml`. A `TRUNC` marker means a
subject is being cut off and needs a rule. Ship with zero markers.

```bash
uv run python -m app.cli check-rooms --group 5028
```

```bash
uv run python -m app.cli gen-example --group 5028 --days 14
```

Regenerates `shared/example.json`, which the tests validate against the schema.

```bash
uv run python -m app.cli find-group "МБС-401"
```

Looks up a group id. Note: the dictionary endpoint the university frontend uses
(`/schedule/backend/dict/groups`) currently answers `504 Gateway Time-out` every
time, so this falls back to a local cache and then to `--probe <id>`. The
simplest reliable route is still to pick the group at
<https://eservice.omsu.ru/schedule/group> and read the id from the network tab.

## Deployment

Docker, from the repository root (the build context needs `shared/`):

```bash
mkdir -p data && sudo chown 1000:1000 data
```

```bash
docker compose up -d --build
```

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

The container publishes plain HTTP on 8080. TLS and the domain are left to your
own reverse proxy.

**Do not raise `--workers`.** Snapshots, the rate limiter and the scheduler all
live in process memory; a second worker means a second scheduler hitting the
university twice as often and a rate limit that counts half the requests.

The healthcheck watches `/health`, which returns 200 even when the university
API is failing. That is deliberate: restarting the container over an upstream
problem would throw away the in-memory state and fix nothing.

## Local development note

The project targets Python 3.12 (that is what the Docker image runs). If uv's
downloaded interpreters are blocked by Windows Application Control, point it at
a system Python instead:

```bash
uv sync --python "C:\Users\<you>\AppData\Local\Python\pythoncore-3.14-64\python.exe"
```

Run tests as `uv run python -m pytest`, not `uv run pytest`: the generated
`pytest.exe` shim in `.venv/Scripts` trips the same policy.

## Layout

```
app/
├── main.py          FastAPI app, lifespan, wiring
├── config.py        Settings; the only source of "now"
├── models.py        Snapshot (full values) and the short-key wire models
├── service.py       sync_group, build_payload, health
├── scheduler.py     background loop with backoff
├── store.py         JSON snapshots, atomic writes
├── hashing.py       content hash and ETag matching
├── ics.py           calendar feed
├── normalize/       room, teacher, subject, lesson
├── upstream/        HTTP client and retry
└── api/             routes
```

Storage is plain JSON files, not SQLite: one writer, reads served from memory,
dozens of records per group, no queries. A schema and migrations would earn
nothing, and a JSON file can be read by eye on the server.

Parts of `normalize/` and `upstream/retry.py` are adapted from
`reference/studyhelper/`; each module says what was taken and what was changed
and why.
