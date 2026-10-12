"""Tests for the journal-page parsing that needs no browser."""

from datetime import date

import pytest

from nzua.journal import (
    JournalError,
    JournalLink,
    JournalNotFound,
    chosen_semester,
    column_dates,
    find_journal,
    normalise_class,
    parse_month_marker,
    parse_semester_label,
    parse_semester_option,
    previous_academic_year,
    semesters_of_year,
)

SEPT = date(2026, 9, 1)


# --- class labels -----------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        (" 9-А", "9-А"),
        ("10-Б", "10-Б"),
        (" 9-Б(1)", "9-Б"),
        ("11-Б(I група)", "11-Б"),
        ("11-Б(ІІ група)", "11-Б"),
    ],
)
def test_normalise_class(label, expected):
    assert normalise_class(label) == expected


# --- month markers ----------------------------------------------------------


@pytest.mark.parametrize(
    "marker,month",
    [("Вер.", 9), ("Жовт.", 10), ("Лист.", 11), ("Груд.", 12), ("Січ.", 1)],
)
def test_parse_month_marker(marker, month):
    assert parse_month_marker(marker) == month


def test_parse_month_marker_ignores_nonsense():
    assert parse_month_marker("??") is None


# --- rebuilding column dates ------------------------------------------------


def test_column_dates_within_one_month():
    cells = [("1 Вер.", "Вер."), ("2", None), ("8", None)]
    assert column_dates(cells, SEPT) == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 8),
    ]


def test_column_dates_across_a_month_boundary():
    cells = [("29", None), ("30", None), ("6 Жовт.", "Жовт."), ("7", None)]
    assert column_dates(cells, date(2026, 9, 29)) == [
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 6),
        date(2026, 10, 7),
    ]


def test_column_dates_roll_the_year_over_into_january():
    cells = [("22 Груд.", "Груд."), ("12 Січ.", "Січ.")]
    assert column_dates(cells, date(2026, 9, 1)) == [
        date(2026, 12, 22),
        date(2027, 1, 12),
    ]


def test_column_dates_on_an_empty_journal():
    assert column_dates([], SEPT) == []


def test_column_dates_keeps_repeats():
    """Two lessons on one day mean two columns with the same date."""
    cells = [("1 Вер.", "Вер."), ("1", None)]
    assert column_dates(cells, SEPT) == [date(2026, 9, 1), date(2026, 9, 1)]


# --- semester range ---------------------------------------------------------


def test_parse_semester_label():
    label = "2026-2027 [1], 01.09.2026 - 31.12.2026 (поточний)"
    assert parse_semester_label(label) == (date(2026, 9, 1), date(2026, 12, 31))


def test_parse_semester_label_rejects_a_label_without_dates():
    with pytest.raises(ValueError):
        parse_semester_label("2026-2027 [1]")


# --- picking a journal ------------------------------------------------------


LINKS = [
    JournalLink("Фізика", "9-А", "https://nz.ua/journal/index?journal=1", " 9-А"),
    JournalLink("Фізика", "9-Б", "https://nz.ua/journal/index?journal=2", " 9-Б(1)"),
    JournalLink("Астрономія", "11-А", "https://nz.ua/journal/index?journal=3", "11-А"),
    JournalLink("Інформатика", "11-Б", "https://nz.ua/journal/index?journal=4", "11-Б(I група)"),
    JournalLink("Інформатика", "11-Б", "https://nz.ua/journal/index?journal=5", "11-Б(II група)"),
]


def test_find_journal_matches_subject_and_class():
    assert find_journal(LINKS, "Астрономія", "11-А").url.endswith("journal=3")


def test_find_journal_accepts_a_single_subgroup_journal():
    assert find_journal(LINKS, "Фізика", "9-Б").url.endswith("journal=2")


def test_find_journal_refuses_to_guess_between_subgroups():
    with pytest.raises(JournalNotFound, match="неоднозначний"):
        find_journal(LINKS, "Інформатика", "11-Б")


def test_find_journal_reports_what_is_available():
    with pytest.raises(JournalNotFound, match="Фізика 9-А"):
        find_journal(LINKS, "Хімія", "9-А")


# --- the semester dropdown --------------------------------------------------

# Copied from the recon dump, trailing spaces and all.
SEMESTER_LABELS = [
    ("1004", "2026-2027 [1], 01.09.2026 - 31.12.2026 (поточний)"),
    ("1003", "2025-2026 [2], 07.01.2026 - 05.06.2026 "),
    ("1002", "2025-2026 [1], 01.09.2025 - 29.12.2025 "),
    ("1001", "2024-2025 [1], 02.09.2024 - 27.12.2024 "),
]
SEMESTERS = [
    parse_semester_option(label, value, chosen=(value == "1004"))
    for value, label in SEMESTER_LABELS
]


def test_semester_option_reads_the_year_and_the_half():
    option = SEMESTERS[1]
    assert option.academic_year == "2025-2026"
    assert option.number == 2
    assert option.start == date(2026, 1, 7)
    assert option.end == date(2026, 6, 5)


def test_semester_option_spots_the_live_one():
    assert SEMESTERS[0].live
    assert not SEMESTERS[1].live


def test_semester_option_refuses_a_label_it_cannot_read():
    with pytest.raises(ValueError, match="навчального року"):
        parse_semester_option("01.09.2026 - 31.12.2026")


def test_chosen_semester_is_the_one_the_server_marked():
    assert chosen_semester(SEMESTERS).value == "1004"


def test_chosen_semester_refuses_when_nothing_is_marked():
    loose = [parse_semester_option(label, value) for value, label in SEMESTER_LABELS]
    with pytest.raises(JournalError, match="вибраний"):
        chosen_semester(loose)


def test_previous_academic_year_is_the_one_before_the_live_one():
    assert previous_academic_year(SEMESTERS) == "2025-2026"


def test_previous_academic_year_refuses_without_a_live_semester():
    loose = [parse_semester_option(label, value) for value, label in SEMESTER_LABELS[1:]]
    with pytest.raises(JournalError, match="поточний"):
        previous_academic_year(loose)


def test_semesters_of_year_returns_both_halves_in_order():
    picked = semesters_of_year(SEMESTERS, "2025-2026")
    assert [option.number for option in picked] == [1, 2]


def test_semesters_of_year_on_a_year_that_is_not_there():
    assert semesters_of_year(SEMESTERS, "2019-2020") == []


def test_semester_describe_names_the_dates():
    assert "01.09.2026 - 31.12.2026" in SEMESTERS[0].describe()
