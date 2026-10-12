"""Filling in and saving the "Додати урок" dialog.

The dialog's fields are native selects, so each is set by matching the option
label rather than by clicking a list open. The date is the exception: its
visible box is read-only and driven by a datepicker, while the value actually
posted lives in a hidden input holding an ISO date. Both are written — the
hidden one so the right date is submitted, the visible one so the dialog on
screen matches what is about to be saved.
"""

from __future__ import annotations

from datetime import date

from playwright.sync_api import Page

from . import selectors as sel
from .schedule import ColumnTask

UK_MONTHS_SHORT = [
    "січ.", "лют.", "бер.", "квіт.", "трав.", "черв.",
    "лип.", "серп.", "вер.", "жовт.", "лист.", "груд.",
]


class DialogError(RuntimeError):
    """The dialog did not offer what the schedule asked for."""


def _select_by_label_prefix(page: Page, selector: str, prefix: str, field: str) -> str:
    """Choose the one option whose label starts with `prefix`."""
    options = page.eval_on_selector_all(
        f"{selector} option",
        "els => els.map(e => ({value: e.value, label: e.text.trim()}))",
    )
    matches = [o for o in options if o["label"].startswith(prefix)]
    if not matches:
        raise DialogError(
            f"У полі «{field}» немає варіанта, що починається з {prefix!r}. "
            f"Є: {', '.join(o['label'] for o in options if o['label'])[:300]}"
        )
    if len(matches) > 1:
        raise DialogError(
            f"У полі «{field}» під {prefix!r} підходить кілька варіантів: "
            f"{', '.join(o['label'] for o in matches)}"
        )
    page.select_option(selector, value=matches[0]["value"])
    return matches[0]["label"]


def _set_date(page: Page, when: date) -> None:
    """Write the date into both the posted hidden field and the visible box."""
    visible = f"{when.day} {UK_MONTHS_SHORT[when.month - 1]} {when.year} р."
    page.eval_on_selector(
        sel.DATE_INPUT_HIDDEN, "(el, v) => { el.value = v; }", when.isoformat()
    )
    page.eval_on_selector(
        sel.DATE_INPUT_VISIBLE, "(el, v) => { el.value = v; }", visible
    )


def open_dialog(page: Page) -> None:
    """Click «Додати стовпчик» and wait for the dialog's form."""
    page.click(sel.ADD_COLUMN_BUTTON)
    page.wait_for_selector(sel.DIALOG_FORM, state="visible")


def close_dialog(page: Page) -> None:
    """Dismiss the dialog without saving."""
    if page.is_visible(sel.DIALOG):
        page.click(sel.DIALOG_CLOSE)
        page.wait_for_selector(sel.DIALOG, state="hidden")


def fill_dialog(page: Page, task: ColumnTask, lesson_type: str) -> dict[str, str]:
    """Set every field of an open dialog. Returns what was chosen, for the log."""
    slot = task.slot
    chosen = {
        "тип": _select_by_label_prefix(
            page, sel.LESSON_TYPE_SELECT, lesson_type, "Тип уроку"
        ),
        "повторення": _select_by_label_prefix(
            page,
            sel.REPEAT_SELECT,
            sel.REPEAT_OPTION_WEEKLY_UNTIL_MONTH_END,
            "Частота повторень",
        ),
        "урок": _select_by_label_prefix(
            page,
            sel.LESSON_NUMBER_SELECT,
            sel.LESSON_NUMBER_LABEL.format(n=slot.lesson_no),
            "Час уроку",
        ),
        "кабінет": _select_by_label_prefix(
            page,
            sel.CABINET_SELECT,
            sel.CABINET_LABEL_PREFIX.format(cabinet=slot.cabinet),
            "Кабінет",
        ),
    }
    _set_date(page, task.date)
    chosen["дата"] = task.date.isoformat()
    return chosen


def save_dialog(page: Page) -> None:
    """Submit the dialog and wait for it to close."""
    page.click(sel.SAVE_BUTTON)
    page.wait_for_selector(sel.DIALOG, state="hidden", timeout=30_000)
    page.wait_for_load_state("networkidle")


def add_column(page: Page, task: ColumnTask, lesson_type: str) -> dict[str, str]:
    """Create one lesson column: open the dialog, fill it, save it."""
    open_dialog(page)
    try:
        chosen = fill_dialog(page, task, lesson_type)
    except Exception:
        close_dialog(page)
        raise
    save_dialog(page)
    return chosen
