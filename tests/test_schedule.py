"""Tests for the pure scheduling logic: no browser, no network."""

from datetime import date
from pathlib import Path

import pytest

from nzua.schedule import (
    WEEKDAYS,
    Schedule,
    first_weekday_in_month,
    load_schedule,
    parse_month,
    plan_month,
)

SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "schedule.yaml"


@pytest.fixture(scope="module")
def schedule() -> Schedule:
    return load_schedule(SCHEDULE_PATH)


# --- first_weekday_in_month -------------------------------------------------


def test_first_weekday_when_month_starts_on_that_weekday():
    # 1 June 2026 is a Monday.
    assert first_weekday_in_month(2026, 6, WEEKDAYS["mon"]) == date(2026, 6, 1)


def test_first_weekday_later_in_the_opening_week():
    # 1 September 2026 is a Tuesday.
    assert first_weekday_in_month(2026, 9, WEEKDAYS["tue"]) == date(2026, 9, 1)
    assert first_weekday_in_month(2026, 9, WEEKDAYS["thu"]) == date(2026, 9, 3)
    assert first_weekday_in_month(2026, 9, WEEKDAYS["fri"]) == date(2026, 9, 4)


def test_first_weekday_wraps_into_the_second_week():
    # 1 September 2026 is a Tuesday, so the first Monday is the 7th.
    assert first_weekday_in_month(2026, 9, WEEKDAYS["mon"]) == date(2026, 9, 7)


def test_first_weekday_in_february():
    # 1 February 2026 is a Sunday.
    assert first_weekday_in_month(2026, 2, WEEKDAYS["mon"]) == date(2026, 2, 2)
    assert first_weekday_in_month(2026, 2, WEEKDAYS["fri"]) == date(2026, 2, 6)


def test_first_weekday_is_always_inside_the_requested_month():
    for month in range(1, 13):
        for weekday in range(5):
            result = first_weekday_in_month(2026, month, weekday)
            assert result.year == 2026
            assert result.month == month
            assert result.weekday() == weekday
            assert result.day <= 7


# --- parse_month ------------------------------------------------------------


def test_parse_month():
    assert parse_month("2026-09") == (2026, 9)
    assert parse_month("2026-1") == (2026, 1)


@pytest.mark.parametrize("bad", ["2026", "2026-13", "2026-00", "вересень", "09-2026"])
def test_parse_month_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_month(bad)


# --- loading the real schedule.yaml -----------------------------------------


def test_schedule_totals(schedule):
    assert len(schedule.slots) == 26
    assert len(schedule.filter(subject="Фізика")) == 23
    assert len(schedule.filter(subject="Астрономія")) == 3


def test_lesson_type_and_repeat(schedule):
    assert schedule.lesson_type == "Поточна"
    assert schedule.repeat == "weekly_until_month_end"


def test_cabinet_defaults_to_class_name(schedule):
    for slot in schedule.slots:
        assert slot.cabinet == slot.class_name


def test_no_wednesday_lessons(schedule):
    assert all(slot.weekday != WEEKDAYS["wed"] for slot in schedule.slots)


def test_no_two_lessons_share_a_weekday_and_period(schedule):
    """The teacher cannot be in two rooms at once."""
    seen: dict[tuple[int, int], str] = {}
    for slot in schedule.slots:
        key = (slot.weekday, slot.lesson_no)
        assert key not in seen, f"{slot.class_name} clashes with {seen[key]} at {key}"
        seen[key] = f"{slot.subject} {slot.class_name}"


def test_specific_slots_present(schedule):
    slots = {
        (s.subject, s.class_name, s.weekday, s.lesson_no) for s in schedule.slots
    }
    assert ("Фізика", "9-В", WEEKDAYS["tue"], 2) in slots
    assert ("Фізика", "9-В", WEEKDAYS["tue"], 4) in slots
    assert ("Астрономія", "11-В", WEEKDAYS["mon"], 5) in slots
    assert ("Фізика", "8-Б", WEEKDAYS["thu"], 7) in slots


def test_filter_by_class(schedule):
    eleven_a = schedule.filter(class_name="11-А")
    assert len(eleven_a) == 4  # three physics lessons plus one astronomy
    assert {s.subject for s in eleven_a} == {"Фізика", "Астрономія"}


def test_filter_by_subject_and_class(schedule):
    assert len(schedule.filter(subject="Астрономія", class_name="11-А")) == 1


def test_filter_rejects_unknown_names(schedule):
    with pytest.raises(ValueError):
        schedule.filter(subject="Хімія")
    with pytest.raises(ValueError):
        schedule.filter(class_name="7-А")


# --- plan_month -------------------------------------------------------------


def test_plan_month_covers_every_slot(schedule):
    tasks = plan_month(schedule, 2026, 9)
    assert len(tasks) == 26


def test_plan_month_assigns_the_first_matching_date(schedule):
    tasks = plan_month(schedule, 2026, 9, subject="Астрономія")
    by_class = {t.slot.class_name: t.date for t in tasks}
    assert by_class["11-А"] == date(2026, 9, 1)  # Tuesday
    assert by_class["11-Б"] == date(2026, 9, 3)  # Thursday
    assert by_class["11-В"] == date(2026, 9, 7)  # Monday


def test_plan_month_groups_tasks_by_journal(schedule):
    """Tasks for one subject+class must be adjacent so the journal opens once."""
    tasks = plan_month(schedule, 2026, 9)
    journals = [(t.slot.subject, t.slot.class_name) for t in tasks]
    assert len(set(journals)) == len(
        [k for i, k in enumerate(journals) if i == 0 or journals[i - 1] != k]
    )
