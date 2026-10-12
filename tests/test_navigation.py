"""Tests for navigation, using a stub page instead of a browser.

The failure these guard against cost a journal: two navigations to the same
page in a row, and the one that followed was aborted mid-flight.
"""

import pytest

from nzua.journal import goto_settled, load_journal_links


class StubPage:
    """The little of Playwright's Page that navigation touches."""

    def __init__(self, url="about:blank", fail_times=0):
        self.url = url
        self.visited: list[str] = []
        self.waited_for: list[str] = []
        self.fail_times = fail_times

    def goto(self, url, **_):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError(
                f'Page.goto: Navigation to "{url}" is interrupted by another'
            )
        self.visited.append(url)
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, selector, **_):
        self.waited_for.append(selector)

    def query_selector_all(self, _selector):
        return []


LIST_URL = "https://nz.ua/journal/list"


def test_goto_settled_waits_for_the_selector():
    page = StubPage()
    goto_settled(page, LIST_URL, "table.journal-choose")
    assert page.visited == [LIST_URL]
    assert page.waited_for == ["table.journal-choose"]


def test_goto_settled_retries_an_interrupted_navigation():
    page = StubPage(fail_times=2)
    goto_settled(page, LIST_URL, "table.journal-choose")
    assert page.visited == [LIST_URL]


def test_goto_settled_gives_up_and_reports_the_real_error():
    page = StubPage(fail_times=99)
    with pytest.raises(RuntimeError, match="interrupted"):
        goto_settled(page, LIST_URL, "table.journal-choose", attempts=2)


def test_journal_list_is_not_navigated_to_when_already_open():
    """The login check has just been there; going again aborted what followed."""
    page = StubPage(url=LIST_URL)
    load_journal_links(page)
    assert page.visited == []


def test_journal_list_is_navigated_to_when_elsewhere():
    page = StubPage(url="https://nz.ua/journal/index?journal=1")
    load_journal_links(page)
    assert page.visited == [LIST_URL]
