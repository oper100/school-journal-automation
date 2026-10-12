"""The «Теми уроків та домашні завдання» block: reading it and filling it in.

A row exists for every lesson column the journal already has, so this module
depends on `add-columns` having run. Each row carries the lesson's date, its
number in the calendar plan, the topic, and what homework is due when.

Where the next lesson falls is never calculated. The site's own «Домашнє
завдання на» dropdown lists the remaining lessons as ISO dates, marking the one
being edited «(Поточний урок)», so the answer is simply the option after it —
which stays right across holidays and rescheduled lessons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Page

from . import selectors as sel

# Cell order inside a row, as the page lays them out.
CELL_DATE = 1
CELL_NUMBER = 2
CELL_TOPIC = 4
CELL_DUE = 5
CELL_HOMEWORK = 6
CELL_SUBSTITUTE = 7
CELL_COUNT = 8


class TopicsError(RuntimeError):
    """The topics table does not look the way the plan assumes."""


@dataclass(frozen=True)
class TopicRow:
    index: int
    date_text: str
    lesson_number: int | None
    topic: str
    due_text: str
    homework: str
    substitute: str
    # Where the row sits on screen. `index` counts across the whole journal,
    # but the pencil to click is found on one page by its position there.
    page_url: str = ""
    page_index: int | None = None
    # The lesson's id on the site; empty when the row had no pencil.
    schedule_id: str = ""

    @property
    def position(self) -> int:
        """The row's place on its own page."""
        return self.index if self.page_index is None else self.page_index

    @property
    def filled(self) -> bool:
        return bool(self.topic)

    def describe(self) -> str:
        if not self.filled:
            return f"{self.date_text} — порожній"
        return (
            f"{self.date_text} — № {self.lesson_number}, "
            f"{self.topic[:60]}"
        )


def parse_topic_rows(
    raw: list[list[str]],
    offset: int = 0,
    page_url: str = "",
    hrefs: list[str] | None = None,
) -> list[TopicRow]:
    """Turn the scraped cell strings of one page into records.

    `offset` is how many rows the earlier pages held, so that `index` keeps
    counting across the whole journal. `hrefs` holds each row's pencil link,
    kept apart from the cells so that a cell the site drops is still noticed:
    the schedule id inside it is what ties a row to its column.
    """
    rows: list[TopicRow] = []
    for position, cells in enumerate(raw):
        index = offset + position
        if len(cells) < CELL_COUNT:
            raise TopicsError(
                f"Рядок {index} таблиці тем має {len(cells)} комірок "
                f"замість {CELL_COUNT} — розмітка сайту змінилась."
            )
        number = cells[CELL_NUMBER].strip()
        href = hrefs[position] if hrefs and position < len(hrefs) else ""
        schedule = re.search(sel.SCHEDULE_ID_PATTERN, href or "")
        rows.append(
            TopicRow(
                index=index,
                date_text=cells[CELL_DATE].strip(),
                lesson_number=int(number) if number.isdigit() else None,
                topic=cells[CELL_TOPIC].strip(),
                due_text=cells[CELL_DUE].strip(),
                homework=cells[CELL_HOMEWORK].strip(),
                substitute=cells[CELL_SUBSTITUTE].strip(),
                page_url=page_url,
                page_index=position,
                schedule_id=schedule.group(1) if schedule else "",
            )
        )
    return rows


def next_lesson_number(rows: list[TopicRow]) -> int:
    """The number to give the next lesson: one past the highest already written.

    Neither a hole in the table nor a jump in the numbers is treated as an
    error. Both happen on purpose — a lesson that did not take place leaves an
    empty row behind, and a correction can take the count from 2 straight to
    4. `check` is what reports them; filling carries on from the last number
    the journal actually shows.
    """
    written = [
        row.lesson_number for row in rows if row.filled and row.lesson_number
    ]
    return max(written) + 1 if written else 1


def pending_rows(rows: list[TopicRow]) -> list[TopicRow]:
    """The rows still waiting for a topic, in page order."""
    return [row for row in rows if not row.filled]


def normalise_topic(text: str) -> str:
    """Compare topics by their words: the page re-wraps and adds <br>."""
    return " ".join(text.split())


def fill_targets(rows: list[TopicRow], count: int) -> list[tuple[int, int]]:
    """Which rows to fill next, as (row index, lesson number) pairs.

    Rows are taken from the first empty one *after the last filled one*, and
    the pairs are decided up front. Starting at the first empty row instead
    would write into a hole left by a lesson that never happened, putting a
    later number above an earlier one. Re-deciding after every save is what
    once let a row be written twice: the table refreshes a moment late, so a
    row just saved can still read as empty.
    """
    last_filled = max((row.index for row in rows if row.filled), default=-1)
    start = next(
        (row.index for row in rows if row.index > last_filled and not row.filled),
        None,
    )
    if start is None:
        return []
    number = next_lesson_number(rows)
    last = min(start + count, len(rows))
    return [(index, number + index - start) for index in range(start, last)]


def resync_targets(
    rows: list[TopicRow], topic_of: Callable[[int], str]
) -> list[tuple[int, int]]:
    """Rows whose number or topic does not match their position in the plan.

    Within one journal the n-th lesson row carries lesson number n, so a row
    that says otherwise was written wrong and is rewritten. A hole left in the
    middle takes its own number and everything below it shifts down — which is
    the only way to close a gap without renumbering by hand.

    Two things are deliberately left alone: rows past the last filled one,
    which are lessons that have not happened yet, and a topic the teacher
    extended by hand («Вступний інструктаж. …»), which a strict comparison
    would wipe on every run.
    """
    from .homework import topics_match

    last_filled = max((row.index for row in rows if row.filled), default=-1)
    targets: list[tuple[int, int]] = []
    for row in rows:
        if row.index > last_filled:
            break
        expected = row.index + 1
        if row.lesson_number != expected or not topics_match(
            row.topic, topic_of(expected)
        ):
            targets.append((row.index, expected))
    return targets


def homework_targets(
    rows: list[TopicRow], homework_of: Callable[[int, str], str | None]
) -> list[tuple[int, int, str]]:
    """Rows that carry a topic but no homework, and that the store can answer.

    This is the second pass: a class whose topics were written before any
    homework was collected gets its homework filled in without its topics
    being touched. Returns (row index, lesson number, homework text).
    """
    targets: list[tuple[int, int, str]] = []
    for row in rows:
        if not row.filled or row.homework or row.lesson_number is None:
            continue
        text = homework_of(row.lesson_number, row.topic)
        if text:
            targets.append((row.index, row.lesson_number, text))
    return targets


def confirm_row(
    page: Page,
    row: TopicRow,
    number: int,
    attempts: int = 3,
    expect_homework: bool = False,
) -> TopicRow:
    """Wait until a saved row really shows what was written to it.

    The journal table updates a moment after the dialog closes. Without this
    the next row is chosen from a stale reading. Only the row's own page is
    read: going through every page after each save would cost a navigation
    per page per lesson.
    """
    for attempt in range(attempts):
        for _ in range(10):
            _show_row_page(page, row)
            shown = _read_page_rows(page, row.index - row.position, row.page_url)
            if row.position < len(shown):
                now = shown[row.position]
                if (
                    now.filled
                    and now.lesson_number == number
                    and (now.homework or not expect_homework)
                ):
                    return now
            page.wait_for_timeout(1_000)
        if attempt < attempts - 1:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1_500)

    what = "домашнє завдання" if expect_homework else f"урок № {number}"
    raise TopicsError(
        f"Рядок {row.index} ({row.date_text}) не показав {what} після "
        "збереження. Зупиняюсь, щоб не записати той самий рядок двічі."
    )


def due_option_after_current(options: list[dict]) -> dict | None:
    """The lesson that homework should be set for: the one after this lesson.

    Returns None when the current lesson is the last in the list — the final
    lesson of the term has nothing to set homework for.
    """
    current = next(
        (
            index
            for index, option in enumerate(options)
            if sel.CURRENT_LESSON_MARKER in option["label"]
        ),
        None,
    )
    if current is None:
        raise TopicsError(
            "У списку «Домашнє завдання на» немає пункту "
            f"«{sel.CURRENT_LESSON_MARKER}» — розмітка сайту змінилась."
        )
    later = options[current + 1 :]
    return later[0] if later else None


def _read_page_rows(page: Page, offset: int, page_url: str) -> list[TopicRow]:
    """Scrape the topics table of the page on screen."""
    page.wait_for_selector(sel.TOPICS_TABLE)
    raw = page.eval_on_selector_all(
        sel.TOPIC_ROW,
        f"""els => els.map(el => {{
            const cells = [...el.querySelectorAll('{sel.TOPIC_CELL}')]
                .map(d => d.innerText.trim());
            const pencil = el.querySelector('{sel.TOPIC_EDIT_LINK}');
            return {{cells, href: pencil ? pencil.getAttribute('href') : ''}};
        }})""",
    )
    return parse_topic_rows(
        [item["cells"] for item in raw],
        offset,
        page_url,
        hrefs=[item["href"] for item in raw],
    )


def read_topic_rows(page: Page) -> list[TopicRow]:
    """Scrape the topics table of the open journal, every page of it.

    The site opens a journal on its last page; reading only that one is what
    once restarted the numbering at 1 on 9-А's second page.
    """
    from .journal import each_journal_page

    rows: list[TopicRow] = []
    for url in each_journal_page(page):
        rows += _read_page_rows(page, len(rows), url)
    return rows


def _show_row_page(page: Page, row: TopicRow) -> None:
    from .journal import show_journal_page

    if row.page_url:
        show_journal_page(page, row.page_url)


def open_topic_dialog(page: Page, row: TopicRow) -> None:
    """Click the pencil on one row and wait for its dialog.

    The link is followed by clicking rather than by navigating: nz.ua answers a
    direct request for the dialog's URL with 403, it only serves it to the
    page's own modal machinery.
    """
    _show_row_page(page, row)
    link = page.query_selector_all(f"{sel.TOPIC_ROW} {sel.TOPIC_EDIT_LINK}")
    if row.position >= len(link):
        raise TopicsError(
            f"У рядку {row.index} ({row.date_text}) немає олівця редагування."
        )
    link[row.position].click()
    page.wait_for_selector(sel.DIALOG_FORM, state="visible")
    title = page.inner_text(sel.DIALOG_TITLE).strip()
    if title != sel.HOMEWORK_DIALOG_TITLE_TEXT:
        raise TopicsError(
            f"Відкрився діалог «{title}», а очікувався "
            f"«{sel.HOMEWORK_DIALOG_TITLE_TEXT}»."
        )


def _due_options(page: Page) -> list[dict]:
    return page.eval_on_selector_all(
        f"{sel.HOMEWORK_DUE_SELECT} option",
        "els => els.map(e => ({value: e.value, label: e.text.trim()}))",
    )


def fill_topic_dialog(
    page: Page, topic: str, number: int, homework: str = ""
) -> str:
    """Fill the open dialog. With no homework to offer, the field is left alone.

    Returns the due date chosen, or an empty string when there is no next
    lesson to set homework for.
    """
    page.fill(sel.TOPIC_TEXTAREA, topic)
    page.fill(sel.LESSON_NUMBER_INPUT, str(number))
    if homework:
        page.fill(sel.HOMEWORK_TEXTAREA, homework)

    due = due_option_after_current(_due_options(page))
    if due is None:
        return ""
    page.select_option(sel.HOMEWORK_DUE_SELECT, value=due["value"])
    return due["label"]


def fill_homework_dialog(page: Page, homework: str) -> str:
    """Write only the homework, leaving the topic and the lesson number as they are.

    «Домашнє завдання на» is only chosen when nothing is chosen yet: a row
    saved earlier already points at the lesson the teacher picked, and
    re-deciding it here would move homework the site has already shown.
    """
    page.fill(sel.HOMEWORK_TEXTAREA, homework)

    options = _due_options(page)
    already = page.eval_on_selector(sel.HOMEWORK_DUE_SELECT, "el => el.value")
    if already:
        return next(
            (option["label"] for option in options if option["value"] == already),
            already,
        )

    due = due_option_after_current(options)
    if due is None:
        return ""
    page.select_option(sel.HOMEWORK_DUE_SELECT, value=due["value"])
    return due["label"]


def save_topic_dialog(page: Page) -> None:
    """Submit the dialog and wait for it to close."""
    page.click(sel.SAVE_BUTTON)
    page.wait_for_selector(sel.DIALOG, state="hidden", timeout=30_000)
    page.wait_for_load_state("networkidle")


# --- checking a journal over, without touching it ---------------------------

# What one row can be wrong about. The order is the order they are reported.
ISSUE_LABELS = {
    "hole": "порожній рядок, а далі є заповнені",
    "no-number": "тема є, а номера уроку немає",
    "backwards": "номер уроку менший за попередній",
    "duplicate": "номер уроку повторюється",
    "jump": "пропуск у нумерації",
    "no-plan": "такого номера немає в плануванні",
    "topic": "тема не збігається з плануванням",
    "homework-pending": "ДЗ порожнє, але у сховищі воно є",
    "homework-missing": "ДЗ порожнє, і у сховищі його немає",
}


@dataclass(frozen=True)
class Issue:
    """One thing worth a human's eye in one row of the topics table."""

    index: int
    date_text: str
    kind: str
    detail: str
    number: int | None = None

    @property
    def label(self) -> str:
        return ISSUE_LABELS.get(self.kind, self.kind)

    @property
    def number_text(self) -> str:
        return str(self.number) if self.number else "—"


def check_rows(
    rows: list[TopicRow],
    plan_topic_of: Callable[[int], str | None],
    homework_of: Callable[[int, str], str | None],
) -> list[Issue]:
    """Everything that does not add up in one journal, in page order.

    Nothing here is fatal: a hole is a lesson that did not happen, a jump is a
    correction the teacher made on purpose. The point is to put them in front
    of her in one list instead of letting them surface one failed run at a
    time.
    """
    from .homework import topics_match

    issues: list[Issue] = []
    last_filled = max((row.index for row in rows if row.filled), default=-1)
    seen: dict[int, TopicRow] = {}
    previous: int | None = None

    for row in rows:
        def note(kind: str, detail: str = "") -> None:
            issues.append(
                Issue(row.index, row.date_text, kind, detail, row.lesson_number)
            )

        if not row.filled:
            # Rows past the last filled one are simply lessons still to come.
            if row.index < last_filled:
                note("hole")
            continue

        number = row.lesson_number
        if number is None:
            note("no-number", row.topic[:60])
            continue

        earlier = seen.get(number)
        if earlier is not None:
            note("duplicate", f"той самий № {number} стоїть і в {earlier.date_text}")
        elif previous is not None and number < previous:
            note("backwards", f"після № {previous}")
        elif previous is not None and number > previous + 1:
            missing = ", ".join(str(n) for n in range(previous + 1, number))
            note("jump", f"після № {previous} немає № {missing}")
        seen[number] = row
        previous = number if previous is None else max(previous, number)

        planned = plan_topic_of(number)
        if planned is None:
            note("no-plan", f"у плануванні {number} уроку немає")
        elif not topics_match(row.topic, planned):
            note("topic", f"у плануванні: {planned[:60]}")

        if not row.homework:
            has = homework_of(number, row.topic)
            note("homework-pending" if has else "homework-missing", (has or "")[:50])

    return issues
