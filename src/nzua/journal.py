"""Finding journals on nz.ua and reading which lesson columns already exist.

Journal ids change every semester, so they are never hard-coded: the list at
/journal/list is read at the start of each run and turned into a
subject + class -> URL map.

Column headers carry only a day number; the month appears once, on the first
column of each month ("1 Вер."). `column_dates` rebuilds full dates from that
sequence, which is why it is a pure function taking already-scraped text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Iterator
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page

from . import selectors as sel
from .browser import BASE_URL

# The site abbreviates months ("Вер.", "Жовт."), so match on stems.
MONTH_STEMS = {
    "січ": 1, "лют": 2, "бер": 3, "квіт": 4, "кві": 4, "трав": 5, "тра": 5,
    "черв": 6, "чер": 6, "лип": 7, "серп": 8, "сер": 8, "вер": 9,
    "жовт": 10, "жов": 10, "лист": 11, "лис": 11, "груд": 12, "гру": 12,
}


# Navigating journal after journal at full speed is what trips Cloudflare's
# check, so each move pauses briefly. A run of 11 journals loses a few seconds;
# an interstitial costs minutes.
NAVIGATION_PAUSE_MS = 1_500


class JournalError(RuntimeError):
    """The journal page does not look the way the code assumes."""


class JournalNotFound(LookupError):
    """The requested subject + class pair is not among the teacher's journals."""


@dataclass(frozen=True)
class JournalLink:
    subject: str
    class_name: str
    url: str
    raw_label: str


def normalise_class(label: str) -> str:
    """Turn a link label into a bare class name.

    Labels arrive padded and sometimes carry a subgroup suffix:
    " 9-Б(1)" and "11-Б(I група)" both name a class we know as 9-Б and 11-Б.
    """
    return re.sub(r"\(.*?\)", "", label).strip()


def parse_month_marker(text: str) -> int | None:
    """Map a month abbreviation such as 'Жовт.' onto a month number."""
    stem = text.strip().rstrip(".").lower()
    for length in range(len(stem), 2, -1):
        if stem[:length] in MONTH_STEMS:
            return MONTH_STEMS[stem[:length]]
    return None


def column_dates(
    cells: Iterable[tuple[str, str | None]], start: date
) -> list[date]:
    """Rebuild each column's date from its day number and month markers.

    `cells` is one (day text, month marker or None) pair per column, in page
    order. `start` anchors the first column: the semester's opening date, which
    supplies the year and the month of any columns before the first marker.

    Months only ever move forward inside a semester, so a marker naming a month
    earlier than the current one means the year has rolled over — which is how
    an autumn semester running into January is handled.
    """
    dates: list[date] = []
    year, month = start.year, start.month

    for day_text, marker in cells:
        if marker:
            marked = parse_month_marker(marker)
            if marked is not None:
                if marked < month:
                    year += 1
                month = marked
        digits = re.search(r"\d+", day_text)
        if not digits:
            continue
        dates.append(date(year, month, int(digits.group())))

    return dates


def parse_semester_label(label: str) -> tuple[date, date]:
    """Read the date range out of a semester option.

    Labels look like "2026-2027 [1], 01.09.2026 - 31.12.2026 (поточний)".
    """
    found = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", label)
    if len(found) < 2:
        raise ValueError(f"Не бачу дат у назві семестру: {label!r}")
    start, end = found[0], found[1]
    to_date = lambda d: date(int(d[2]), int(d[1]), int(d[0]))  # noqa: E731
    return to_date(start), to_date(end)


def current_semester(page: Page) -> tuple[date, date]:
    """The date range of the semester the journal is currently showing."""
    label = page.eval_on_selector(
        sel.SEMESTER_SELECT,
        "el => el.options[el.selectedIndex].text",
    )
    return parse_semester_label(label)


# --- switching semesters ----------------------------------------------------


@dataclass(frozen=True)
class SemesterOption:
    """One entry of the header's semester dropdown."""

    value: str
    label: str
    academic_year: str
    number: int
    start: date
    end: date
    live: bool
    chosen: bool

    def describe(self) -> str:
        mark = " (поточний)" if self.live else ""
        here = " <- вибраний" if self.chosen else ""
        return (
            f"{self.academic_year} [{self.number}] "
            f"{self.start:%d.%m.%Y} - {self.end:%d.%m.%Y}{mark}{here}"
        )


_SEMESTER_HEAD = re.compile(r"(\d{4}-\d{4})\s*\[(\d)\]")


def parse_semester_option(
    label: str, value: str = "", chosen: bool = False
) -> SemesterOption:
    """Read one dropdown entry: academic year, half, dates, and whether it is live."""
    head = _SEMESTER_HEAD.search(label)
    if not head:
        raise ValueError(f"Не бачу навчального року в назві семестру: {label!r}")
    start, end = parse_semester_label(label)
    return SemesterOption(
        value=value,
        label=" ".join(label.split()),
        academic_year=head.group(1),
        number=int(head.group(2)),
        start=start,
        end=end,
        live=sel.SEMESTER_CURRENT_MARKER in label,
        chosen=chosen,
    )


def semester_options(page: Page) -> list[SemesterOption]:
    """Every semester the account can switch to, newest first as the site lists them."""
    page.wait_for_selector(sel.SEMESTER_SELECT)
    raw = page.eval_on_selector_all(
        f"{sel.SEMESTER_SELECT} option",
        """els => els.map(el => ({
            value: el.value,
            label: el.text,
            chosen: el.hasAttribute('selected'),
        }))""",
    )
    return [
        parse_semester_option(item["label"], item["value"], item["chosen"])
        for item in raw
    ]


def chosen_semester(options: list[SemesterOption]) -> SemesterOption:
    """The semester the server currently serves this session."""
    for option in options:
        if option.chosen:
            return option
    raise JournalError(
        "У списку семестрів жоден не позначений як вибраний — "
        "розмітка сайту змінилась."
    )


def previous_academic_year(options: list[SemesterOption]) -> str:
    """The academic year before the live one: 2026-2027 is running, so 2025-2026."""
    live = next((option for option in options if option.live), None)
    if live is None:
        raise JournalError(
            f"У списку семестрів немає «{sel.SEMESTER_CURRENT_MARKER}» — "
            "не можу сказати, який рік минулий."
        )
    earlier = sorted(
        {option.academic_year for option in options if option.academic_year < live.academic_year}
    )
    if not earlier:
        raise JournalError(
            f"У списку семестрів немає нічого раніше за {live.academic_year}."
        )
    return earlier[-1]


def semesters_of_year(
    options: list[SemesterOption], academic_year: str
) -> list[SemesterOption]:
    """Both halves of one academic year, in order."""
    return sorted(
        (option for option in options if option.academic_year == academic_year),
        key=lambda option: option.number,
    )


def _server_semester(page: Page) -> str:
    """Which semester the server thinks is chosen.

    Read from the `selected` attribute rather than the select's value: the
    value also changes when we pick an option client-side and the form is
    never posted, which would make a failed switch look like a success.
    """
    return page.eval_on_selector(
        sel.SEMESTER_SELECT,
        f"""el => {{
            const marked = el.querySelector('{sel.SEMESTER_SELECTED_OPTION}');
            return marked ? marked.value : '';
        }}""",
    )


def select_semester(page: Page, value: str) -> None:
    """Switch the session to one semester and make sure the switch took.

    This changes the semester for the whole account, not for the open tab, so
    every caller is responsible for switching back. Picking an option is
    expected to post the form by itself; when it does not, the form is posted
    directly.
    """
    if _server_semester(page) == value:
        return

    for post_by_hand in (False, True):
        try:
            if post_by_hand:
                page.eval_on_selector(sel.SEMESTER_FORM, "form => form.submit()")
            else:
                page.select_option(sel.SEMESTER_SELECT, value=value)
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass  # a navigation mid-call is the success case, not a failure
        page.wait_for_timeout(NAVIGATION_PAUSE_MS)
        try:
            if _server_semester(page) == value:
                return
        except Exception:
            pass

    raise JournalError(
        f"Не вдалося перемкнути семестр на {value}: сайт лишився "
        f"на {_server_semester(page)!r}."
    )


def require_current_semester(page: Page) -> None:
    """Refuse to write into a journal of a semester that is over.

    `dump-homework` walks past semesters, and the choice lives in the session:
    a run that died half-way leaves it there, and the next `add-columns` would
    quietly create its columns in the wrong year.
    """
    option = chosen_semester(semester_options(page))
    if not option.live:
        raise JournalError(
            f"Зараз вибрано семестр {option.describe()}, а не поточний. "
            "Перемкни його у шапці сайту — інакше записи підуть не в той рік."
        )


def goto_settled(page: Page, url: str, wait_selector: str, attempts: int = 3) -> None:
    """Navigate and let the page settle before anyone navigates away again.

    Playwright aborts a `goto` if another navigation starts while it is in
    flight, and nz.ua's own pages sometimes navigate a moment after load. The
    pause afterwards is also what keeps a run of eleven journals from tripping
    Cloudflare's check.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(NAVIGATION_PAUSE_MS)
            page.wait_for_selector(wait_selector)
            return
        except Exception as exc:
            last = exc
            if attempt < attempts - 1:
                page.wait_for_timeout(2_000)
    raise last  # type: ignore[misc]


def load_journal_links(page: Page) -> list[JournalLink]:
    """Read /journal/list into one record per subject + class journal.

    The page is only navigated to when we are not already on it: the login
    check has usually just been there, and going twice in a row is what once
    interrupted the navigation that followed.
    """
    list_url = BASE_URL + sel.JOURNAL_LIST_PATH
    if not page.url.startswith(list_url):
        goto_settled(page, list_url, sel.JOURNAL_LIST_ROW)
    else:
        page.wait_for_selector(sel.JOURNAL_LIST_ROW)

    links: list[JournalLink] = []
    for row in page.query_selector_all(sel.JOURNAL_LIST_ROW):
        subject_cell = row.query_selector(sel.JOURNAL_LIST_SUBJECT_CELL)
        if subject_cell is None:
            continue
        subject = subject_cell.inner_text().strip()
        for link in row.query_selector_all(sel.JOURNAL_LIST_CLASS_LINK):
            label = link.inner_text()
            href = link.get_attribute("href") or ""
            links.append(
                JournalLink(
                    subject=subject,
                    class_name=normalise_class(label),
                    url=href if href.startswith("http") else BASE_URL + href,
                    raw_label=label.strip(),
                )
            )
    return links


def find_journal(
    links: list[JournalLink], subject: str, class_name: str
) -> JournalLink:
    """Pick one journal, refusing to guess when the pair is missing or doubled."""
    matches = [
        link
        for link in links
        if link.subject == subject and link.class_name == class_name
    ]
    if not matches:
        available = ", ".join(
            sorted({f"{link.subject} {link.class_name}" for link in links})
        )
        raise JournalNotFound(
            f"Немає журналу «{subject} {class_name}». Доступні: {available}"
        )
    if len(matches) > 1:
        labels = ", ".join(link.raw_label for link in matches)
        raise JournalNotFound(
            f"Журнал «{subject} {class_name}» неоднозначний — знайдено кілька: "
            f"{labels}. Уточни підгрупу вручну."
        )
    return matches[0]


def open_journal(page: Page, link: JournalLink) -> None:
    """Navigate to a journal and wait for its marks table."""
    goto_settled(page, link.url, sel.ADD_COLUMN_BUTTON)


def journal_page_urls(page: Page) -> list[str]:
    """Every page of the open journal, first to last.

    The site opens a journal on its *last* page, so whatever reads only the
    page on screen misses every earlier lesson — which once numbered 9-А's
    second page from 1 while the first still held lessons 1–12.
    """
    raw = page.eval_on_selector_all(
        sel.JOURNAL_PAGE_LINK,
        "els => els.map(a => [a.dataset.page, a.getAttribute('href')])",
    )
    by_number = {
        int(number): href
        for number, href in raw
        if number is not None and str(number).isdigit() and href
    }
    if not by_number:
        return [page.url]
    return [
        href if href.startswith("http") else BASE_URL + href
        for _, href in sorted(by_number.items())
    ]


def _on_screen(page: Page, url: str) -> bool:
    """Whether `url` names the journal page already shown.

    A journal opened without `page=` shows its last page, while the
    pagination link to that same page carries `page=N`; comparing the two
    addresses as text reloaded the page on screen on every read.
    """
    if page.url == url:
        return True
    if "page" in parse_qs(urlparse(page.url).query):
        return False
    urls = journal_page_urls(page)
    return len(urls) > 1 and urls[-1] == url


def show_journal_page(page: Page, url: str) -> None:
    """Make one page of the journal the one on screen, unless it already is."""
    if not _on_screen(page, url):
        goto_settled(page, url, sel.ADD_COLUMN_BUTTON)


def each_journal_page(page: Page) -> Iterator[str]:
    """Visit the open journal's pages in order, yielding each page's URL."""
    for url in journal_page_urls(page):
        show_journal_page(page, url)
        yield url


def existing_column_dates(page: Page, semester_start: date) -> list[date]:
    """Dates of the lesson columns already present in the open journal.

    A date can repeat: a class with two lessons on the same weekday needs two
    columns on that day, so the caller counts rather than deduplicates.
    Every page is read: columns on an earlier page exist just the same, and
    missing them would add them a second time.
    """
    cells: list = []
    for _ in each_journal_page(page):
        cells += page.eval_on_selector_all(
            sel.COLUMN_HEADER_CELLS,
            """els => els.map(el => {
                const marker = el.querySelector('span.pt-month');
                const markerText = marker ? marker.innerText : null;
                const day = el.innerText.replace(markerText || '', '');
                return [day, markerText];
            })""",
        )
    return column_dates([(day, marker) for day, marker in cells], semester_start)
