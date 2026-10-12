"""Deleting columns and setting lesson types. No browser, no network.

The deciding is tested directly; the run is tested with the site replaced by
fakes, for the part that matters most when nothing can be undone: what gets
deleted, what is spared, and that nothing goes before the teacher says yes.
"""

from datetime import date

import pytest

from nzua import journal as journal_module
from nzua import lessons as lessons_module
from nzua import runner as runner_module
from nzua import topics as topics_module
from nzua.cli import SCHEDULE_PATH, _deletion_range, build_parser
from nzua.journal import JournalLink
from nzua.lessons import last_week, lesson_type_for, parse_row_date, rows_between, type_targets
from nzua.schedule import load_schedule
from nzua.topics import parse_topic_rows as parse_cells

AUTUMN = date(2026, 9, 1)
SPRING = date(2026, 1, 7)


def row(date_text, number="", topic="", schedule_id="1"):
    href = f"/journal/add-edit-home-task?schedule={schedule_id}&journal=7"
    return ["", date_text, str(number), "", topic, "", "", "", href]


def parse_topic_rows(raw, **kwargs):
    """Rows as `row` builds them: eight cells, then the pencil's href."""
    return parse_cells(
        [cells[:8] for cells in raw],
        hrefs=[cells[8] if len(cells) > 8 else "" for cells in raw],
        **kwargs,
    )


# --- dates ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, start, expected",
    [
        ("19 жовтня", AUTUMN, date(2026, 10, 19)),
        ("3 вересня", AUTUMN, date(2026, 9, 3)),
        ("1 грудня", AUTUMN, date(2026, 12, 1)),
        ("12 січня", SPRING, date(2026, 1, 12)),
        ("5 червня", SPRING, date(2026, 6, 5)),
        ("2 січня", date(2026, 9, 1), date(2027, 1, 2)),
    ],
)
def test_row_dates_get_the_semesters_year(text, start, expected):
    assert parse_row_date(text, start) == expected


def test_a_row_without_a_date_has_none():
    assert parse_row_date("", AUTUMN) is None
    assert parse_row_date("щось", AUTUMN) is None


def test_a_weekday_before_the_date_is_skipped():
    assert parse_row_date("Пн, 19 жовтня", AUTUMN) == date(2026, 10, 19)


def test_a_date_that_cannot_exist_is_none_not_a_crash():
    assert parse_row_date("29 лютого", SPRING) is None
    assert parse_row_date("31 листопада", AUTUMN) is None


def test_a_row_short_of_a_cell_is_refused_even_with_its_pencil():
    with pytest.raises(topics_module.TopicsError):
        parse_cells([row("19 жовтня")[:7]], hrefs=[row("19 жовтня")[8]])


def test_last_week_of_october_2026_is_the_holidays():
    assert last_week(2026, 10) == (date(2026, 10, 26), date(2026, 10, 31))


def test_last_week_of_december_does_not_spill_into_the_next_year():
    assert last_week(2026, 12) == (date(2026, 12, 28), date(2026, 12, 31))


def test_a_month_ending_on_monday_has_a_one_day_last_week():
    # August 2026 ends on a Monday.
    assert last_week(2026, 8) == (date(2026, 8, 31), date(2026, 8, 31))


def test_rows_between_includes_both_ends():
    rows = parse_topic_rows(
        [row(f"{d} жовтня", schedule_id=str(d)) for d in (22, 23, 26, 29, 30)]
        + [row("2 листопада", schedule_id="102")]
    )
    picked = rows_between(rows, date(2026, 10, 26), date(2026, 10, 30), AUTUMN)
    assert [r.schedule_id for r, _ in picked] == ["26", "29", "30"]


def test_the_schedule_id_is_read_from_the_pencil():
    parsed = parse_topic_rows([row("19 жовтня", schedule_id="1001")])[0]
    assert parsed.schedule_id == "1001"


def test_a_row_scraped_without_the_pencil_has_no_id():
    parsed = parse_topic_rows([row("19 жовтня")[:8]])[0]
    assert parsed.schedule_id == ""


# --- lesson types -----------------------------------------------------------


@pytest.mark.parametrize(
    "topic, expected",
    [
        ("Лабораторна робота № 3 «Визначення ККД похилої площини».", "Лабораторна робота"),
        ("Лабораторна робота №1. Вивчення руху тіла по колу.", "Лабораторна робота"),
        ("Контрольна робота №2 з теми «Молекулярна фізика»", "Контрольна робота"),
        ("Контрольна робота №1.", "Контрольна робота"),
        ("контрольна  робота", "Контрольна робота"),
        ("Аналіз контрольної роботи.", None),
        ("Підготовка до контрольної роботи.", None),
        ("Практична робота №1", None),
        ("Електричний струм у металах.", None),
        ("", None),
    ],
)
def test_the_type_is_read_off_the_topic(topic, expected):
    assert lesson_type_for(topic) == expected


def test_only_filled_rows_with_an_id_are_typed():
    rows = parse_topic_rows(
        [
            row("1 жовтня", 1, "Лабораторна робота №1.", "11"),
            row("2 жовтня", 2, "Звичайна тема.", "12"),
            row("5 жовтня", 3, "Контрольна робота №1.", ""),
            row("6 жовтня"),
        ]
    )
    assert [(r.schedule_id, label) for r, label in type_targets(rows)] == [
        ("11", "Лабораторна робота")
    ]


# --- command line -----------------------------------------------------------


def parse(*argv):
    return build_parser().parse_args(["delete-lessons", *argv])


def test_last_week_flag_gives_the_range():
    assert _deletion_range(parse("--last-week", "2026-10")) == (
        date(2026, 10, 26),
        date(2026, 10, 31),
    )


def test_from_alone_is_one_day():
    assert _deletion_range(parse("--from", "2026-10-27")) == (
        date(2026, 10, 27),
        date(2026, 10, 27),
    )


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("--last-week", "2026-10", "--from", "2026-10-01"),
        ("--from", "2026-10-30", "--to", "2026-10-26"),
        ("--from", "30.10.2026"),
    ],
)
def test_a_range_that_makes_no_sense_is_refused(argv):
    with pytest.raises(ValueError):
        _deletion_range(parse(*argv))


# --- the run ----------------------------------------------------------------

PAGE = object()

LINKS = [
    JournalLink("Фізика", "9-А", "u/9a", "9-А"),
    JournalLink("Фізика", "9-Б", "u/9b", "9-Б"),
]

JOURNALS = {
    "u/9a": [
        row("23 жовтня", 22, "Тема", "923"),
        row("26 жовтня", schedule_id="926"),
        row("27 жовтня", schedule_id=""),
        row("29 жовтня", schedule_id="929"),
        row("30 жовтня", schedule_id="930"),
        row("2 листопада", schedule_id="9102"),
    ],
    "u/9b": [
        row("27 жовтня", 20, "Тема з оцінками", "827"),
        row("29 жовтня", schedule_id="829"),
    ],
}
MARKS = {"827": 4}


@pytest.fixture
def site(monkeypatch, tmp_path):
    state = {"deleted": [], "current": None}

    def fake_open(page, link):
        state["current"] = link.url

    def fake_rows(page):
        return parse_topic_rows(JOURNALS[state["current"]], page_url=state["current"])

    def fake_delete(page, target, when):
        state["deleted"].append((target.schedule_id, when))

    monkeypatch.setattr(runner_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner_module, "ensure_logged_in", lambda page: None)
    monkeypatch.setattr(runner_module, "require_current_semester", lambda page: None)
    monkeypatch.setattr(runner_module, "load_journal_links", lambda page: LINKS)
    monkeypatch.setattr(runner_module, "open_journal", fake_open)
    monkeypatch.setattr(runner_module, "current_semester", lambda page: (AUTUMN, None))
    monkeypatch.setattr(topics_module, "read_topic_rows", fake_rows)
    monkeypatch.setattr(journal_module, "show_journal_page", lambda page, url: None)
    monkeypatch.setattr(lessons_module, "marks_by_schedule", lambda page: MARKS)
    monkeypatch.setattr(lessons_module, "delete_lesson", fake_delete)
    return state


def delete(answer="т", **kwargs):
    asked = []

    def ask(question):
        asked.append(question)
        return answer

    code = runner_module.run_delete_lessons(
        PAGE,
        load_schedule(SCHEDULE_PATH),
        date(2026, 10, 26),
        date(2026, 10, 31),
        subject="Фізика",
        ask=ask,
        **{"class_name": None, **kwargs},
    )
    return code, asked


def test_the_range_is_deleted_latest_first(site):
    code, asked = delete(class_name="9-А")
    assert code == 0
    assert len(asked) == 1
    assert [sid for sid, _ in site["deleted"]] == ["930", "929", "926"]


def test_columns_with_marks_are_spared(site):
    delete(class_name="9-Б")
    assert [sid for sid, _ in site["deleted"]] == ["829"]


def test_force_deletes_columns_with_marks_too(site):
    delete(class_name="9-Б", force=True)
    assert [sid for sid, _ in site["deleted"]] == ["829", "827"]


def test_nothing_goes_without_a_yes(site):
    code, asked = delete(answer="н", class_name="9-А")
    assert code == 0 and asked
    assert site["deleted"] == []


def test_dry_run_neither_asks_nor_deletes(site):
    code, asked = delete(class_name="9-А", dry_run=True)
    assert code == 0
    assert asked == [] and site["deleted"] == []


def test_each_deletion_carries_the_date_to_check_against(site):
    delete(class_name="9-А")
    assert ("926", date(2026, 10, 26)) in site["deleted"]


def test_a_row_without_an_id_is_not_planned_for_deletion(site):
    code, _ = delete(class_name="9-А")
    assert code == 0
    assert "" not in [sid for sid, _ in site["deleted"]]


# --- the type follows the topic ---------------------------------------------


class TypeLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


@pytest.mark.parametrize(
    "before, after, expected",
    [
        ("Тема.", "Лабораторна робота №2.", "Лабораторна робота"),
        ("Лабораторна робота №2.", "Тема.", "Поточна"),
        ("Контрольна робота №1.", "Лабораторна робота №2.", "Лабораторна робота"),
        ("Тема.", "Інша тема.", None),
        ("", "Тема.", None),
    ],
)
def test_the_type_follows_the_topic_written(monkeypatch, before, after, expected):
    set_to = []
    monkeypatch.setattr(
        lessons_module,
        "set_lesson_type",
        lambda page, target, label: set_to.append(label) or "було",
    )
    old = parse_topic_rows([row("19 жовтня", 5, before)])[0]
    assert runner_module._type_from_topic(PAGE, TypeLog(), old, after) == 0
    assert set_to == ([expected] if expected else [])
