"""Tests for reading the lesson-topics table. No browser, no network."""

import pytest

from nzua.topics import (
    TopicRow,
    TopicsError,
    due_option_after_current,
    fill_targets,
    resync_targets,
    next_lesson_number,
    parse_topic_rows,
    pending_rows,
)


def row(index, date_text, number="", topic="", due="", homework=""):
    """Build a row the way the page hands one over: eight cell strings."""
    return [
        "",
        date_text,
        str(number),
        "",
        topic,
        due,
        homework,
        "",
    ]


FILLED = [
    row(0, "3 вересня", 1, "Електричний струм у металах.", "на 4 вересня", ""),
    row(1, "4 вересня", 2, "Розв’язування задач.", "на 7 вересня", ""),
]
EMPTY = [row(2, "7 вересня"), row(3, "10 вересня"), row(4, "11 вересня")]


# --- parsing ----------------------------------------------------------------


def test_parse_reads_every_column():
    parsed = parse_topic_rows([FILLED[0]])[0]
    assert parsed.index == 0
    assert parsed.date_text == "3 вересня"
    assert parsed.lesson_number == 1
    assert parsed.topic == "Електричний струм у металах."
    assert parsed.due_text == "на 4 вересня"
    assert parsed.filled


def test_parse_marks_an_untouched_row_as_empty():
    parsed = parse_topic_rows(EMPTY)[0]
    assert parsed.lesson_number is None
    assert parsed.topic == ""
    assert not parsed.filled


def test_parse_numbers_rows_by_position():
    parsed = parse_topic_rows(FILLED + EMPTY)
    assert [p.index for p in parsed] == [0, 1, 2, 3, 4]


def test_parse_rejects_a_row_of_the_wrong_shape():
    with pytest.raises(TopicsError):
        parse_topic_rows([["", "3 вересня"]])


# --- where to continue ------------------------------------------------------


def test_next_lesson_number_continues_the_journal():
    assert next_lesson_number(parse_topic_rows(FILLED + EMPTY)) == 3


def test_next_lesson_number_on_an_untouched_journal_is_one():
    assert next_lesson_number(parse_topic_rows(EMPTY)) == 1


def test_next_lesson_number_continues_past_a_gap_in_the_numbers():
    """1, 2, then 4 is a correction the teacher made: carry on from 4."""
    corrected = [
        row(0, "3 вересня", 1, "Тема", "на 4 вересня"),
        row(1, "4 вересня", 2, "Тема", "на 7 вересня"),
        row(2, "7 вересня", 4, "Тема", "на 10 вересня"),
    ]
    assert next_lesson_number(parse_topic_rows(corrected)) == 5


def test_next_lesson_number_ignores_blank_rows_in_the_middle():
    """A lesson that never happened leaves a hole; the count goes on regardless."""
    gapped = FILLED + [row(2, "7 вересня")] + [
        row(3, "10 вересня", 4, "Тема", "на 11 вересня")
    ]
    assert next_lesson_number(parse_topic_rows(gapped)) == 5


def test_next_lesson_number_when_filled_rows_carry_no_number():
    assert next_lesson_number(parse_topic_rows([row(0, "3 вересня", "", "Тема")])) == 1


def test_pending_rows_are_the_empty_ones_in_order():
    rows = parse_topic_rows(FILLED + EMPTY)
    assert [r.date_text for r in pending_rows(rows)] == [
        "7 вересня",
        "10 вересня",
        "11 вересня",
    ]


def test_pending_rows_on_a_finished_journal_is_empty():
    assert pending_rows(parse_topic_rows(FILLED)) == []


# --- the "homework due" dropdown --------------------------------------------

OPTIONS = [
    {"value": "17034437", "label": "2026-09-03 (Поточний урок)"},
    {"value": "17034441", "label": "2026-09-04"},
    {"value": "17034454", "label": "2026-09-07"},
]


def test_due_option_is_the_one_after_the_current_lesson():
    assert due_option_after_current(OPTIONS) == OPTIONS[1]


def test_due_option_when_the_current_lesson_is_the_last_one():
    """The final lesson of the term has nothing to set homework for."""
    assert due_option_after_current(OPTIONS[:1]) is None


def test_due_option_when_the_list_never_marks_the_current_lesson():
    with pytest.raises(TopicsError, match="Поточний урок"):
        due_option_after_current(OPTIONS[1:])


def test_due_option_when_the_current_lesson_is_not_first():
    """The site puts the current lesson first, but do not rely on it."""
    shuffled = [OPTIONS[1], OPTIONS[0], OPTIONS[2]]
    assert due_option_after_current(shuffled) == OPTIONS[2]


# --- the row record ---------------------------------------------------------


def test_topic_row_describes_itself_for_the_log():
    r = TopicRow(0, "3 вересня", 1, "Тема уроку", "на 4 вересня", "", "")
    assert "3 вересня" in r.describe()
    assert "Тема уроку" in r.describe()


# --- deciding what to write, up front ---------------------------------------


def test_fill_targets_pairs_rows_with_lesson_numbers():
    rows = parse_topic_rows(FILLED + EMPTY)
    assert fill_targets(rows, 2) == [(2, 3), (3, 4)]


def test_fill_targets_starts_at_one_on_an_empty_journal():
    assert fill_targets(parse_topic_rows(EMPTY), 3) == [(0, 1), (1, 2), (2, 3)]


def test_fill_targets_stops_at_the_end_of_the_journal():
    rows = parse_topic_rows(FILLED + EMPTY)
    assert fill_targets(rows, 99) == [(2, 3), (3, 4), (4, 5)]


def test_fill_targets_on_a_finished_journal_is_empty():
    assert fill_targets(parse_topic_rows(FILLED), 5) == []


def test_fill_targets_start_after_the_last_filled_row_not_the_first_hole():
    """The hole at 4 вересня is a lesson that did not happen: leave it alone."""
    holed = [
        row(0, "3 вересня", 1, "Тема", "на 4 вересня"),
        row(1, "4 вересня"),
        row(2, "7 вересня", 6, "Тема", "на 10 вересня"),
        row(3, "10 вересня"),
        row(4, "11 вересня"),
    ]
    assert fill_targets(parse_topic_rows(holed), 2) == [(3, 7), (4, 8)]


def test_fill_targets_are_decided_once_not_row_by_row():
    """Every target has a distinct row: a row can never be written twice."""
    targets = fill_targets(parse_topic_rows(EMPTY), 3)
    assert len({index for index, _ in targets}) == len(targets)


# --- repairing a journal that drifted ---------------------------------------

PLAN = {
    1: "Урок один",
    2: "Урок два",
    3: "Урок три",
    4: "Урок чотири",
}


def test_resync_finds_nothing_when_the_journal_is_correct():
    rows = parse_topic_rows(
        [
            row(0, "3 вересня", 1, "Урок один", "на 4 вересня"),
            row(1, "4 вересня", 2, "Урок два", "на 7 вересня"),
        ]
    )
    assert resync_targets(rows, PLAN.__getitem__) == []


def test_resync_catches_a_shifted_number():
    """The real failure: a row was overwritten, shifting everything after it."""
    rows = parse_topic_rows(
        [
            row(0, "3 вересня", 1, "Урок один", "на 4 вересня"),
            row(1, "4 вересня", 3, "Урок три", "на 7 вересня"),
            row(2, "7 вересня", 4, "Урок чотири", "на 10 вересня"),
        ]
    )
    assert resync_targets(rows, PLAN.__getitem__) == [(1, 2), (2, 3)]


def test_resync_catches_a_right_number_with_the_wrong_topic():
    rows = parse_topic_rows([row(0, "3 вересня", 1, "Зовсім інша тема")])
    assert resync_targets(rows, PLAN.__getitem__) == [(0, 1)]


def test_resync_includes_an_empty_row_among_the_written_ones():
    """The hole is the whole point: it takes its number, the rest shift down."""
    rows = parse_topic_rows(
        [
            row(0, "3 вересня", 1, "Урок один", "на 4 вересня"),
            row(1, "4 вересня"),
            row(2, "7 вересня", 2, "Урок два", "на 10 вересня"),
        ]
    )
    assert resync_targets(rows, PLAN.__getitem__) == [(1, 2), (2, 3)]


def test_resync_leaves_the_lessons_still_to_come_alone():
    """Rows after the last filled one are future lessons, not mistakes."""
    rows = parse_topic_rows(
        [
            row(0, "3 вересня", 1, "Урок один", "на 4 вересня"),
            row(1, "4 вересня"),
            row(2, "7 вересня"),
        ]
    )
    assert resync_targets(rows, PLAN.__getitem__) == []


def test_resync_keeps_a_topic_the_teacher_extended():
    """«Вступний інструктаж.» is hers; rewriting would wipe it every run."""
    plan = {1: "Електричний струм у металах."}
    rows = parse_topic_rows(
        [row(0, "3 вересня", 1, "Вступний інструктаж. Електричний струм у металах.")]
    )
    assert resync_targets(rows, plan.__getitem__) == []


def test_resync_ignores_differences_in_whitespace():
    rows = parse_topic_rows([row(0, "3 вересня", 1, "Урок   один\n")])
    assert resync_targets(rows, PLAN.__getitem__) == []
