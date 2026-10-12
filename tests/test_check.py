"""Tests for the journal integrity check. No browser, no network."""

from nzua.topics import check_rows, parse_topic_rows


def row(date_text, number="", topic="", due="", homework=""):
    return ["", date_text, str(number), "", topic, due, homework, ""]


# Real topics are a sentence long; a short label would never clear the bar
# `topics_match` sets for calling a fragment a match.
PLAN = {
    1: "Електричний струм у металах.",
    2: "Розв'язування задач про опір.",
    3: "Лабораторна робота № 1.",
    4: "Електричний струм в електролітах.",
    5: "Застосування електролізу.",
}


def check(raw, homework=lambda number, topic: "§1"):
    return check_rows(parse_topic_rows(raw), PLAN.get, homework)


def kinds(issues):
    return [issue.kind for issue in issues]


# --- a journal with nothing wrong -------------------------------------------


def test_a_clean_journal_has_nothing_to_report():
    clean = [
        row("3 вересня", 1, "Електричний струм у металах.", "на 4 вересня", "§1"),
        row("4 вересня", 2, "Розв'язування задач про опір.", "на 7 вересня", "§2"),
        row("7 вересня"),
    ]
    assert check(clean) == []


def test_trailing_empty_rows_are_normal():
    """Lessons not taught yet: the whole point of fill-topics."""
    clean = [row("3 вересня", 1, "Електричний струм у металах.", "", "§1")]
    assert check(clean + [row("4 вересня")]) == []


# --- holes and jumps --------------------------------------------------------


def test_an_empty_row_before_a_filled_one_is_reported():
    holed = [
        row("3 вересня", 1, "Електричний струм у металах.", "", "§1"),
        row("4 вересня"),
        row("7 вересня", 2, "Розв'язування задач про опір.", "", "§2"),
    ]
    assert kinds(check(holed)) == ["hole"]


def test_a_jump_in_the_numbers_is_reported():
    jumped = [
        row("3 вересня", 1, "Електричний струм у металах.", "", "§1"),
        row("4 вересня", 2, "Розв'язування задач про опір.", "", "§2"),
        row("7 вересня", 4, "Електричний струм в електролітах.", "", "§4"),
    ]
    issues = check(jumped)
    assert kinds(issues) == ["jump"]
    assert issues[0].date_text == "7 вересня"
    assert "3" in issues[0].detail  # says which number is missing


def test_a_repeated_number_is_reported():
    doubled = [
        row("3 вересня", 1, "Електричний струм у металах.", "", "§1"),
        row("4 вересня", 1, "Електричний струм у металах.", "", "§1"),
    ]
    assert kinds(check(doubled)) == ["duplicate"]


def test_a_number_that_goes_backwards_is_reported():
    backwards = [
        row("3 вересня", 3, "Лабораторна робота № 1.", "", "§3"),
        row("4 вересня", 2, "Розв'язування задач про опір.", "", "§2"),
    ]
    assert kinds(check(backwards)) == ["backwards"]


def test_a_filled_row_with_no_number_is_reported():
    bare = [row("3 вересня", "", "Електричний струм у металах.", "", "§1")]
    assert kinds(check(bare)) == ["no-number"]


# --- topic against the plan -------------------------------------------------


def test_a_topic_that_is_not_the_plans_is_reported():
    wrong = [row("3 вересня", 1, "Зовсім інша тема", "", "§1")]
    issues = check(wrong)
    assert kinds(issues) == ["topic"]
    assert "Електричний струм у металах." in issues[0].detail


def test_a_topic_the_teacher_extended_is_not_a_complaint():
    extended = [
        row("3 вересня", 1, "Вступний інструктаж. Електричний струм у металах.", "", "§1")
    ]
    assert check(extended) == []


def test_a_number_the_plan_does_not_reach_is_reported():
    beyond = [row("3 вересня", 40, "Хтозна що", "", "§40")]
    assert kinds(check(beyond)) == ["no-plan"]


# --- homework ---------------------------------------------------------------


def test_a_row_without_homework_the_store_could_fill_is_reported():
    bare = [row("3 вересня", 1, "Електричний струм у металах.")]
    issues = check(bare, homework=lambda number, topic: "§1")
    assert kinds(issues) == ["homework-pending"]


def test_a_row_without_homework_the_store_cannot_fill_is_reported_too():
    bare = [row("3 вересня", 1, "Електричний струм у металах.")]
    issues = check(bare, homework=lambda number, topic: None)
    assert kinds(issues) == ["homework-missing"]


def test_homework_is_not_asked_about_on_an_empty_row():
    assert check([row("3 вересня")]) == []


# --- several at once --------------------------------------------------------


def test_every_issue_of_a_row_is_reported_not_just_the_first():
    messy = [
        row("3 вересня", 1, "Електричний струм у металах.", "", "§1"),
        row("4 вересня", 4, "Зовсім інша тема"),
    ]
    assert kinds(check(messy, homework=lambda n, t: None)) == [
        "jump",
        "topic",
        "homework-missing",
    ]


def test_issues_carry_the_row_they_belong_to():
    messy = [
        row("3 вересня", 1, "Електричний струм у металах.", "", "§1"),
        row("4 вересня", 9, "Хтозна"),
    ]
    assert {issue.index for issue in check(messy)} == {1}
