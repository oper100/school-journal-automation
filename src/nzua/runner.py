"""Running a month's worth of column creation across every journal.

Journals are visited once each, in the order the plan produced. Before adding
anything the runner reads the columns a journal already has, so a repeated run
does not silently double up.

Counting matters more than mere presence: a class can legitimately have two
lessons on one weekday — 9-В has physics on both the 2nd and 4th period every
Tuesday — so two columns on that date are correct and a third is not.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page

from .browser import PROJECT_ROOT, ensure_logged_in
from .columns import add_column
from .journal import (
    current_semester,
    existing_column_dates,
    find_journal,
    load_journal_links,
    open_journal,
    require_current_semester,
)
from .schedule import ColumnTask, Schedule

Ask = Callable[[str], str]


class Log:
    """Print to the console and keep the same lines in a run log."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("a", encoding="utf-8")
        self.write(f"=== запуск {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    def write(self, line: str) -> None:
        print(line)
        self.handle.write(line + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def _ask_console(question: str) -> str:
    return input(question).strip().lower()


def _said_yes(answer: str) -> bool:
    """Whether a [т]ак / [н]і answer was a yes."""
    return answer.startswith("т")


def _group_by_journal(tasks: list[ColumnTask]) -> list[tuple[tuple[str, str], list[ColumnTask]]]:
    """Keep the plan's order, but collect each journal's tasks together."""
    groups: dict[tuple[str, str], list[ColumnTask]] = {}
    for task in tasks:
        groups.setdefault(task.journal, []).append(task)
    return list(groups.items())


def run_tasks(
    page: Page,
    schedule: Schedule,
    tasks: list[ColumnTask],
    ask: Ask = _ask_console,
) -> int:
    """Create every planned column. Returns a process exit code."""
    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    added = skipped = failed = 0
    skip_all_duplicates = False
    stop_requested = False

    try:
        ensure_logged_in(page)
        require_current_semester(page)
        links = load_journal_links(page)
        log.write(f"Знайдено журналів на сайті: {len(links)}")

        for (subject, class_name), journal_tasks in _group_by_journal(tasks):
            log.write("")
            log.write(f"--- {subject} {class_name} ({len(journal_tasks)} стовпчиків)")

            try:
                link = find_journal(links, subject, class_name)
                open_journal(page, link)
                semester_start, _ = current_semester(page)
                have = Counter(existing_column_dates(page, semester_start))
            except Exception as exc:
                failed += len(journal_tasks)
                log.write(f"  ПОМИЛКА журналу: {type(exc).__name__}: {exc}")
                continue

            needed = Counter(task.date for task in journal_tasks)
            done_now: Counter[date] = Counter()

            for task in journal_tasks:
                when = task.date
                duplicate = have[when] + done_now[when] >= needed[when]

                if duplicate:
                    if skip_all_duplicates:
                        skipped += 1
                        log.write(f"  {when} урок {task.slot.lesson_no}: вже є, пропускаю")
                        continue
                    log.write(
                        f"  {when} урок {task.slot.lesson_no}: у журналі вже "
                        f"{have[when] + done_now[when]} стовпчик(ів) на цю дату, "
                        f"а за розкладом треба {needed[when]}."
                    )
                    answer = ask(
                        "    [п]ропустити / [в]се одно додати / "
                        "пропускати [у]сі такі / [з]упинити: "
                    )
                    if answer.startswith("з"):
                        log.write("  Зупинено на прохання користувача.")
                        stop_requested = True
                        break
                    if answer.startswith("у"):
                        skip_all_duplicates = True
                        skipped += 1
                        continue
                    if not answer.startswith("в"):
                        skipped += 1
                        continue

                try:
                    chosen = add_column(page, task, schedule.lesson_type)
                    done_now[when] += 1
                    added += 1
                    log.write(
                        f"  + {when} | {chosen['урок']} | {chosen['кабінет']} | "
                        f"{chosen['повторення']}"
                    )
                except Exception as exc:
                    failed += 1
                    log.write(
                        f"  ПОМИЛКА {when} урок {task.slot.lesson_no}: "
                        f"{type(exc).__name__}: {exc}"
                    )
            if stop_requested:
                break

        log.write("")
        log.write(f"Підсумок: додано {added}, пропущено {skipped}, помилок {failed}.")
        log.write(f"Журнал запуску: {log.path.name}")
    finally:
        log.close()

    return 1 if failed else 0


def _ask_count(available: int, ask: Ask) -> int:
    """How many lessons to fill this run, when --count was not given."""
    while True:
        answer = ask(
            f"    Порожніх уроків: {available}. Скільки заповнити "
            f"(Enter — усі, 0 — вийти): "
        )
        if not answer:
            return available
        if answer.isdigit():
            return min(int(answer), available)
        print("    Введи число.")




def journals_of(schedule: Schedule, subject=None, class_name=None):
    """Every subject+class journal the schedule mentions, in a stable order."""
    slots = schedule.filter(subject=subject, class_name=class_name)
    return list(dict.fromkeys((slot.subject, slot.class_name) for slot in slots))


def _homework_store(schedule: Schedule, log: Log, subject: str, class_name: str):
    """The collected homework for this class's year group, if any was collected.

    A missing store is not an error: it only means topics go in without
    homework, exactly as they did before `dump-homework` existed.
    """
    from .homework import HomeworkError, load_store_if_present
    from .planning import grade_of

    try:
        path = PROJECT_ROOT / schedule.homework_path(subject, grade_of(class_name))
        store = load_store_if_present(path)
    except (KeyError, ValueError, HomeworkError) as exc:
        log.write(f"  ДЗ: {exc}")
        return None

    if store is None:
        log.write("  ДЗ: сховища ще немає — теми запишуться без ДЗ.")
    else:
        log.write(f"  ДЗ: {path.name}, {len(store.entries)} уроків.")
    return store


def _add_missing_homework(page, log: Log, store, rows) -> tuple[int, int]:
    """Second pass: fill homework into rows that already carry a topic.

    Topics written before any homework was collected — and topics of 9-Б and
    9-В written before 9-А was dumped — would otherwise stay bare. Nothing
    but the homework field is touched, so the numbering cannot shift and a
    failure here does not stop the rest.
    """
    from .topics import (
        confirm_row,
        fill_homework_dialog,
        homework_targets,
        open_topic_dialog,
        save_topic_dialog,
    )

    targets = homework_targets(rows, store.lookup)
    if not targets:
        return 0, 0

    log.write(f"  Дозапис ДЗ у вже заповнені рядки: {len(targets)}.")
    added = failed = 0
    for index, number, text in targets:
        row = rows[index]
        try:
            open_topic_dialog(page, row)
            due = fill_homework_dialog(page, text)
            save_topic_dialog(page)
            confirm_row(page, row, number, expect_homework=True)
            added += 1
            log.write(
                f"  ДЗ {row.date_text} | № {number} | "
                f"на {due or '—'} | {text[:60]}"
            )
        except Exception as exc:
            failed += 1
            log.write(
                f"  ПОМИЛКА ДЗ {row.date_text} № {number}: "
                f"{type(exc).__name__}: {exc}"
            )
    return added, failed


def _write_targets(
    page, log: Log, plan, store, rows, targets
) -> tuple[int, int, int]:
    """Write one batch of (row, lesson number) pairs.

    Returns (written, failed, types failed). Only `failed` means the batch
    stopped: a lesson type that did not take leaves the numbering intact, so
    it is counted apart and must not stop the passes that follow.

    The pairs are decided before the first save and never re-read from the
    page: the table refreshes a moment late, so a row just saved can still
    read as empty, which once wrote the same row twice.
    """
    from .topics import (
        confirm_row,
        fill_topic_dialog,
        open_topic_dialog,
        save_topic_dialog,
    )

    written = failed = types_failed = 0
    for index, number in targets:
        row = rows[index]
        try:
            lesson = plan.lesson(number)
            homework = store.lookup(lesson.number, lesson.topic) if store else None
            open_topic_dialog(page, row)
            due = fill_topic_dialog(
                page, lesson.topic, lesson.number, homework or ""
            )
            save_topic_dialog(page)
            confirm_row(page, row, lesson.number)
            written += 1
            log.write(
                f"  + {row.date_text} | № {lesson.number} | "
                f"ДЗ на {due or '—'} | {lesson.topic[:60]}"
            )
            if store is not None and not homework:
                log.write(f"      ДЗ для уроку № {lesson.number} у сховищі немає.")
        except Exception as exc:
            failed += 1
            log.write(
                f"  ПОМИЛКА {row.date_text} № {number}: "
                f"{type(exc).__name__}: {exc}"
            )
            break  # a wrong row here would shift every number after it
        # The topic is in; a type that did not take is reported, but the
        # numbering is not at stake, so writing goes on.
        types_failed += _type_from_topic(page, log, row, lesson.topic)
    return written, failed, types_failed


def _type_from_topic(page, log: Log, row, topic: str) -> int:
    """Set the column's type when the topic names a lab or a test. Returns failures.

    `row` is the row as read before `topic` went in. When the topic it held
    named a lab or a test and the new one names neither — a realigned journal
    moves topics down — the column goes back to the ordinary type, or it
    would stay a lab with an ordinary topic and nothing would ever fix it.
    """
    from . import selectors as sel
    from .lessons import lesson_type_for, set_lesson_type

    wanted = lesson_type_for(topic)
    if not wanted and lesson_type_for(row.topic):
        wanted = sel.LESSON_TYPE_OPTION
    if not wanted:
        return 0
    try:
        before = set_lesson_type(page, row, wanted)
    except Exception as exc:
        log.write(
            f"  ПОМИЛКА типу {row.date_text} «{wanted}»: {type(exc).__name__}: {exc}"
        )
        return 1
    if before is None:
        log.write(f"      тип уже «{wanted}»")
    else:
        log.write(f"      тип: {before} -> {wanted}")
    return 0


def _agree_to_realign(log: Log, ask: Ask, drift, decisions: dict) -> bool:
    """Ask whether to bring a journal that drifted back onto the plan.

    Closing a hole means renumbering every row below it, so it is never done
    silently — but a teacher fixing eleven journals should not have to answer
    eleven times either.
    """
    log.write(
        f"  Рядків, що не збігаються з плануванням: {len(drift)} "
        f"(пропуск або зсув нумерації)."
    )
    if decisions.get("all"):
        return True

    answer = ask(
        "    Переписати журнал за плануванням? "
        "[т]ак / [н]і / [у]сі такі / [з]упинити: "
    )
    if answer.startswith("з"):
        decisions["stop"] = True
        return False
    if answer.startswith("у"):
        decisions["all"] = True
        return True
    return _said_yes(answer)


def _fill_one_journal(
    page: Page,
    log: Log,
    links,
    plan,
    schedule: Schedule,
    subject: str,
    class_name: str,
    count: int | None,
    resync: bool,
    ask: Ask,
    decisions: dict | None = None,
) -> tuple[int, int, int]:
    """Fill one journal. Returns (topics written, homework added, failed).

    Up to three passes, in this order: bring the journal back onto the plan if
    it drifted, write the lessons that come next, then fill in homework the
    store knows about for rows that already carry a topic.
    """
    from .journal import find_journal, open_journal
    from .topics import fill_targets, pending_rows, read_topic_rows, resync_targets

    decisions = {} if decisions is None else decisions
    written = added = failed = 0
    # Lesson types that did not take: reported in the total, but unlike
    # `failed` they stop nothing — the topics and numbering are fine.
    types_failed = 0
    log.write("")
    log.write(f"--- {subject} {class_name}: {plan.source}")

    try:
        link = find_journal(links, subject, class_name)
        open_journal(page, link)
        rows = read_topic_rows(page)
    except Exception as exc:
        log.write(f"  ПОМИЛКА журналу: {type(exc).__name__}: {exc}")
        return 0, 0, 1

    log.write(
        f"  рядків {len(rows)}, заповнено {len(rows) - len(pending_rows(rows))}"
    )
    store = _homework_store(schedule, log, subject, class_name)

    # --- pass one: back onto the plan
    try:
        drift = resync_targets(rows, lambda n: plan.lesson(n).topic)
    except Exception as exc:
        log.write(f"  ПОМИЛКА звірки з плануванням: {type(exc).__name__}: {exc}")
        return 0, 0, 1

    if drift and (resync or _agree_to_realign(log, ask, drift, decisions)):
        done, bad, bad_types = _write_targets(page, log, plan, store, rows, drift)
        written += done
        failed += bad
        types_failed += bad_types
        if failed:
            return written, added, failed + types_failed
        rows = read_topic_rows(page)  # the pass above renumbered them
    elif drift:
        log.write("  Журнал лишено як є.")
    if decisions.get("stop"):
        return written, added, failed + types_failed

    # --- pass two: the lessons that come next
    try:
        if resync and count is None:
            wanted = 0  # --resync on its own only repairs
        elif count is None:
            wanted = _ask_count(len(pending_rows(rows)), ask)
        else:
            wanted = count
        targets = fill_targets(rows, wanted) if wanted > 0 else []
    except Exception as exc:
        log.write(f"  ПОМИЛКА: {type(exc).__name__}: {exc}")
        return written, added, failed + types_failed + 1

    if targets:
        done, bad, bad_types = _write_targets(page, log, plan, store, rows, targets)
        written += done
        failed += bad
        types_failed += bad_types

    # --- pass three: homework for rows that already had a topic
    if store is not None and not failed:
        try:
            added, bad = _add_missing_homework(page, log, store, read_topic_rows(page))
            failed += bad
        except Exception as exc:
            failed += 1
            log.write(f"  ПОМИЛКА дозапису ДЗ: {type(exc).__name__}: {exc}")

    if not written and not added:
        log.write("  Нічого робити не треба.")

    return written, added, failed + types_failed


def _plan_for(schedule: Schedule, subject: str, class_name: str):
    from .planning import load_plan

    return load_plan(PROJECT_ROOT / schedule.plan_path(subject, class_name))


def run_fill_topics(
    page: Page,
    schedule: Schedule,
    subject: str | None = None,
    class_name: str | None = None,
    count: int | None = None,
    resync: bool = False,
    ask: Ask = _ask_console,
) -> int:
    """Fill lesson topics from the calendar plans.

    With no subject or class, every journal in the schedule is visited. A
    journal that fails does not stop the others: it is reported and the run
    moves on, because each journal's numbering is independent.
    """
    from .journal import load_journal_links

    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    filled = homework = failed = 0

    try:
        ensure_logged_in(page)
        require_current_semester(page)
        links = load_journal_links(page)
        targets = journals_of(schedule, subject, class_name)
        log.write(f"Журналів до заповнення: {len(targets)}")

        # Asked once rather than per journal: eleven prompts is not a workflow.
        if count is None and not resync and len(targets) > 1:
            answer = ask("    Скільки уроків заповнити в кожному класі: ")
            count = int(answer) if answer.isdigit() else 0

        # «усі такі» and «зупинити» are answered once, not once per journal.
        decisions: dict = {}

        for subject_name, class_label in targets:
            if decisions.get("stop"):
                log.write("")
                log.write("Зупинено на прохання користувача.")
                break
            try:
                plan = _plan_for(schedule, subject_name, class_label)
            except Exception as exc:
                failed += 1
                log.write("")
                log.write(f"--- {subject_name} {class_label}: планування недоступне: {exc}")
                continue
            done, extra, bad = _fill_one_journal(
                page, log, links, plan, schedule,
                subject_name, class_label, count, resync, ask, decisions,
            )
            filled += done
            homework += extra
            failed += bad

        log.write("")
        log.write(
            f"Підсумок: заповнено {filled}, дописано ДЗ {homework}, "
            f"помилок {failed}."
        )
        log.write(f"Журнал запуску: {log.path.name}")
    except Exception as exc:
        log.write(f"ПОМИЛКА: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        log.close()

    return 1 if failed else 0


def run_month(
    page: Page,
    schedule: Schedule,
    tasks: list[ColumnTask],
    count: int | None = None,
    ask: Ask = _ask_console,
) -> int:
    """A month in one go: create every column, then fill every topic.

    Order matters and is not optional — the topics table only lists rows for
    columns that already exist.
    """
    columns = run_tasks(page, schedule, tasks, ask=ask)
    topics = run_fill_topics(page, schedule, count=count, ask=ask)
    return columns or topics


# --- collecting homework out of journals ------------------------------------


def _readable_journals(schedule: Schedule, links) -> list:
    """Journals worth reading for homework, out of everything the account has.

    Past semesters hold subjects and year groups we have no plan for, so the
    filter is the schedule's own subjects plus the year groups schedule.yaml
    gives a homework file. Subgroup journals are all read: each keeps its own
    topics table.
    """
    from .planning import grade_of

    wanted = set(schedule.subjects)
    out = []
    for link in links:
        if link.subject not in wanted:
            continue
        try:
            schedule.homework_path(link.subject, grade_of(link.class_name))
        except (KeyError, ValueError):
            continue
        out.append(link)
    return out


def _collect_from_journal(page: Page, log: Log, link):
    """Read one journal's topics table into homework entries."""
    from .homework import harvest
    from .journal import open_journal
    from .topics import read_topic_rows

    open_journal(page, link)
    rows = read_topic_rows(page)
    entries = harvest(rows)
    log.write(
        f"  {link.subject} {link.raw_label or link.class_name}: "
        f"рядків {len(rows)}, із ДЗ {len(entries)}"
    )
    return entries


def _choose_semesters(options, wanted: str | None, log: Log):
    """Which semesters to walk: the named one, or the whole previous year."""
    from .journal import JournalError, previous_academic_year, semesters_of_year

    if wanted:
        picked = [option for option in options if wanted in option.label]
        if not picked:
            available = "\n    ".join(option.label for option in options)
            raise JournalError(
                f"Немає семестру, у назві якого є «{wanted}». Доступні:\n    "
                + available
            )
        return picked

    year = previous_academic_year(options)
    log.write(f"Минулий навчальний рік: {year}")
    return semesters_of_year(options, year)


def run_dump_homework(
    page: Page,
    schedule: Schedule,
    semester: str | None = None,
    from_classes: tuple[str, ...] = (),
    subject: str | None = None,
    dry_run: bool = False,
    list_only: bool = False,
) -> int:
    """Collect «lesson -> homework» pairs into the store under `homework/`.

    Two ways in, one store out:

    * with no `from_classes`, past semesters are walked and every journal of a
      year group we have a plan for is read;
    * with `from_classes`, only those classes of the semester in use are read
      — which is how 9-А's homework reaches 9-Б and 9-В: dump it here, and the
      next `fill-topics` writes it into the others.

    The chosen semester belongs to the whole session, not to the tab, so it is
    always put back — a run that left it in a past year would make the next
    `add-columns` create its columns there.
    """
    from .homework import combine, load_store_if_present, store_of, write_store
    from .journal import (
        chosen_semester,
        find_journal,
        semester_options,
        select_semester,
    )
    from .planning import grade_of

    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    # (subject, grade) -> the entries collected so far, earliest journal wins.
    collected: dict[tuple[str, int], list] = {}
    sources: dict[tuple[str, int], list[str]] = {}
    failed = 0

    try:
        ensure_logged_in(page)
        options = semester_options(page)
        started_on = chosen_semester(options)

        if list_only:
            log.write("Семестри в акаунті:")
            for option in options:
                log.write(f"  {option.describe()}")
            return 0

        if from_classes:
            wanted = [started_on]
            log.write(f"Поточний семестр: {started_on.describe()}")
        else:
            wanted = _choose_semesters(options, semester, log)
            log.write(f"Семестрів до читання: {len(wanted)}")
            for option in wanted:
                log.write(f"  {option.describe()}")

        try:
            for option in wanted:
                log.write("")
                log.write(f"--- {option.label}")
                select_semester(page, option.value)
                # Journal ids are per semester, so the list is read again.
                links = load_journal_links(page)

                if from_classes:
                    pairs = list(
                        dict.fromkeys(
                            pair
                            for name in from_classes
                            for pair in journals_of(schedule, subject, name)
                        )
                    )
                    chosen = []
                    for subject_name, class_label in pairs:
                        try:
                            chosen.append(
                                find_journal(links, subject_name, class_label)
                            )
                        except Exception as exc:
                            failed += 1
                            log.write(
                                f"  ПОМИЛКА {subject_name} {class_label}: {exc}"
                            )
                else:
                    chosen = _readable_journals(schedule, links)
                    if subject:
                        chosen = [
                            link for link in chosen if link.subject == subject
                        ]

                log.write(f"  журналів до читання: {len(chosen)}")
                for link in chosen:
                    try:
                        entries = _collect_from_journal(page, log, link)
                    except Exception as exc:
                        failed += 1
                        log.write(
                            f"  ПОМИЛКА {link.subject} {link.class_name}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue
                    if not entries:
                        continue
                    key = (link.subject, grade_of(link.class_name))
                    merged, _ = combine(collected.get(key, []), entries)
                    collected[key] = merged
                    sources.setdefault(key, []).append(
                        f"{option.academic_year} [{option.number}] {link.class_name}"
                    )
        finally:
            select_semester(page, started_on.value)
            log.write("")
            log.write(f"Семестр повернуто на: {started_on.label}")

        if not collected:
            log.write("Жодного домашнього завдання не знайдено.")
            return 1 if failed else 0

        for (subject_name, grade), entries in sorted(collected.items()):
            path = PROJECT_ROOT / schedule.homework_path(subject_name, grade)
            existing = load_store_if_present(path)
            final, overridden = combine(
                entries, existing.entries if existing else []
            )
            store = store_of(
                subject_name,
                grade,
                final,
                list(sources.get((subject_name, grade), ()))
                + list(existing.sources if existing else ()),
            )

            log.write("")
            log.write(
                f"=== {subject_name} {grade} клас -> {path.name}: "
                f"уроків {len(store.entries)}, зібрано цього разу {len(entries)}, "
                f"перезаписано {overridden}"
            )
            for entry in store.entries:
                log.write(
                    f"  № {entry.number:<4} {entry.topic[:60]} — "
                    f"{entry.homework[:80]}"
                )

            if dry_run:
                log.write(f"  --dry-run: {path.name} не записано.")
            else:
                write_store(store, path)
                log.write(f"  записано {path}")

        log.write("")
        log.write(f"Підсумок: файлів {len(collected)}, помилок {failed}.")
        log.write(f"Журнал запуску: {log.path.name}")
    except Exception as exc:
        log.write(f"ПОМИЛКА: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        log.close()

    return 1 if failed else 0


# --- reading every journal over without writing to it -----------------------


def _check_one_journal(
    page: Page, log: Log, links, schedule: Schedule, subject: str, class_name: str
) -> tuple[int, int]:
    """Report on one journal. Returns (issues found, journals that failed)."""
    from .journal import find_journal, open_journal
    from .topics import check_rows, read_topic_rows

    log.write("")
    try:
        plan = _plan_for(schedule, subject, class_name)
        link = find_journal(links, subject, class_name)
        open_journal(page, link)
        rows = read_topic_rows(page)
    except Exception as exc:
        log.write(f"--- {subject} {class_name}: {type(exc).__name__}: {exc}")
        return 0, 1

    store = _homework_store(schedule, log, subject, class_name)

    def plan_topic(number: int):
        try:
            return plan.lesson(number).topic
        except Exception:
            return None

    issues = check_rows(
        rows,
        plan_topic,
        store.lookup if store else (lambda number, topic: None),
    )
    log.write(
        f"--- {subject} {class_name}: рядків {len(rows)}, зауважень {len(issues)}"
    )
    for issue in issues:
        log.write(f"  {issue.date_text:<14} № {issue.number_text:<5} {issue.label}")
        if issue.detail:
            log.write(f"  {'':<14}   {issue.detail}")
    return len(issues), 0


def run_check(
    page: Page,
    schedule: Schedule,
    subject: str | None = None,
    class_name: str | None = None,
) -> int:
    """Read every journal and report what does not add up. Writes nothing.

    Holes and jumps in the numbering are legitimate — a lesson that did not
    happen, a correction made by hand — so `fill-topics` no longer stops at
    them. This is where they are put in front of a person instead.
    """
    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    issues = failed = 0

    try:
        ensure_logged_in(page)
        require_current_semester(page)
        links = load_journal_links(page)
        targets = journals_of(schedule, subject, class_name)
        log.write(f"Журналів до перевірки: {len(targets)}")

        for subject_name, class_label in targets:
            found, bad = _check_one_journal(
                page, log, links, schedule, subject_name, class_label
            )
            issues += found
            failed += bad

        log.write("")
        log.write(
            f"Підсумок: зауважень {issues} у {len(targets)} журналах, "
            f"недоступних журналів {failed}."
        )
        log.write("Нічого не змінено — це лише перевірка.")
        log.write(f"Журнал запуску: {log.path.name}")
    except Exception as exc:
        log.write(f"ПОМИЛКА: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        log.close()

    return 1 if failed else 0


# --- deleting columns -------------------------------------------------------


def _ask_delete(log: Log, ask: Ask, count: int, journals: int) -> bool:
    log.write("")
    answer = ask(
        f"    Видалити {count} стовпчик(ів) у {journals} журнал(ах)? "
        "Відновити їх не можна. [т]ак / [н]і: "
    )
    return _said_yes(answer)


def _plan_deletions(
    page: Page, log: Log, link, start: date, end: date, force: bool
) -> list[tuple]:
    """Read one journal and decide which of its columns in the range go.

    Returns (row, date) pairs. A column holding marks is kept unless `force`:
    deleting it would delete the marks with it.
    """
    from .journal import show_journal_page
    from .lessons import marks_by_schedule, parse_row_date, rows_between
    from .topics import read_topic_rows

    open_journal(page, link)
    semester_start, _ = current_semester(page)
    rows = read_topic_rows(page)
    for row in rows:
        if row.date_text and parse_row_date(row.date_text, semester_start) is None:
            log.write(f"  ? {row.date_text:<14} не розумію дату — не чіпаю")
    picked = []
    for row, when in rows_between(rows, start, end, semester_start):
        # Without the id the column can be neither found nor checked, and
        # a failed deletion would stop the rest of this journal.
        if not row.schedule_id:
            log.write(f"  ? {row.date_text:<14} немає id уроку — не чіпаю")
            continue
        picked.append((row, when))

    marks: dict[str, int] = {}
    for url in dict.fromkeys(row.page_url for row, _ in picked if row.page_url):
        show_journal_page(page, url)
        marks.update(marks_by_schedule(page))

    chosen = []
    for row, when in picked:
        held = marks.get(row.schedule_id, 0)
        what = f"№ {row.lesson_number}, {row.topic[:50]}" if row.filled else "порожній"
        if held and not force:
            log.write(f"  = {row.date_text:<14} {what} | оцінок {held} — лишаю")
            continue
        note = f" | оцінок {held}" if held else ""
        log.write(f"  - {row.date_text:<14} {what}{note}")
        chosen.append((row, when))
    return chosen


def run_delete_lessons(
    page: Page,
    schedule: Schedule,
    start: date,
    end: date,
    subject: str | None = None,
    class_name: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    ask: Ask = _ask_console,
) -> int:
    """Delete every lesson column dated from `start` to `end` in the chosen journals.

    Everything is read first and shown, and asked about once; only then is
    anything deleted. Within a journal the latest column goes first, so the
    ones still waiting stay where they were read.
    """
    from .lessons import delete_lesson

    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    deleted = failed = 0

    try:
        ensure_logged_in(page)
        require_current_semester(page)
        links = load_journal_links(page)
        targets = journals_of(schedule, subject, class_name)
        log.write(
            f"Видалення стовпчиків з {start:%d.%m.%Y} по {end:%d.%m.%Y}, "
            f"журналів: {len(targets)}"
        )

        plan: list[tuple] = []
        for subject_name, class_label in targets:
            log.write("")
            log.write(f"--- {subject_name} {class_label}")
            try:
                link = find_journal(links, subject_name, class_label)
                chosen = _plan_deletions(page, log, link, start, end, force)
            except Exception as exc:
                failed += 1
                log.write(f"  ПОМИЛКА журналу: {type(exc).__name__}: {exc}")
                continue
            if not chosen:
                log.write("  у цьому діапазоні видаляти нічого")
                continue
            plan.append((subject_name, class_label, link, chosen))

        total = sum(len(chosen) for *_, chosen in plan)
        if not total:
            log.write("")
            log.write("Нічого видаляти.")
        elif dry_run:
            log.write("")
            log.write(f"--dry-run: до видалення {total}, нічого не видалено.")
        elif not _ask_delete(log, ask, total, len(plan)):
            log.write("Скасовано, нічого не видалено.")
        else:
            for subject_name, class_label, link, chosen in plan:
                log.write("")
                log.write(f"--- {subject_name} {class_label}")
                try:
                    open_journal(page, link)
                except Exception as exc:
                    failed += 1
                    log.write(f"  ПОМИЛКА журналу: {type(exc).__name__}: {exc}")
                    continue
                for row, when in sorted(chosen, key=lambda pair: pair[1], reverse=True):
                    try:
                        delete_lesson(page, row, when)
                    except Exception as exc:
                        failed += 1
                        log.write(
                            f"  ПОМИЛКА {row.date_text}: {type(exc).__name__}: {exc}"
                        )
                        break  # the page is no longer what was read; leave it
                    deleted += 1
                    log.write(f"  x {row.date_text} видалено")
                if any(row.filled for row, _ in chosen):
                    log.write(
                        "  Серед видалених були уроки з темою: fill-topics "
                        "продовжить з найбільшого номера, що лишився, а якщо "
                        "нижче є заповнені — запропонує вирівняти."
                    )

        log.write("")
        log.write(f"Підсумок: видалено {deleted}, помилок {failed}.")
        log.write(f"Журнал запуску: {log.path.name}")
    except Exception as exc:
        log.write(f"ПОМИЛКА: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        log.close()

    return 1 if failed else 0


# --- lesson types from the topic --------------------------------------------


def run_set_lesson_types(
    page: Page,
    schedule: Schedule,
    subject: str | None = None,
    class_name: str | None = None,
    dry_run: bool = False,
) -> int:
    """Give every lab and test lesson its type, judging by the topic written in.

    fill-topics does this for the lessons it writes; this is for the ones
    written before, or by hand. A column that already has the type is opened,
    read and closed without saving.
    """
    from .lessons import set_lesson_type, type_targets
    from .topics import read_topic_rows

    log = Log(PROJECT_ROOT / f"run-{date.today():%Y-%m-%d}.log")
    changed = failed = 0

    try:
        ensure_logged_in(page)
        require_current_semester(page)
        links = load_journal_links(page)
        targets = journals_of(schedule, subject, class_name)
        log.write(f"Типи уроків за темою, журналів: {len(targets)}")

        for subject_name, class_label in targets:
            log.write("")
            log.write(f"--- {subject_name} {class_label}")
            try:
                open_journal(page, find_journal(links, subject_name, class_label))
                wanted = type_targets(read_topic_rows(page))
            except Exception as exc:
                failed += 1
                log.write(f"  ПОМИЛКА журналу: {type(exc).__name__}: {exc}")
                continue
            if not wanted:
                log.write("  лабораторних і контрольних серед тем немає")
                continue
            for row, label in wanted:
                head = f"  {row.date_text:<14} № {row.lesson_number} {label}"
                if dry_run:
                    log.write(f"{head} | {row.topic[:50]}")
                    continue
                try:
                    before = set_lesson_type(page, row, label)
                except Exception as exc:
                    failed += 1
                    log.write(f"{head}: ПОМИЛКА {type(exc).__name__}: {exc}")
                    continue
                if before is None:
                    log.write(f"{head}: уже так")
                else:
                    changed += 1
                    log.write(f"{head}: було «{before}»")

        log.write("")
        if dry_run:
            log.write("--dry-run: нічого не змінено.")
        log.write(f"Підсумок: змінено типів {changed}, помилок {failed}.")
        log.write(f"Журнал запуску: {log.path.name}")
    except Exception as exc:
        log.write(f"ПОМИЛКА: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        log.close()

    return 1 if failed else 0
