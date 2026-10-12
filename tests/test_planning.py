"""Tests for reading the calendar plans. No browser, no network.

These run against the teacher's real .docx files, because the point of this
module is that it survives the two different layouts those files actually use.
When the folder is absent the docx tests skip, and the YAML tests still run.
"""

from pathlib import Path

import pytest

from nzua.planning import (
    DOCX_SOURCES,
    Lesson,
    Plan,
    PlanError,
    grade_of,
    load_plan,
    parse_planning_docx,
    write_plan,
)

SOURCE_DIR = Path.home() / "Desktop" / "планування"

# filename -> (subject, grade, lesson count, first topic, last topic)
EXPECTED = {
    "8 клас.docx": ("Фізика", 8, 70, "Прості механізми. Похила площина.", "Резерв."),
    "9 клас.docx": (
        "Фізика",
        9,
        105,
        "Електричний струм у металах.",
        "Комплексна підсумкова робота № 6",
    ),
    "10 клас.docx": (
        "Фізика",
        10,
        101,
        "Народження й розвиток фізики як науки.",
        "Узагальнююче заняття «Професія майбутнього»",
    ),
    "11 клас.docx": (
        "Фізика",
        11,
        92,
        "Електричний струм.",
        "Захист навчальних проектів за темою «Атомна та ядерна фізика»",
    ),
    "астрономія.docx": (
        "Астрономія",
        11,
        35,
        "Астрономія – фундаментальна наука",
        "Узагальнювальне заняття.",
    ),
}

needs_docx = pytest.mark.skipif(
    not SOURCE_DIR.exists(), reason=f"немає теки з плануванням: {SOURCE_DIR}"
)


@pytest.fixture(scope="module")
def plans() -> dict[str, Plan]:
    if not SOURCE_DIR.exists():
        pytest.skip("немає теки з плануванням")
    return {
        source.filename: parse_planning_docx(
            SOURCE_DIR / source.filename, source.subject, source.grade
        )
        for source in DOCX_SOURCES
    }


# --- class name to grade ----------------------------------------------------


@pytest.mark.parametrize(
    "class_name,grade",
    [("8-Б", 8), ("9-А", 9), ("9-В", 9), ("10-Б", 10), ("11-В", 11)],
)
def test_grade_of(class_name, grade):
    assert grade_of(class_name) == grade


def test_grade_of_rejects_a_name_without_a_number():
    with pytest.raises(ValueError):
        grade_of("випускний")


# --- the five real documents ------------------------------------------------


@needs_docx
@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_every_plan_has_the_expected_number_of_lessons(plans, filename):
    subject, grade, count, _, _ = EXPECTED[filename]
    plan = plans[filename]
    assert (plan.subject, plan.grade) == (subject, grade)
    assert len(plan.lessons) == count


@needs_docx
@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_lesson_numbers_run_from_one_without_gaps(plans, filename):
    numbers = [lesson.number for lesson in plans[filename].lessons]
    assert numbers == list(range(1, len(numbers) + 1))


@needs_docx
@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_first_and_last_topics(plans, filename):
    _, _, _, first, last = EXPECTED[filename]
    lessons = plans[filename].lessons
    assert lessons[0].topic.startswith(first)
    assert lessons[-1].topic.startswith(last)


@needs_docx
@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_no_topic_is_blank_or_padded(plans, filename):
    for lesson in plans[filename].lessons:
        assert lesson.topic
        assert lesson.topic == lesson.topic.strip()
        assert "  " not in lesson.topic


@needs_docx
def test_section_headings_are_not_mistaken_for_lessons(plans):
    """Rows spanning one cell name a section, not a lesson."""
    topics = [lesson.topic for lesson in plans["9 клас.docx"].lessons]
    assert not any(topic.startswith("РОЗДІЛ") for topic in topics)
    assert not any(topic.startswith("Тема 1.") for topic in topics)

    topics = [lesson.topic for lesson in plans["10 клас.docx"].lessons]
    assert not any(topic.startswith("Вступ (3 години)") for topic in topics)
    assert "Виставлення оцінок за тему." not in topics


@needs_docx
def test_rows_without_a_number_are_skipped_in_the_numbered_format(plans):
    """The numbered plans carry «Демонстрації …» rows that are not lessons."""
    for filename in ("10 клас.docx", "11 клас.docx", "астрономія.docx"):
        topics = [lesson.topic for lesson in plans[filename].lessons]
        assert not any(topic.startswith("Демонстрації") for topic in topics)


@needs_docx
def test_unnumbered_plans_are_numbered_by_position(plans):
    """8 and 9 leave the number column empty, so position supplies it."""
    plan = plans["9 клас.docx"]
    assert plan.lesson(2).topic == "Розв’язування задач."
    assert plan.lesson(105).topic.startswith("Комплексна підсумкова робота № 6")


# --- looking a lesson up ----------------------------------------------------


def test_lesson_lookup():
    plan = Plan(
        subject="Фізика",
        grade=9,
        source="9 клас.docx",
        lessons=(Lesson(1, "Перший"), Lesson(2, "Другий")),
    )
    assert plan.lesson(2).topic == "Другий"


def test_lesson_lookup_past_the_end_says_so():
    plan = Plan("Фізика", 9, "9 клас.docx", (Lesson(1, "Перший"),))
    with pytest.raises(PlanError, match="1 уроків"):
        plan.lesson(2)


# --- YAML round trip --------------------------------------------------------


def test_plan_survives_a_round_trip_through_yaml(tmp_path):
    plan = Plan(
        subject="Астрономія",
        grade=11,
        source="астрономія.docx",
        lessons=(Lesson(1, "Перший урок"), Lesson(2, "Другий «урок»")),
    )
    path = tmp_path / "astronomy-11.yaml"
    write_plan(plan, path)
    assert load_plan(path) == plan


@needs_docx
def test_real_plans_survive_a_round_trip(plans, tmp_path):
    for filename, plan in plans.items():
        path = tmp_path / f"{filename}.yaml"
        write_plan(plan, path)
        assert load_plan(path) == plan
