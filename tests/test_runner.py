"""The whole-run commands, with the browser replaced by fakes.

Only the orchestration is exercised here: which semesters are visited, which
journals are read in each, where the entries end up, and — the part that can
spoil the next run — that the semester is put back even when a journal blows
up half-way.
"""

import shutil

import pytest

from nzua import journal as journal_module
from nzua import runner as runner_module
from nzua import topics as topics_module
from nzua.cli import SCHEDULE_PATH
from nzua.homework import load_store
from nzua.journal import JournalLink, parse_semester_option
from nzua.schedule import load_schedule
from nzua.topics import parse_topic_rows

PAGE = object()  # every call that would touch it is replaced

SEMESTERS = [
    parse_semester_option(
        "2026-2027 [1], 01.09.2026 - 31.12.2026 (поточний)", "now", chosen=True
    ),
    parse_semester_option("2025-2026 [2], 07.01.2026 - 05.06.2026", "past2"),
    parse_semester_option("2025-2026 [1], 01.09.2025 - 29.12.2025", "past1"),
    parse_semester_option("2024-2025 [1], 02.09.2024 - 27.12.2024", "older"),
]


def link(subject, class_name, url):
    return JournalLink(subject, class_name, url, class_name)


LINKS = {
    "now": [
        link("Фізика", "9-А", "u/now-9a"),
        link("Фізика", "9-Б", "u/now-9b"),
    ],
    "past1": [
        link("Фізика", "9-А", "u/p1-9a"),
        link("Астрономія", "11-В", "u/p1-11v"),
        link("Історія", "5-А", "u/p1-5a"),  # not ours: no plan, no store
    ],
    "past2": [link("Фізика", "9-А", "u/p2-9a")],
}


def row(date_text, number="", topic="", homework=""):
    return ["", date_text, str(number), "", topic, "", homework, ""]


ROWS = {
    "u/now-9a": [row("3 вересня", 1, "Тема перша", "§1 цьогоріч")],
    "u/now-9b": [row("3 вересня", 1, "Тема перша", "")],
    "u/p1-9a": [
        row("2 вересня", 1, "Тема перша", "§1 торік"),
        row("3 вересня", 2, "Тема друга", "§2 торік"),
    ],
    "u/p1-11v": [row("2 вересня", 1, "Астрономія перша", "§1 астро")],
    "u/p1-5a": [row("2 вересня", 1, "Історія перша", "§1 історія")],
    "u/p2-9a": [
        row("9 січня", 40, "Тема сорокова", "§40 торік"),
        row("12 січня", 41, "Тема перша", "§1 пізніше"),
    ],
}


@pytest.fixture
def site(monkeypatch, tmp_path):
    """A stand-in nz.ua: a semester dropdown, journals, and their topic rows."""

    state = {"semester": "now", "visited": [], "switches": [], "opened": []}

    def fake_select_semester(page, value):
        state["switches"].append(value)
        state["semester"] = value

    def fake_links(page):
        return LINKS[state["semester"]]

    def fake_open_journal(page, journal_link):
        state["opened"].append(journal_link.url)
        state["current"] = journal_link.url

    def fake_rows(page):
        url = state["current"]
        if url not in ROWS:
            raise RuntimeError(f"журнал {url} не відкривається")
        return parse_topic_rows(ROWS[url])

    # The calendar plans are read from the project root, which is moved aside
    # so nothing real gets written; they have to move with it.
    shutil.copytree(SCHEDULE_PATH.parent / "planning", tmp_path / "planning")
    monkeypatch.setattr(runner_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner_module, "ensure_logged_in", lambda page: None)
    monkeypatch.setattr(
        runner_module, "require_current_semester", lambda page: None
    )
    monkeypatch.setattr(runner_module, "load_journal_links", fake_links)
    monkeypatch.setattr(journal_module, "semester_options", lambda page: SEMESTERS)
    monkeypatch.setattr(journal_module, "select_semester", fake_select_semester)
    monkeypatch.setattr(journal_module, "open_journal", fake_open_journal)
    monkeypatch.setattr(topics_module, "read_topic_rows", fake_rows)
    return state


@pytest.fixture
def schedule():
    return load_schedule(SCHEDULE_PATH)


def run(schedule, **kwargs):
    return runner_module.run_dump_homework(PAGE, schedule, **kwargs)


# --- walking past semesters -------------------------------------------------


def test_the_previous_year_is_the_one_walked(site, schedule):
    assert run(schedule) == 0
    assert site["switches"] == ["past1", "past2", "now"]


def test_the_semester_is_put_back_at_the_end(site, schedule):
    run(schedule)
    assert site["switches"][-1] == "now"
    assert site["semester"] == "now"


def test_the_semester_is_put_back_even_after_a_broken_journal(
    site, schedule, monkeypatch
):
    monkeypatch.setitem(LINKS, "past1", [link("Фізика", "9-А", "u/missing")])
    assert run(schedule) == 1  # the failure is reported, not swallowed
    assert site["semester"] == "now"


def test_subjects_we_have_no_plan_for_are_not_opened(site, schedule):
    run(schedule)
    assert "u/p1-5a" not in site["opened"]


def test_entries_land_in_the_file_of_their_year_group(site, schedule, tmp_path):
    run(schedule)
    store = load_store(tmp_path / "homework" / "physics-9.yaml")
    assert store.grade == 9
    assert {entry.number for entry in store.entries} == {1, 2, 40, 41}


def test_astronomy_gets_its_own_file(site, schedule, tmp_path):
    run(schedule)
    store = load_store(tmp_path / "homework" / "astronomy-11.yaml")
    assert store.entries[0].homework == "§1 астро"


def test_the_first_semester_read_wins_a_disagreement(site, schedule, tmp_path):
    """Both halves of the year number a lesson 1; the autumn one is read first."""
    run(schedule)
    store = load_store(tmp_path / "homework" / "physics-9.yaml")
    assert store.lookup(1, "Тема перша") == "§1 торік"


def test_sources_say_where_each_file_came_from(site, schedule, tmp_path):
    run(schedule)
    store = load_store(tmp_path / "homework" / "physics-9.yaml")
    assert "2025-2026 [1] 9-А" in store.sources


def test_dry_run_writes_nothing(site, schedule, tmp_path):
    assert run(schedule, dry_run=True) == 0
    assert not (tmp_path / "homework").exists()


def test_listing_semesters_switches_nothing(site, schedule, tmp_path):
    assert run(schedule, list_only=True) == 0
    assert site["switches"] == []
    assert not (tmp_path / "homework").exists()


def test_a_named_semester_is_the_only_one_walked(site, schedule):
    assert run(schedule, semester="2025-2026 [2]") == 0
    assert site["switches"] == ["past2", "now"]


def test_a_semester_name_that_matches_nothing_is_an_error(site, schedule):
    assert run(schedule, semester="2019-2020") == 1
    assert site["switches"] == []


# --- copying one class of the current semester ------------------------------


def test_from_class_reads_only_that_journal(site, schedule):
    assert run(schedule, from_classes=("9-А",)) == 0
    assert site["opened"] == ["u/now-9a"]


def test_from_class_does_not_leave_the_current_semester(site, schedule):
    run(schedule, from_classes=("9-А",))
    assert set(site["switches"]) == {"now"}


def test_from_class_fills_the_store_the_other_classes_read(
    site, schedule, tmp_path
):
    """This is 9-А -> 9-Б: what the dump writes is what fill-topics looks up."""
    run(schedule, from_classes=("9-А",))
    store = load_store(tmp_path / "homework" / "physics-9.yaml")
    assert store.lookup(1, "Тема перша") == "§1 цьогоріч"


def test_an_existing_file_keeps_the_lessons_the_new_run_never_saw(
    site, schedule, tmp_path
):
    run(schedule)  # lessons 1, 2, 40 and 41
    assert run(schedule, from_classes=("9-А",)) == 0  # lesson 1 only
    store = load_store(tmp_path / "homework" / "physics-9.yaml")
    assert {entry.number for entry in store.entries} == {1, 2, 40, 41}
    assert store.lookup(1, "Тема перша") == "§1 цьогоріч"  # the newer run wins


def test_several_classes_are_read_in_one_go(site, schedule):
    assert run(schedule, from_classes=("9-А", "9-Б")) == 0
    assert site["opened"] == ["u/now-9a", "u/now-9b"]


# --- the check command ------------------------------------------------------


def test_check_visits_every_journal_of_the_schedule(site, schedule):
    assert runner_module.run_check(PAGE, schedule, class_name="9-А") == 0
    assert site["opened"] == ["u/now-9a"]


def test_check_reports_a_journal_it_cannot_open(site, schedule, monkeypatch):
    monkeypatch.setitem(LINKS, "now", [link("Фізика", "9-А", "u/missing")])
    assert runner_module.run_check(PAGE, schedule, class_name="9-А") == 1


def test_check_writes_nothing(site, schedule, tmp_path):
    runner_module.run_check(PAGE, schedule, class_name="9-А")
    assert not (tmp_path / "homework").exists()


# --- bringing a journal that drifted back onto the plan ---------------------


@pytest.fixture
def journal(monkeypatch, tmp_path):
    """One journal whose rows and console answers a test controls."""
    from nzua import planning

    plan = planning.load_plan(SCHEDULE_PATH.parent / "planning" / "physics-9.yaml")
    state = {
        "rows": [], "written": [], "answers": [], "asked": [],
        "types_failed": 0, "homework_passes": 0,
    }

    def fake_rows(page):
        return parse_topic_rows(state["rows"])

    def fake_write(page, log, plan, store, rows, targets):
        state["written"].append(list(targets))
        return len(targets), 0, state["types_failed"]

    def fake_homework(page, log, store, rows):
        state["homework_passes"] += 1
        return 0, 0

    monkeypatch.setattr(topics_module, "read_topic_rows", fake_rows)
    monkeypatch.setattr(runner_module, "_write_targets", fake_write)
    monkeypatch.setattr(runner_module, "_add_missing_homework", fake_homework)
    monkeypatch.setattr(journal_module, "open_journal", lambda page, link: None)
    state["plan"] = plan
    state["log"] = runner_module.Log(tmp_path / "run.log")
    return state


def ask_from(state):
    def ask(question):
        state["asked"].append(question)
        return state["answers"].pop(0) if state["answers"] else ""

    return ask


def fill(state, schedule, count=0, resync=False, decisions=None):
    return runner_module._fill_one_journal(
        PAGE,
        state["log"],
        LINKS["now"],
        state["plan"],
        schedule,
        "Фізика",
        "9-А",
        count,
        resync,
        ask_from(state),
        decisions if decisions is not None else {},
    )


DRIFTED = [
    ["", "3 вересня", "1", "", "Електричний струм у металах. Залежність електричного "
     "опору металу від температури, температурний коефіцієнт опору. Явище "
     "надпровідності.", "", "§1", ""],
    ["", "4 вересня", "", "", "", "", "", ""],
    ["", "7 вересня", "2", "", "Розв’язування задач.", "", "§2", ""],
]


def test_a_drifted_journal_asks_before_rewriting(journal, schedule):
    journal["rows"] = DRIFTED
    journal["answers"] = ["н"]
    fill(journal, schedule)
    assert "Переписати журнал" in journal["asked"][0]


def test_saying_no_leaves_the_journal_alone(journal, schedule):
    journal["rows"] = DRIFTED
    journal["answers"] = ["н"]
    fill(journal, schedule)
    assert journal["written"] == []


def test_saying_yes_renumbers_every_row_from_the_hole_down(journal, schedule):
    journal["rows"] = DRIFTED
    journal["answers"] = ["т"]
    fill(journal, schedule)
    assert journal["written"] == [[(1, 2), (2, 3)]]


def test_resync_rewrites_without_asking(journal, schedule):
    journal["rows"] = DRIFTED
    fill(journal, schedule, resync=True)
    assert journal["asked"] == []
    assert journal["written"] == [[(1, 2), (2, 3)]]


def test_answering_for_all_is_not_asked_again(journal, schedule):
    journal["rows"] = DRIFTED
    journal["answers"] = ["у"]
    decisions = {}
    fill(journal, schedule, decisions=decisions)
    fill(journal, schedule, decisions=decisions)
    assert len(journal["asked"]) == 1
    assert len(journal["written"]) == 2


def test_stopping_writes_nothing_and_says_so(journal, schedule):
    journal["rows"] = DRIFTED
    journal["answers"] = ["з"]
    decisions = {}
    fill(journal, schedule, decisions=decisions)
    assert journal["written"] == []
    assert decisions["stop"]


def test_a_journal_on_the_plan_is_never_asked_about(journal, schedule):
    journal["rows"] = [DRIFTED[0]]
    fill(journal, schedule)
    assert journal["asked"] == []
    assert journal["written"] == []


def test_a_lesson_type_that_did_not_take_stops_nothing(journal, schedule):
    """A cosmetic type must not cost the lessons and homework after it."""
    journal["rows"] = DRIFTED + [["", "8 вересня", "", "", "", "", "", ""]]
    journal["types_failed"] = 1
    _, _, failed = fill(journal, schedule, count=1, resync=True)
    assert len(journal["written"]) == 2  # pass two still ran
    assert journal["homework_passes"] == 1
    assert failed == 2  # still reported, once per batch
