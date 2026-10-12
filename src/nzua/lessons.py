"""Existing lesson columns: deleting them, and setting their type from the topic.

Both go through the same «Редагувати урок» dialog, opened by clicking a
column's date in the marks table. A row of the topics table and its column are
tied together by the lesson's schedule id, which both links carry.

Deleting is the one thing in this tool that cannot be undone, so every
deletion re-reads the lesson's date in the dialog itself and refuses to go on
when it is not the date that was planned — a page that re-paginated between
reading and deleting must not cost a different lesson.
"""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import date, timedelta

from playwright.sync_api import Page

from . import selectors as sel
from .topics import TopicRow


class LessonError(RuntimeError):
    """A column could not be found, opened, changed or deleted as planned."""


# --- deciding, without a browser ---------------------------------------------


def parse_row_date(text: str, semester_start: date) -> date | None:
    """Turn a topics-table date such as "19 жовтня" into a full date.

    The table shows no year. A semester never spans more than one new year, so
    a month earlier than the semester's first is in the following year — the
    same rule the column headers use. Anything before the day, such as a
    weekday, is skipped; a date that cannot exist gives None, like no date.
    """
    from .journal import parse_month_marker

    found = re.search(r"(\d{1,2})\s+(\S+)", text)
    if not found:
        return None
    month = parse_month_marker(found.group(2))
    if month is None:
        return None
    year = semester_start.year + (1 if month < semester_start.month else 0)
    try:
        return date(year, month, int(found.group(1)))
    except ValueError:
        return None


def last_week(year: int, month: int) -> tuple[date, date]:
    """The month's last week: from the Monday of the week holding its last
    day, to that last day.

    October 2026 ends on a Saturday, so its last week is the 26th to the 31st
    — the autumn holidays, which is what this is for.
    """
    following = date(year + month // 12, month % 12 + 1, 1)
    end = following - timedelta(days=1)
    return end - timedelta(days=end.weekday()), end


def rows_between(
    rows: list[TopicRow], start: date, end: date, semester_start: date
) -> list[tuple[TopicRow, date]]:
    """The rows whose lesson falls between `start` and `end`, both included."""
    picked = []
    for row in rows:
        when = parse_row_date(row.date_text, semester_start)
        if when is not None and start <= when <= end:
            picked.append((row, when))
    return picked


# Phrase in the topic -> the option label of «Тип уроку». Matched as words in
# the nominative, so «Аналіз контрольної роботи» stays an ordinary lesson.
TYPE_BY_PHRASE = {
    re.compile(r"\bлабораторна\s+робота\b", re.IGNORECASE): sel.LESSON_TYPE_LAB,
    re.compile(r"\bконтрольна\s+робота\b", re.IGNORECASE): sel.LESSON_TYPE_TEST,
}


def lesson_type_for(topic: str) -> str | None:
    """The lesson type a topic announces, or None for an ordinary lesson.

    When a topic names both, the one named first wins.
    """
    found = [
        (match.start(), label)
        for pattern, label in TYPE_BY_PHRASE.items()
        if (match := pattern.search(topic))
    ]
    return min(found)[1] if found else None


def type_targets(rows: list[TopicRow]) -> list[tuple[TopicRow, str]]:
    """Filled rows whose topic asks for a type other than the ordinary one."""
    out = []
    for row in rows:
        if not row.filled or not row.schedule_id:
            continue
        wanted = lesson_type_for(row.topic)
        if wanted:
            out.append((row, wanted))
    return out


# --- on the page --------------------------------------------------------------


def marks_by_schedule(page: Page) -> dict[str, int]:
    """How many marks each column on screen holds, by schedule id.

    Body cells carry no id of their own, but they come in the same order as
    the header cells, which do.
    """
    raw = page.eval_on_selector_all(
        sel.COLUMN_HEADER_CELLS,
        f"""heads => {{
            const ids = heads.map(td => {{
                const a = td.querySelector('a[href*="schedule="]');
                const m = a && a.getAttribute('href').match(/{sel.SCHEDULE_ID_PATTERN}/);
                return m ? m[1] : null;
            }});
            const counts = ids.map(() => 0);
            document.querySelectorAll('{sel.MARK_ROW}').forEach(tr => {{
                [...tr.querySelectorAll('{sel.MARK_CELL}')].forEach((td, i) => {{
                    const input = td.querySelector('{sel.MARK_INPUT}');
                    if (i < counts.length && input
                        && (input.value.trim() || input.dataset.markId)) {{
                        counts[i]++;
                    }}
                }});
            }});
            return ids.map((id, i) => [id, counts[i]]);
        }}""",
    )
    return {schedule_id: count for schedule_id, count in raw if schedule_id}


def _find_column(page: Page, row: TopicRow) -> None:
    """Bring the page holding the row's column on screen.

    The row's own page is tried first. A deletion re-paginates the journal, so
    a column can move to the page before; then every page is looked through.
    """
    from .journal import each_journal_page, show_journal_page

    link = sel.COLUMN_EDIT_LINK.format(id=row.schedule_id)
    if row.page_url:
        show_journal_page(page, row.page_url)
        if page.query_selector(link):
            return
    for _ in each_journal_page(page):
        if page.query_selector(link):
            return
    raise LessonError(
        f"Стовпчика {row.date_text} (id {row.schedule_id}) у журналі немає."
    )


def open_lesson_dialog(page: Page, row: TopicRow) -> None:
    """Click the column's date and wait for «Редагувати урок»."""
    if not row.schedule_id:
        raise LessonError(f"У рядку {row.date_text} немає id уроку.")
    _find_column(page, row)
    page.click(sel.COLUMN_EDIT_LINK.format(id=row.schedule_id))
    page.wait_for_selector(sel.DIALOG_FORM, state="visible")
    title = page.inner_text(sel.DIALOG_TITLE).strip()
    if title != sel.EDIT_LESSON_DIALOG_TITLE_TEXT:
        _close(page)
        raise LessonError(
            f"Відкрився діалог «{title}», а очікувався "
            f"«{sel.EDIT_LESSON_DIALOG_TITLE_TEXT}»."
        )


def _close(page: Page) -> None:
    if page.is_visible(sel.DIALOG):
        page.click(sel.DIALOG_CLOSE)
        page.wait_for_selector(sel.DIALOG, state="hidden")


def _close_after_failure(page: Page) -> None:
    """Close a dialog left open by a failed step, so the next step can click.

    A failure to close is swallowed: the error worth reporting is the one
    that left the dialog open.
    """
    with suppress(Exception):
        _close(page)


def _column_anywhere(page: Page, schedule_id: str) -> bool:
    """Whether any page of the open journal still has this column."""
    from .journal import each_journal_page

    link = sel.COLUMN_EDIT_LINK.format(id=schedule_id)
    return any(page.query_selector(link) for _ in each_journal_page(page))


def _dialog_date(page: Page) -> str:
    return page.eval_on_selector(sel.DATE_INPUT_HIDDEN, "el => el.value")


def delete_lesson(page: Page, row: TopicRow, expected: date) -> None:
    """Delete one column, after checking in its own dialog that it is the one.

    On success the site reloads the page. An error comes back as a plain
    alert(), which is caught and turned into an exception.
    """
    open_lesson_dialog(page, row)
    shown = _dialog_date(page)
    if shown != expected.isoformat():
        _close(page)
        raise LessonError(
            f"Діалог уроку {row.date_text} показує дату {shown!r}, "
            f"а мала бути {expected.isoformat()}. Нічого не видалено."
        )

    alerts: list[str] = []

    def on_alert(dialog) -> None:
        alerts.append(dialog.message)
        dialog.accept()

    page.on("dialog", on_alert)
    try:
        page.click(sel.DELETE_LESSON_LINK)
        page.wait_for_selector(sel.DELETE_CONFIRM_BUTTON, state="visible")
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
            page.click(sel.DELETE_CONFIRM_BUTTON)
    except Exception as exc:
        if alerts:
            raise LessonError(f"Сайт не видалив урок: {alerts[-1]}") from exc
        raise
    finally:
        page.remove_listener("dialog", on_alert)
    page.wait_for_timeout(1_500)

    # The reload may land on another page of the journal than the column's,
    # so the one on screen proves nothing: every page is looked through.
    if _column_anywhere(page, row.schedule_id):
        raise LessonError(
            f"Після видалення стовпчик {row.date_text} досі в журналі."
        )


def set_lesson_type(page: Page, row: TopicRow, label: str) -> str | None:
    """Give one column the type `label`.

    Returns the type it had before, or None when it already had this one and
    nothing was saved.
    """
    open_lesson_dialog(page, row)
    try:
        current = page.eval_on_selector(
            sel.LESSON_TYPE_SELECT, "el => el.options[el.selectedIndex].text.trim()"
        )
        if current == label:
            _close(page)
            return None
        options = page.eval_on_selector_all(
            f"{sel.LESSON_TYPE_SELECT} option",
            "els => els.map(e => ({value: e.value, label: e.text.trim()}))",
        )
        match = next((o for o in options if o["label"] == label), None)
        if match is None:
            raise LessonError(f"У полі «Тип уроку» немає варіанта «{label}».")
        page.select_option(sel.LESSON_TYPE_SELECT, value=match["value"])
        page.click(sel.SAVE_BUTTON)
        page.wait_for_selector(sel.DIALOG, state="hidden", timeout=30_000)
    except Exception:
        _close_after_failure(page)
        raise
    page.wait_for_load_state("networkidle")
    return current
