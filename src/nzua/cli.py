"""Command line entry point: `python -m nzua <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The Windows console defaults to a legacy code page that mangles Ukrainian
# text. Force UTF-8 so prompts and the plan table are readable.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from .schedule import (
    WEEKDAY_LABELS_UK,
    load_schedule,
    parse_month,
    plan_month,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_PATH = PROJECT_ROOT / "schedule.yaml"


def _print_plan(tasks, year: int, month: int) -> None:
    print(f"Місяць: {year}-{month:02d}. Стовпчиків до створення: {len(tasks)}")
    print()
    header = f"{'Предмет':<12} {'Клас':<6} {'Дата':<12} {'День':<12} {'Урок':<5} Кабінет"
    print(header)
    print("-" * len(header))
    for task in tasks:
        slot = task.slot
        print(
            f"{slot.subject:<12} {slot.class_name:<6} "
            f"{task.date.isoformat():<12} "
            f"{WEEKDAY_LABELS_UK[slot.weekday]:<12} "
            f"{slot.lesson_no:<5} {slot.cabinet}"
        )
    print()
    print("Кожен рядок створюється один раз із повторенням «щотижня до кінця місяця».")


BROWSER_MODES = {
    "attach": "звичайний Chrome із портом налагодження; Playwright лише "
    "під'єднується (за замовчуванням — єдиний режим, який проходить "
    "перевірку Cloudflare на nz.ua)",
    "launch": "Chrome, запущений самим Playwright — nz.ua його блокує, "
    "лишено для діагностики",
    "edge": "те саме через Microsoft Edge",
}


SLOW_MO_HELP = "Затримка між діями браузера, мс (щоб було видно, що робиться)."


def _add_browser_flag(parser: argparse.ArgumentParser) -> None:
    """Every command needs the same choice of how to reach a browser."""
    parser.add_argument(
        "--browser",
        choices=sorted(BROWSER_MODES),
        default="attach",
        help="; ".join(f"{name}: {text}" for name, text in BROWSER_MODES.items()),
    )


DEFAULT_PLANNING_SOURCE = Path.home() / "Desktop" / "планування"
PLANNING_DIR = PROJECT_ROOT / "planning"


def cmd_import_planning(args: argparse.Namespace) -> int:
    """Convert the .docx calendar plans into YAML we can read and correct."""
    from .planning import DOCX_SOURCES, parse_planning_docx, write_plan

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"Помилка: немає теки {source_dir}", file=sys.stderr)
        return 2

    failed = 0
    for source in DOCX_SOURCES:
        docx = source_dir / source.filename
        if not docx.exists():
            print(f"  ПРОПУЩЕНО {source.filename}: файла немає", file=sys.stderr)
            failed += 1
            continue
        try:
            plan = parse_planning_docx(docx, source.subject, source.grade)
        except Exception as exc:
            print(f"  ПОМИЛКА {source.filename}: {exc}", file=sys.stderr)
            failed += 1
            continue
        out = write_plan(plan, PLANNING_DIR / source.output)
        print(
            f"  {source.filename:<18} -> {out.name:<20} "
            f"{plan.subject} {plan.grade} клас, {len(plan.lessons)} уроків"
        )
        print(f"      перший: {plan.lessons[0].topic[:70]}")
        print(f"     останній: {plan.lessons[-1].topic[:70]}")
    return 1 if failed else 0


def cmd_recon(args: argparse.Namespace) -> int:
    from .browser import open_browser
    from .recon import run_recon

    with open_browser(mode=args.browser) as page:
        run_recon(page)
    return 0


def cmd_add_columns(args: argparse.Namespace) -> int:
    schedule = load_schedule(SCHEDULE_PATH)
    try:
        year, month = parse_month(args.month)
        tasks = plan_month(
            schedule, year, month, subject=args.subject, class_name=args.class_name
        )
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    if not tasks:
        print("За цими фільтрами уроків немає.")
        return 0

    _print_plan(tasks, year, month)

    if args.dry_run:
        print("\n--dry-run: нічого не створено.")
        return 0

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_tasks

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_tasks(page, schedule, tasks)


def cmd_fill_topics(args: argparse.Namespace) -> int:
    """Fill lesson topics from the calendar plans."""
    from .planning import load_plan
    from .runner import journals_of

    schedule = load_schedule(SCHEDULE_PATH)
    try:
        targets = journals_of(schedule, args.subject, args.class_name)
        plans = {
            pair: load_plan(PROJECT_ROOT / schedule.plan_path(*pair))
            for pair in targets
        }
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    print(f"Журналів: {len(targets)}")
    for (subject, class_name), plan in plans.items():
        print(
            f"  {subject:<12} {class_name:<6} {plan.source:<18} "
            f"{len(plan.lessons)} уроків"
        )

    if args.dry_run:
        print()
        print("--dry-run: журнал не читаю, показую початок планування.")
        for (subject, class_name), plan in plans.items():
            print(f"  {subject} {class_name}:")
            for lesson in plan.lessons[: args.count or 3]:
                print(f"    № {lesson.number:<4} {lesson.topic[:80]}")
        return 0

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_fill_topics

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_fill_topics(
            page,
            schedule,
            subject=args.subject,
            class_name=args.class_name,
            count=args.count,
            resync=args.resync,
        )


def cmd_dump_homework(args: argparse.Namespace) -> int:
    """Collect homework already entered on the site into homework/*.yaml."""
    schedule = load_schedule(SCHEDULE_PATH)

    from_classes = tuple(
        name.strip() for name in (args.from_class or "").split(",") if name.strip()
    )
    try:
        for name in from_classes or (None,):
            schedule.filter(subject=args.subject, class_name=name)
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_dump_homework

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_dump_homework(
            page,
            schedule,
            semester=args.semester,
            from_classes=from_classes,
            subject=args.subject,
            dry_run=args.dry_run,
            list_only=args.semester_list,
        )


def cmd_check(args: argparse.Namespace) -> int:
    """Read the journals over and report what does not add up. Writes nothing."""
    schedule = load_schedule(SCHEDULE_PATH)
    try:
        schedule.filter(subject=args.subject, class_name=args.class_name)
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_check

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_check(
            page, schedule, subject=args.subject, class_name=args.class_name
        )


def _deletion_range(args: argparse.Namespace):
    """The dates to delete, from either --last-week or --from/--to."""
    from datetime import date

    from .lessons import last_week

    if args.last_week:
        if args.date_from or args.date_to:
            raise ValueError("--last-week не поєднується з --from/--to.")
        return last_week(*parse_month(args.last_week))
    if not args.date_from:
        raise ValueError("Вкажи --last-week YYYY-MM або --from YYYY-MM-DD.")
    try:
        start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to) if args.date_to else start
    except ValueError:
        raise ValueError("Дати пишуться як YYYY-MM-DD, напр. 2026-10-26.") from None
    if end < start:
        raise ValueError(f"--to {end} раніше за --from {start}.")
    return start, end


def cmd_delete_lessons(args: argparse.Namespace) -> int:
    """Delete the lesson columns of a date range."""
    schedule = load_schedule(SCHEDULE_PATH)
    try:
        start, end = _deletion_range(args)
        schedule.filter(subject=args.subject, class_name=args.class_name)
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_delete_lessons

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_delete_lessons(
            page,
            schedule,
            start,
            end,
            subject=args.subject,
            class_name=args.class_name,
            dry_run=args.dry_run,
            force=args.force,
        )


def cmd_set_lesson_types(args: argparse.Namespace) -> int:
    """Set lab and test lesson types from the topics already written."""
    schedule = load_schedule(SCHEDULE_PATH)
    try:
        schedule.filter(subject=args.subject, class_name=args.class_name)
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_set_lesson_types

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_set_lesson_types(
            page,
            schedule,
            subject=args.subject,
            class_name=args.class_name,
            dry_run=args.dry_run,
        )


def cmd_run_month(args: argparse.Namespace) -> int:
    """A whole month for every class: create the columns, then fill the topics."""
    schedule = load_schedule(SCHEDULE_PATH)
    try:
        year, month = parse_month(args.month)
        tasks = plan_month(schedule, year, month)
    except ValueError as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2

    _print_plan(tasks, year, month)
    print()
    print(f"Далі — теми уроків у всіх {len(set(t.journal for t in tasks))} журналах.")

    if args.dry_run:
        print()
        print("--dry-run: нічого не створено і не заповнено.")
        return 0

    from .selectors import require_ready

    require_ready()

    from .browser import open_browser
    from .runner import run_month

    with open_browser(mode=args.browser, slow_mo=args.slow_mo) as page:
        return run_month(page, schedule, tasks, count=args.count)


HELP_DESCRIPTION = """\
Автоматизація журналу вчителя на nz.ua: стовпчики уроків за розкладом, теми
уроків за календарним плануванням і домашні завдання, зібрані з журналів.

Браузер завжди видимий — видно кожну дію. Нічого не робиться мовчки: усе, що
скрипт записав, лягає і в консоль, і в run-РРРР-ММ-ДД.log.
"""

HELP_EPILOG = """\
Порядок за місяць
  1. add-columns   створює стовпчики уроків за schedule.yaml
  2. fill-topics   пише теми в ті стовпчики (без них нема куди писати)
  run-month робить обидва кроки в одному сеансі браузера.

Раз на семестр
  import-planning  розбирає .docx планування у planning/*.yaml
  dump-homework    збирає ДЗ із журналів у homework/*.yaml

Правки
  delete-lessons   видаляє стовпчики за датами, напр. канікули в кінці місяця
  set-lesson-types ставить тип «Лабораторна/Контрольна робота» за темою

Коли щось не так
  check            показує, що не збігається, і нічого не змінює
  recon            зберігає розмітку сайту, якщо змінились селектори

Файли
  schedule.yaml     розклад, і де лежать планування та ДЗ
  planning/*.yaml   теми уроків за паралелями
  homework/*.yaml   домашні завдання за паралелями
  .env              NZ_LOGIN і NZ_PASSWORD

Приклади
  python -m nzua add-columns --month 2026-09 --dry-run
  python -m nzua run-month --month 2026-09 --count 3
  python -m nzua check --class 9-А
  python -m nzua dump-homework --from 9-А,9-Б,9-В
  python -m nzua fill-topics --class 9-Б --count 0
  python -m nzua delete-lessons --last-week 2026-10 --dry-run
  python -m nzua set-lesson-types --class 9-А

Докладніше про команду:  python -m nzua <команда> --help
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nzua",
        description=HELP_DESCRIPTION,
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="команда", required=True)

    def command(name: str, **kwargs) -> argparse.ArgumentParser:
        """A subcommand whose own --help keeps the layout of its description."""
        return sub.add_parser(
            name,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            **kwargs,
        )

    recon = command(
        "recon",
        help="Розвідка: пройти сайт разом зі скриптом і зберегти розмітку.",
        description="""\
Проходить сайт разом із тобою і зберігає розмітку в recon/: HTML сторінок,
список полів і випадних списків, знімки екрана. Нічого не змінює.

Потрібно тільки тоді, коли nz.ua змінив верстку і селектори в
src/nzua/selectors.py перестали знаходити елементи.""",
    )
    _add_browser_flag(recon)
    recon.set_defaults(func=cmd_recon)

    add = command(
        "add-columns", help="Створити стовпчики уроків за розкладом на місяць.",
        description="""\
Створює стовпчики уроків за schedule.yaml. Для кожного уроку відкриває
«Додати стовпчик», ставить тип «Поточна», дату першого такого дня місяця,
повторення «щотижня до кінця місяця», номер уроку і кабінет — решту тижнів
добудовує сам сайт.

Канікули й святкові дні не враховуються: зайвий стовпчик простіше видалити
вручну. Повторний запуск не дублює — рахується, скільки стовпчиків на дату
вже є, і при розбіжності скрипт питає.""",
    )
    add.add_argument("--month", required=True, help="Цільовий місяць, формат YYYY-MM.")
    add.add_argument("--subject", default=None, help="Обмежитись одним предметом.")
    add.add_argument(
        "--class", dest="class_name", default=None, help="Обмежитись одним класом."
    )
    add.add_argument(
        "--dry-run",
        action="store_true",
        help="Тільки надрукувати план, нічого не створювати.",
    )
    add.add_argument(
        "--slow-mo",
        type=int,
        default=250,
        help=SLOW_MO_HELP,
    )
    _add_browser_flag(add)
    add.set_defaults(func=cmd_add_columns)

    planning = command(
        "import-planning",
        help="Перетворити .docx планування на planning/*.yaml.",
        description="""\
Читає п'ять .docx календарних планувань і пише planning/*.yaml — по файлу на
паралель. Далі ці файли правляться руками; .docx більше не потрібен.

Робиться раз на семестр, перед першим fill-topics.""",
    )
    planning.add_argument(
        "--source",
        default=str(DEFAULT_PLANNING_SOURCE),
        help=f"Тека з .docx планування (типово {DEFAULT_PLANNING_SOURCE}).",
    )
    planning.set_defaults(func=cmd_import_planning)

    topics = command(
        "fill-topics",
        help="Заповнити теми уроків у журналі за календарним плануванням.",
        description="""\
Пише теми уроків у блок «Теми уроків та домашні завдання». Рядок там існує
лише для вже створеного стовпчика, тому спершу має пройти add-columns.

Три проходи за один візит у журнал:
  1. якщо журнал розійшовся з плануванням — питає, чи вирівняти;
  2. пише наступні уроки, скільки скаже --count;
  3. дописує ДЗ зі сховища в рядки, де тема є, а ДЗ порожнє.

Урок, тема якого — «Лабораторна робота …» чи «Контрольна робота …»,
одразу отримує цей тип замість «Поточна».

--count 0 робить лише третій прохід: тем не чіпає, тільки дозаписує ДЗ.""",
    )
    topics.add_argument(
        "--subject",
        default=None,
        help="Обмежитись одним предметом. Без цього — усі предмети.",
    )
    topics.add_argument(
        "--class",
        dest="class_name",
        default=None,
        help="Обмежитись одним класом. Без цього — усі класи.",
    )
    topics.add_argument(
        "--count",
        type=int,
        default=None,
        help="Скільки уроків заповнити. Без цього — питає в консолі.",
    )
    topics.add_argument(
        "--resync",
        action="store_true",
        help=(
            "Вирівняти журнал по плануванню без питання: n-й рядок стає "
            "n-м уроком. Тільки вирівнює; нові уроки пише лише з --count."
        ),
    )
    topics.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати теми з планування, журнал не чіпати.",
    )
    topics.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(topics)
    topics.set_defaults(func=cmd_fill_topics)

    dump = command(
        "dump-homework",
        help="Зібрати домашні завдання з журналів у homework/*.yaml.",
        description="""\
Читає таблицю тем готових журналів і складає пари «номер уроку, тема,
домашнє завдання» у homework/*.yaml — по файлу на паралель. Звідти їх бере
fill-topics.

Без прапорців читає обидва семестри минулого навчального року. Семестр —
стан сесії, не вкладки, тому після роботи завжди повертається на поточний.

--from читає натомість поточний семестр: так ДЗ з 9-А переноситься в 9-Б і
9-В, бо fill-topics бере його з того самого файла.""",
    )
    dump.add_argument(
        "--semester",
        default=None,
        help=(
            "Читати семестр, у назві якого є цей підрядок, напр. "
            "\"2025-2026 [1]\". Без цього — минулий навчальний рік."
        ),
    )
    dump.add_argument(
        "--semester-list",
        action="store_true",
        help="Тільки показати семестри акаунта і вийти, нічого не перемикаючи.",
    )
    dump.add_argument(
        "--from",
        dest="from_class",
        default=None,
        help=(
            "Читати ці класи поточного семестру замість минулих років, "
            "через кому: 9-А або 9-А,9-Б,9-В. Семестр не перемикається."
        ),
    )
    dump.add_argument(
        "--subject", default=None, help="Обмежитись одним предметом."
    )
    dump.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати зібране, файлів не записувати.",
    )
    dump.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(dump)
    dump.set_defaults(func=cmd_dump_homework)

    check = command(
        "check",
        help="Перевірити журнали: нумерація, теми, ДЗ. Нічого не змінює.",
        description="""\
Читає таблицю тем кожного журналу і друкує, що не сходиться:

  порожній рядок, а далі є заповнені   урок не відбувся
  пропуск у нумерації (1, 2, потім 4)  коригування зробили руками
  номер повторюється або йде назад     майже завжди помилка
  тема не збігається з плануванням     клас пішов своїм темпом
  ДЗ порожнє                           окремо: чи є воно у сховищі

Нічого не записує. Виправляє це fill-topics — він питає, чи вирівняти
журнал по плануванню.""",
    )
    check.add_argument("--subject", default=None, help="Обмежитись одним предметом.")
    check.add_argument(
        "--class", dest="class_name", default=None, help="Обмежитись одним класом."
    )
    check.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(check)
    check.set_defaults(func=cmd_check)

    month = command(
        "run-month",
        help="Усе за місяць для всіх класів: стовпчики, потім теми уроків.",
        description="""\
Один місяць повністю: спершу стовпчики для всіх класів, потім теми уроків.
Порядок обов'язковий і не налаштовується — блок тем показує рядки лише для
вже створених стовпчиків.""",
    )
    month.add_argument("--month", required=True, help="Цільовий місяць, YYYY-MM.")
    month.add_argument(
        "--count",
        type=int,
        default=None,
        help="Скільки тем заповнити в кожному класі. Без цього — питає.",
    )
    month.add_argument(
        "--dry-run", action="store_true", help="Показати план, нічого не робити."
    )
    month.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(month)
    month.set_defaults(func=cmd_run_month)

    delete = command(
        "delete-lessons",
        help="Видалити стовпчики уроків за діапазоном дат (напр. канікули).",
        description="""\
Видаляє стовпчики уроків, що припадають на вказані дати, — наприклад,
останній тиждень жовтня, коли канікули, а add-columns створив уроки
«щотижня до кінця місяця».

Спершу читає всі журнали і показує, що саме піде під видалення: дату,
тему (якщо є) і скільки в стовпчику оцінок. Потім питає один раз. Видалити
назад не можна.

Стовпчик з оцінками лишається, якщо не дати --force. Перед кожним
видаленням дата ще раз звіряється в самому діалозі уроку.

Якщо у видалених уроках уже стояли теми, fill-topics продовжить з
найбільшого номера, що лишився, — ці теми підуть на наступні уроки.""",
    )
    delete.add_argument(
        "--last-week",
        metavar="YYYY-MM",
        default=None,
        help="Останній тиждень місяця: з понеділка того тижня до кінця місяця.",
    )
    delete.add_argument(
        "--from", dest="date_from", metavar="YYYY-MM-DD", default=None,
        help="Перша дата діапазону.",
    )
    delete.add_argument(
        "--to", dest="date_to", metavar="YYYY-MM-DD", default=None,
        help="Остання дата діапазону, включно. Без цього — лише день --from.",
    )
    delete.add_argument("--subject", default=None, help="Обмежитись одним предметом.")
    delete.add_argument(
        "--class", dest="class_name", default=None, help="Обмежитись одним класом."
    )
    delete.add_argument(
        "--force",
        action="store_true",
        help="Видаляти й стовпчики, де вже є оцінки (разом з оцінками).",
    )
    delete.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати, що піде під видалення, нічого не видаляти.",
    )
    delete.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(delete)
    delete.set_defaults(func=cmd_delete_lessons)

    types = command(
        "set-lesson-types",
        help="Поставити тип «Лабораторна/Контрольна робота» за темою уроку.",
        description="""\
Читає теми, вже записані в журнал, і уроку з темою «Лабораторна робота …»
ставить тип «Лабораторна робота», а з «Контрольна робота …» — «Контрольна
робота» замість «Поточна». «Аналіз контрольної роботи» лишається звичайним.

fill-topics робить це сам для уроків, які пише. Ця команда — для тем,
записаних раніше або вручну. Де тип уже правильний, нічого не зберігає.""",
    )
    types.add_argument("--subject", default=None, help="Обмежитись одним предметом.")
    types.add_argument(
        "--class", dest="class_name", default=None, help="Обмежитись одним класом."
    )
    types.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати, яким урокам який тип належить, нічого не змінювати.",
    )
    types.add_argument("--slow-mo", type=int, default=250, help=SLOW_MO_HELP)
    _add_browser_flag(types)
    types.set_defaults(func=cmd_set_lesson_types)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
