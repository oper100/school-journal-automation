"""Tests for the command line layer that do not touch a browser."""

import pytest

from nzua.cli import SCHEDULE_PATH, main
from nzua import selectors
from nzua.selectors import require_ready


def test_dry_run_lists_every_column(capsys):
    assert main(["add-columns", "--month", "2026-09", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Стовпчиків до створення: 26" in out
    assert "нічого не створено" in out


def test_dry_run_can_be_narrowed_to_one_journal(capsys):
    assert (
        main(
            [
                "add-columns",
                "--month",
                "2026-09",
                "--subject",
                "Фізика",
                "--class",
                "9-А",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Стовпчиків до створення: 3" in out
    assert "Астрономія" not in out


def test_bad_month_is_reported_not_crashed(capsys):
    assert main(["add-columns", "--month", "вересень", "--dry-run"]) == 2
    assert "Помилка" in capsys.readouterr().err


def test_unknown_class_is_reported_not_crashed(capsys):
    assert main(["add-columns", "--month", "2026-09", "--class", "7-А"]) == 2
    assert "Невідомий клас" in capsys.readouterr().err


def test_selectors_are_filled_in():
    require_ready()  # raises once recon has not been done


def test_the_guard_still_bites_if_selectors_are_blanked(monkeypatch):
    monkeypatch.setattr(selectors, "SELECTORS_READY", False)
    with pytest.raises(RuntimeError, match="recon"):
        require_ready()


def test_fill_topics_covers_every_journal_when_unfiltered(capsys):
    assert main(["fill-topics", "--dry-run", "--count", "1"]) == 0
    out = capsys.readouterr().out
    assert "Журналів: 11" in out
    assert "Астрономія" in out and "Фізика" in out


def test_fill_topics_can_still_be_narrowed(capsys):
    assert main(["fill-topics", "--subject", "Астрономія", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Журналів: 3" in out
    assert "Фізика" not in out


def test_run_month_lists_columns_and_journals(capsys):
    assert main(["run-month", "--month", "2026-09", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Стовпчиків до створення: 26" in out
    assert "теми уроків у всіх 11 журналах" in out


def test_journals_of_lists_each_journal_once():
    from nzua.runner import journals_of
    from nzua.schedule import load_schedule

    schedule = load_schedule(SCHEDULE_PATH)
    journals = journals_of(schedule)
    assert len(journals) == 11
    assert len(set(journals)) == 11
    assert ("Астрономія", "11-В") in journals


def test_dump_homework_rejects_a_class_the_schedule_never_heard_of(capsys):
    assert main(["dump-homework", "--from", "7-А"]) == 2
    assert "Невідомий клас" in capsys.readouterr().err


def test_dump_homework_rejects_an_unknown_subject(capsys):
    assert main(["dump-homework", "--from", "9-А", "--subject", "Хімія"]) == 2
    assert "Невідомий предмет" in capsys.readouterr().err


def test_help_names_every_command(capsys):
    """The one place a person looks first has to list all of them."""
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for name in (
        "recon",
        "add-columns",
        "import-planning",
        "fill-topics",
        "dump-homework",
        "check",
        "run-month",
    ):
        assert name in out


def test_help_says_in_what_order_to_run_them(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "Порядок за місяць" in out
    assert "Файли" in out


def test_every_command_explains_itself(capsys):
    for name in (
        "recon",
        "add-columns",
        "import-planning",
        "fill-topics",
        "dump-homework",
        "check",
        "run-month",
    ):
        with pytest.raises(SystemExit):
            main([name, "--help"])
        out = capsys.readouterr().out
        body = out.split("options:")[0]
        assert len(body.splitlines()) > 4, f"{name} має лише рядок використання"
