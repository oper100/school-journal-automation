"""Tests for the homework store. No browser, no network."""

import pytest

from nzua.homework import (
    HomeworkEntry,
    HomeworkError,
    combine,
    harvest,
    load_store,
    load_store_if_present,
    store_of,
    topics_match,
    write_store,
)
from nzua.topics import homework_targets, parse_topic_rows


def row(date_text, number="", topic="", due="", homework=""):
    """One row as the page hands it over: eight cell strings."""
    return ["", date_text, str(number), "", topic, due, homework, ""]


ROWS = [
    row("3 вересня", 1, "Електричний струм у металах.", "на 4 вересня", "§1, впр. 1"),
    row("4 вересня", 2, "Розв'язування задач.", "на 7 вересня", "§1, впр. 2"),
    row("7 вересня", 3, "Електроліз.", "на 10 вересня", ""),
    row("10 вересня"),
]


# --- reading a journal ------------------------------------------------------


def test_harvest_takes_only_rows_that_have_homework():
    entries = harvest(parse_topic_rows(ROWS))
    assert [entry.number for entry in entries] == [1, 2]


def test_harvest_keeps_the_topic_beside_the_homework():
    first = harvest(parse_topic_rows(ROWS))[0]
    assert first.topic == "Електричний струм у металах."
    assert first.homework == "§1, впр. 1"


def test_harvest_skips_a_row_with_no_lesson_number():
    numberless = [row("3 вересня", "", "Тема", "на 4 вересня", "§1")]
    assert harvest(parse_topic_rows(numberless)) == []


def test_harvest_folds_the_line_breaks_the_page_adds():
    wrapped = [row("3 вересня", 1, "Тема  уроку\nдалі", "", "§1")]
    assert harvest(parse_topic_rows(wrapped))[0].topic == "Тема уроку далі"


# --- answering "what homework goes with this lesson" ------------------------

STORE = store_of(
    "Фізика",
    9,
    [
        HomeworkEntry(1, "Електричний струм у металах.", "§1, впр. 1"),
        HomeworkEntry(2, "Розв'язування задач.", "§1, впр. 2"),
        HomeworkEntry(5, "Розв'язування задач.", "§3, впр. 5"),
        HomeworkEntry(9, "Електричний струм у газах.", "§7"),
    ],
)


def test_lookup_matches_on_number_and_topic_together():
    assert STORE.lookup(2, "Розв'язування задач.") == "§1, впр. 2"
    assert STORE.lookup(5, "Розв'язування задач.") == "§3, впр. 5"


def test_lookup_ignores_differences_in_whitespace():
    assert STORE.lookup(1, "Електричний   струм у металах.\n") == "§1, впр. 1"


def test_lookup_follows_the_topic_when_the_plan_was_renumbered():
    """Last year the topic was lesson 9; this year it is lesson 8."""
    assert STORE.lookup(8, "Електричний струм у газах.") == "§7"


def test_lookup_refuses_a_repeated_topic_under_the_wrong_number():
    """«Розв'язування задач.» is two different lessons: do not guess."""
    assert STORE.lookup(7, "Розв'язування задач.") is None


def test_lookup_on_a_topic_the_store_never_saw():
    assert STORE.lookup(3, "Електроліз.") is None


def test_lookup_allows_a_repeated_topic_when_the_homework_agrees():
    store = store_of(
        "Фізика",
        9,
        [
            HomeworkEntry(2, "Розв'язування задач.", "§1"),
            HomeworkEntry(5, "Розв'язування задач.", "§1"),
        ],
    )
    assert store.lookup(7, "Розв'язування задач.") == "§1"


# --- merging runs together --------------------------------------------------


def test_combine_lets_the_first_side_win():
    newer = [HomeworkEntry(1, "Тема", "нове")]
    older = [HomeworkEntry(1, "Тема", "старе")]
    entries, overridden = combine(newer, older)
    assert [entry.homework for entry in entries] == ["нове"]
    assert overridden == 1


def test_combine_keeps_lessons_only_the_second_side_has():
    entries, overridden = combine(
        [HomeworkEntry(1, "Тема", "нове")], [HomeworkEntry(2, "Інша", "старе")]
    )
    assert [entry.number for entry in entries] == [1, 2]
    assert overridden == 0


def test_combine_does_not_count_agreement_as_an_override():
    _, overridden = combine(
        [HomeworkEntry(1, "Тема", "те саме")], [HomeworkEntry(1, "Тема", "те саме")]
    )
    assert overridden == 0


def test_combine_sorts_by_lesson_number():
    entries, _ = combine(
        [HomeworkEntry(5, "П'ятий", "§5")], [HomeworkEntry(2, "Другий", "§2")]
    )
    assert [entry.number for entry in entries] == [2, 5]


# --- the file on disk -------------------------------------------------------


def test_store_survives_a_write_and_a_read(tmp_path):
    path = write_store(STORE, tmp_path / "physics-9.yaml")
    back = load_store(path)
    assert back == STORE


def test_write_keeps_the_sources_it_was_given(tmp_path):
    store = store_of("Фізика", 9, STORE.entries, ["2025-2026 [1] 9-А"])
    back = load_store(write_store(store, tmp_path / "physics-9.yaml"))
    assert back.sources == ("2025-2026 [1] 9-А",)


def test_sources_are_not_repeated():
    store = store_of("Фізика", 9, (), ["2025-2026 [1] 9-А", "2025-2026 [1] 9-А"])
    assert store.sources == ("2025-2026 [1] 9-А",)


def test_missing_file_is_not_an_error(tmp_path):
    assert load_store_if_present(tmp_path / "nothing.yaml") is None


def test_a_file_of_the_wrong_shape_says_so(tmp_path):
    path = tmp_path / "physics-9.yaml"
    path.write_text("subject: Фізика\n", encoding="utf-8")
    with pytest.raises(HomeworkError, match="physics-9.yaml"):
        load_store(path)


# --- which rows the second pass touches -------------------------------------


def test_homework_targets_are_filled_rows_with_no_homework():
    rows = parse_topic_rows(ROWS)
    store = store_of("Фізика", 9, [HomeworkEntry(3, "Електроліз.", "§4")])
    assert homework_targets(rows, store.lookup) == [(2, 3, "§4")]


def test_homework_targets_leave_rows_that_already_have_homework():
    rows = parse_topic_rows(ROWS[:2])
    assert homework_targets(rows, STORE.lookup) == []


def test_homework_targets_skip_rows_with_no_topic():
    rows = parse_topic_rows([row("10 вересня")])
    assert homework_targets(rows, lambda number, topic: "§1") == []


def test_homework_targets_skip_what_the_store_cannot_answer():
    rows = parse_topic_rows([row("7 вересня", 3, "Електроліз.", "на 10 вересня")])
    assert homework_targets(rows, STORE.lookup) == []


# --- a topic the teacher extended by hand -----------------------------------


def test_topics_match_when_one_is_the_other_with_a_note_in_front():
    """«Вступний інструктаж.» is added to the first lesson every September."""
    assert topics_match(
        "Електричний струм.", "Вступний інструктаж. Електричний струм."
    )


def test_topics_match_when_the_plan_carries_a_trailing_note():
    assert topics_match(
        "Практична робота №1",
        "Практична робота №1 (Із трьох варіантів можна обрати один)",
    )


def test_topics_do_not_match_on_a_short_fragment():
    """A few characters inside a long topic prove nothing."""
    assert not topics_match("Задачі.", "Розв'язування задач. Задачі.")


def test_topics_do_not_match_on_different_lessons():
    assert not topics_match("Електричний струм у газах.", "Електроліз.")


def test_lookup_accepts_the_extended_topic_under_the_same_number():
    store = store_of(
        "Фізика",
        11,
        [HomeworkEntry(1, "Вступний інструктаж. Електричний струм.", "§1")],
    )
    assert store.lookup(1, "Електричний струм.") == "§1"


def test_the_fallback_by_topic_stays_strict():
    """Without a matching number there is nothing to back a loose match up."""
    store = store_of(
        "Фізика",
        11,
        [HomeworkEntry(1, "Вступний інструктаж. Електричний струм.", "§1")],
    )
    assert store.lookup(7, "Електричний струм.") is None
