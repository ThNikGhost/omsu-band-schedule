"""Operational helpers: find a group id, inspect normalisation, regenerate examples.

uv run python -m app.cli find-group "МБС-401"
uv run python -m app.cli check-names --group 5028
uv run python -m app.cli check-rooms --group 5028
uv run python -m app.cli gen-example --group 5028
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from app.bells import Bells
from app.config import Settings, get_settings
from app.hashing import payload_hash
from app.models import DayOut, LessonOut, ScheduleOut
from app.normalize.lesson import normalize_response
from app.normalize.room import format_room
from app.normalize.subject import Abbreviator
from app.store import SnapshotStore, atomic_write
from app.upstream.omsu import OmsuClient, build_client

DICT_CACHE = "dict_groups.json"
SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "shared"


async def _fetch(settings: Settings, group_id: int) -> dict[str, Any]:
    http = build_client(
        connect_timeout=settings.upstream_connect_timeout,
        read_timeout=settings.upstream_read_timeout,
    )
    try:
        client = OmsuClient(
            http,
            base_url=settings.upstream_base,
            max_response_bytes=settings.max_response_bytes,
            dict_timeout=settings.upstream_dict_timeout,
        )
        return await client.fetch_group(group_id)
    finally:
        await http.aclose()


def _load_payload(settings: Settings, group_id: int, source: str | None) -> dict[str, Any]:
    if source:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    return asyncio.run(_fetch(settings, group_id))


def _snapshot(settings: Settings, group_id: int, source: str | None):
    payload = _load_payload(settings, group_id, source)
    now = settings.now()
    return normalize_response(
        payload,
        group_id=group_id,
        window=settings.snapshot_window(now.date()),
        fetched_at=now,
    )


# --------------------------------------------------------------------- commands


def cmd_check_names(settings: Settings, args: argparse.Namespace) -> int:
    """Print every subject through the abbreviator; TRUNC means a rule is missing."""
    abbreviate = Abbreviator.from_yaml(settings.abbreviations_path)
    snapshot = _snapshot(settings, args.group, args.source)

    subjects = sorted({lesson.subject for lesson in snapshot.lessons}, key=len, reverse=True)
    if args.all:
        payload = _load_payload(settings, args.group, args.source)
        subjects = sorted(
            {
                x["lesson"].rsplit(" ", 1)[0].strip()
                for day in payload.get("data", [])
                for x in day.get("lessons", [])
            },
            key=len,
            reverse=True,
        )

    problems = 0
    for subject in subjects:
        result = abbreviate(subject)
        truncated = result.endswith(abbreviate.rules.ellipsis)
        over = len(result) > abbreviate.rules.max_len
        mark = "OVER!" if over else ("TRUNC" if truncated else "     ")
        if over or truncated:
            problems += 1
        print(f"{mark} {len(result):2d} | {subject} -> {result}")

    print(f"\n{len(subjects)} subjects, {problems} need a rule in abbreviations.yaml")
    return 1 if problems else 0


def cmd_check_rooms(settings: Settings, args: argparse.Namespace) -> int:
    payload = _load_payload(settings, args.group, args.source)
    values = sorted(
        {
            x.get("auditCorps") or ""
            for day in payload.get("data", [])
            for x in day.get("lessons", [])
        }
    )
    for value in values:
        print(f"{value!r:45} -> {format_room(value)!r}")
    print(f"\n{len(values)} distinct auditCorps values")
    return 0


def cmd_dump(settings: Settings, args: argparse.Namespace) -> int:
    snapshot = _snapshot(settings, args.group, args.source)
    print(
        json.dumps(
            json.loads(snapshot.model_dump_json()),
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


def cmd_gen_example(settings: Settings, args: argparse.Namespace) -> int:
    """Regenerate shared/example.json from real data."""
    abbreviate = Abbreviator.from_yaml(settings.abbreviations_path)
    snapshot = _snapshot(settings, args.group, args.source)
    now = settings.now()
    today = now.date()
    last = today + dt.timedelta(days=args.days - 1)

    by_date: dict[dt.date, list[LessonOut]] = {}
    for lesson in snapshot.lessons:
        if not (today <= lesson.date <= last):
            continue
        if args.subgroup is not None and lesson.subgroup not in (None, args.subgroup):
            continue
        by_date.setdefault(lesson.date, []).append(
            LessonOut(
                p=lesson.pair,
                n=abbreviate(lesson.subject),
                t=abbreviate.lesson_type(lesson.type),
                r=lesson.room,
                tc=lesson.teacher,
                sg=lesson.subgroup,
            )
        )

    days = [DayOut(d=date.isoformat(), l=by_date[date]) for date in sorted(by_date)]
    payload = ScheduleOut(
        gid=args.group,
        g=snapshot.group_name,
        gen=now.isoformat(timespec="seconds"),
        src=snapshot.fetched_at.isoformat(timespec="seconds"),
        stale=False,
        h=payload_hash([day.model_dump() for day in days]),
        days=days,
    )

    target = Path(args.out) if args.out else SHARED_DIR / "example.json"
    body = json.dumps(json.loads(payload.model_dump_json()), ensure_ascii=False, indent=1) + "\n"
    atomic_write(target, body.encode("utf-8"))

    compact = payload.model_dump_json()
    print(f"wrote {target}")
    print(f"{len(days)} days, {sum(len(d.l) for d in days)} lessons")
    print(f"wire size: {len(compact.encode('utf-8'))} bytes compact JSON")
    return 0


def cmd_bake(settings: Settings, args: argparse.Namespace) -> int:
    """Собирает расписание для полностью автономного браслета.

    Синхронизация через телефон требует, чтобы bluetooth-сессию держал AstroBox,
    а у браслета она одна — значит Mi Fitness в это время не работает
    (docs/DECISIONS.md). Чтобы не выбирать между расписанием и пульсом,
    расписание можно вшить прямо в приложение.

    В файл идёт две вещи:

    * `days` — реальные опубликованные дни от сегодня. Это правда, но вуз
      публикует неглубоко, обычно дней на десять вперёд.
    * `cycle` — двухнедельный шаблон по последним неделям. Им заполняются даты,
      до которых публикация ещё не дошла.

    Точность шаблона измерена на реальных данных группы 5028: 85–90% дней
    совпадают полностью. Ошибается он почти всегда в одну сторону — в жизни
    появляется пара, которой в шаблоне нет, — поэтому вычисленные дни помечены
    флагом `approx`, и приложение показывает их как приблизительные.
    """
    abbreviate = Abbreviator.from_yaml(settings.abbreviations_path)
    snapshot = _snapshot(settings, args.group, args.source)
    now = settings.now()
    today = now.date()

    def out(lesson) -> LessonOut:
        return LessonOut(
            p=lesson.pair,
            n=abbreviate(lesson.subject),
            t=abbreviate.lesson_type(lesson.type),
            r=lesson.room,
            tc=lesson.teacher,
            sg=lesson.subgroup,
        )

    def wanted(lesson) -> bool:
        return args.subgroup is None or lesson.subgroup in (None, args.subgroup)

    by_date: dict[dt.date, list[LessonOut]] = {}
    for lesson in snapshot.lessons:
        if wanted(lesson):
            by_date.setdefault(lesson.date, []).append(out(lesson))

    published = sorted(d for d in by_date if d >= today)
    days = [DayOut(d=d.isoformat(), l=by_date[d]) for d in published]

    # Чётность считается от понедельника-якоря, а не по номеру ISO-недели:
    # на браслете вычислить разницу дат тривиально, а номер ISO-недели — нет.
    anchor_monday = today - dt.timedelta(days=today.weekday())
    window_start = anchor_monday - dt.timedelta(weeks=args.weeks)

    cycle: dict[str, list[LessonOut]] = {}
    for date in sorted(by_date):
        if not (window_start <= date < anchor_monday + dt.timedelta(days=14)):
            continue
        parity = ((date - anchor_monday).days // 7) % 2
        # Свежие недели важнее старых, поэтому поздние перезаписывают ранние.
        cycle[f"{date.weekday()}-{parity}"] = by_date[date]

    baked = {
        "v": 1,
        "gid": args.group,
        "g": snapshot.group_name,
        "sg": args.subgroup,
        "gen": now.isoformat(timespec="seconds"),
        "src": snapshot.fetched_at.isoformat(timespec="seconds"),
        "anchor": anchor_monday.isoformat(),
        "days": [json.loads(day.model_dump_json()) for day in days],
        "cycle": {
            key: [json.loads(item.model_dump_json()) for item in value]
            for key, value in sorted(cycle.items())
        },
    }

    target = Path(args.out) if args.out else SHARED_DIR / "baked.json"
    body = json.dumps(baked, ensure_ascii=False, indent=1) + "\n"
    atomic_write(target, body.encode("utf-8"))

    lessons = sum(len(day.l) for day in days)
    print(f"wrote {target}")
    print(f"{len(days)} published days ({lessons} lessons), {len(cycle)} slots in the cycle")
    print(f"anchor Monday {anchor_monday}, cycle built from the last {args.weeks} weeks")
    return 0


def cmd_find_group(settings: Settings, args: argparse.Namespace) -> int:
    """Look up a group id by name.

    The dictionary endpoint the university frontend uses answers 504 every time
    we have tried it, so this walks three levels: live dictionary, local cache,
    then explicit probing of candidate ids.
    """
    store_dir = Path(settings.data_dir)
    cache_path = store_dir / DICT_CACHE

    if args.probe:
        return _probe(settings, args.probe)

    entries = None
    if not args.cache_only:
        try:
            entries = asyncio.run(_fetch_dict(settings))
            atomic_write(cache_path, json.dumps(entries, ensure_ascii=False).encode("utf-8"))
            print(f"fetched {len(entries)} entries, cached in {cache_path}", file=sys.stderr)
        except Exception as exc:
            print(f"dictionary unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)

    if entries is None and cache_path.exists():
        entries = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"using cached dictionary from {cache_path}", file=sys.stderr)

    if entries is None:
        print(
            "No dictionary available. Options:\n"
            "  * open https://eservice.omsu.ru/schedule/group in the browser, pick the group,\n"
            "    and read the id from the URL or the DevTools network tab;\n"
            "  * or probe a candidate id: python -m app.cli find-group --probe <id>",
            file=sys.stderr,
        )
        return 2

    needle = (args.name or "").casefold()
    matches = [e for e in entries if needle in json.dumps(e, ensure_ascii=False).casefold()]
    for entry in matches[:50]:
        print(json.dumps(entry, ensure_ascii=False))
    print(f"\n{len(matches)} matches", file=sys.stderr)
    return 0 if matches else 1


async def _fetch_dict(settings: Settings) -> list[dict[str, Any]]:
    http = build_client(
        connect_timeout=settings.upstream_connect_timeout,
        read_timeout=settings.upstream_dict_timeout,
    )
    try:
        client = OmsuClient(
            http,
            base_url=settings.upstream_base,
            max_response_bytes=settings.max_response_bytes,
            dict_timeout=settings.upstream_dict_timeout,
        )
        data = await client.fetch_dict("groups")
    finally:
        await http.aclose()

    if isinstance(data, dict):
        data = data.get("data", [])
    return list(data or [])


def _probe(settings: Settings, group_id: int) -> int:
    """Fetch one id and report which group it belongs to. Downloads ~1.5 MB."""
    print(f"probing group {group_id} (this downloads about 1.5 MB)...", file=sys.stderr)
    try:
        snapshot = _snapshot(settings, group_id, None)
    except Exception as exc:
        print(f"group {group_id}: {type(exc).__name__}: {exc}")
        return 1
    print(
        json.dumps(
            {
                "group_id": group_id,
                "group_name": snapshot.group_name,
                "upstream_days": snapshot.upstream_days,
                "upstream_lessons": snapshot.upstream_lessons,
                "lessons_in_window": len(snapshot.lessons),
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    """Fetch and persist a snapshot without running the server."""
    from app.service import ScheduleService

    async def run() -> int:
        http = build_client(
            connect_timeout=settings.upstream_connect_timeout,
            read_timeout=settings.upstream_read_timeout,
        )
        try:
            store = SnapshotStore(settings.data_dir)
            store.load_all(settings.groups)
            service = ScheduleService(
                settings,
                store,
                OmsuClient(http, base_url=settings.upstream_base),
                Abbreviator.from_yaml(settings.abbreviations_path),
                Bells.load(settings.bells_path),
            )
            snapshot = await service.sync_group(args.group)
        finally:
            await http.aclose()
        print(f"group {snapshot.group_id} ({snapshot.group_name}): {len(snapshot.lessons)} lessons")
        return 0

    return asyncio.run(run())


# ----------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_source(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--group", type=int, default=5028)
        p.add_argument("--source", help="read a saved API response instead of the network")
        return p

    names = with_source(
        sub.add_parser("check-names", help="run subjects through abbreviations.yaml")
    )
    names.add_argument(
        "--all", action="store_true", help="include raw names, not only windowed ones"
    )
    names.set_defaults(func=cmd_check_names)

    with_source(
        sub.add_parser("check-rooms", help="run auditCorps through format_room")
    ).set_defaults(func=cmd_check_rooms)
    with_source(sub.add_parser("dump", help="print a snapshot")).set_defaults(func=cmd_dump)

    example = with_source(sub.add_parser("gen-example", help="regenerate shared/example.json"))
    example.add_argument("--days", type=int, default=14)
    example.add_argument("--subgroup", type=int, default=None)
    example.add_argument("--out", default=None)
    example.set_defaults(func=cmd_gen_example)

    bake = with_source(sub.add_parser("bake", help="regenerate shared/baked.json for offline use"))
    bake.add_argument("--subgroup", type=int, default=None)
    bake.add_argument("--weeks", type=int, default=4, help="how far back to look for the cycle")
    bake.add_argument("--out", default=None)
    bake.set_defaults(func=cmd_bake)

    find = sub.add_parser("find-group", help="look up a group id by name")
    find.add_argument("name", nargs="?", default="")
    find.add_argument("--probe", type=int, help="check one candidate id directly")
    find.add_argument("--cache-only", action="store_true", help="skip the network, use the cache")
    find.set_defaults(func=cmd_find_group)

    sync = sub.add_parser("sync", help="fetch and persist one group")
    sync.add_argument("--group", type=int, default=5028)
    sync.set_defaults(func=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    return int(args.func(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
