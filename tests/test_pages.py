"""A journal spread over several pages must be read as one.

nz.ua puts twenty lesson columns on a page and, opened without `page=`, shows
the *last* page. Reading only what was on screen once numbered 9-А's second
page from 1, over the top of lessons 13–16, while page one still held 1–12.
"""

from datetime import date

from nzua import selectors as sel
from nzua.journal import existing_column_dates, journal_page_urls, show_journal_page
from nzua.topics import fill_targets, read_topic_rows, resync_targets

JOURNAL = "https://nz.ua/journal/index?journal=7"
PAGE_1 = JOURNAL + "&page=1"
PAGE_2 = JOURNAL + "&page=2"

# What `ul.pagination` yields on the second page: «, 1, 2 (» is a bare span).
LINKS = [
    ["0", "/journal/index?journal=7&page=1"],
    ["0", "/journal/index?journal=7&page=1"],
    ["1", "/journal/index?journal=7&page=2"],
]


def row(date_text, number="", topic=""):
    return ["", date_text, str(number), "", topic, "", "", ""]


class PagedJournal:
    """A journal of two pages, opened the way the site opens it: on the last."""

    def __init__(self, pages, links=LINKS):
        self.pages = pages
        self.links = links
        self.url = JOURNAL
        self.visited: list[str] = []

    def _current(self):
        return self.pages[PAGE_2 if self.url == JOURNAL else self.url]

    def goto(self, url, **_):
        self.visited.append(url)
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, _selector, **_):
        pass

    def eval_on_selector_all(self, selector, _script):
        if selector == sel.JOURNAL_PAGE_LINK:
            return self.links
        if selector == sel.TOPIC_ROW:
            return [{"cells": cells, "href": ""} for cells in self._current()["rows"]]
        if selector == sel.COLUMN_HEADER_CELLS:
            return self._current()["headers"]
        raise AssertionError(selector)


def nine_a():
    first = [row(f"{d} вересня", n, f"Тема {n}") for n, d in enumerate(range(3, 15), 1)]
    first += [row(f"{d} жовтня") for d in range(1, 9)]
    return PagedJournal(
        {
            PAGE_1: {
                "rows": first,
                "headers": [["3", "Вер."]] + [[str(d), None] for d in range(4, 15)]
                + [["1", "Жовт."]] + [[str(d), None] for d in range(2, 9)],
            },
            PAGE_2: {
                "rows": [row(f"{d} жовтня") for d in (19, 22, 23)],
                "headers": [["19", "Жовт."], ["22", None], ["23", None]],
            },
        }
    )


def test_page_urls_come_in_page_order_without_repeats():
    assert journal_page_urls(nine_a()) == [PAGE_1, PAGE_2]


def test_a_journal_without_pagination_is_its_own_only_page():
    journal = nine_a()
    journal.links = []
    assert journal_page_urls(journal) == [JOURNAL]


def test_rows_of_every_page_are_read_in_order():
    rows = read_topic_rows(nine_a())
    assert len(rows) == 23
    assert [r.index for r in rows] == list(range(23))
    assert rows[20].date_text == "19 жовтня"
    assert (rows[20].page_url, rows[20].page_index) == (PAGE_2, 0)
    assert (rows[3].page_url, rows[3].page_index) == (PAGE_1, 3)


def test_numbering_carries_on_from_the_first_page():
    """The bug: page two alone looked empty, so the count restarted at 1."""
    rows = read_topic_rows(nine_a())
    assert fill_targets(rows, 2) == [(12, 13), (13, 14)]


def test_a_second_page_numbered_from_one_is_seen_as_drift():
    journal = nine_a()
    journal.pages[PAGE_2]["rows"] = [
        row("19 жовтня", 1, "Тема 1"),
        row("22 жовтня", 2, "Тема 2"),
        row("23 жовтня"),
    ]
    rows = read_topic_rows(journal)
    drift = resync_targets(rows, lambda n: f"Тема {n}")
    assert drift == [(i, i + 1) for i in range(12, 22)]


def test_existing_columns_include_the_earlier_pages():
    dates = existing_column_dates(nine_a(), date(2026, 9, 1))
    assert dates[0] == date(2026, 9, 3)
    assert date(2026, 10, 1) in dates
    assert dates[-1] == date(2026, 10, 23)
    assert len(dates) == 23


def test_the_last_page_is_not_reloaded_when_opened_without_page():
    """Opened bare, the journal already shows its last page."""
    journal = nine_a()
    show_journal_page(journal, PAGE_2)
    assert journal.visited == []


def test_another_page_is_still_navigated_to():
    journal = nine_a()
    show_journal_page(journal, PAGE_1)
    assert journal.visited == [PAGE_1]
    show_journal_page(journal, PAGE_2)
    assert journal.visited == [PAGE_1, PAGE_2]
