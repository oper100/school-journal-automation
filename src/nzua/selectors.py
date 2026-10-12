"""Every nz.ua selector lives here.

Filled in from the recon dumps under `recon/`. When the site changes its
markup, this is the only file that should need editing.

The add-column dialog turned out to be plain HTML: the fields are native
`<select>` elements inside a fancybox popup, so they can be set directly
rather than clicked open. The visible date box is read-only and backed by a
hidden input holding an ISO date, which is the value actually posted.
"""

from __future__ import annotations

SELECTORS_READY = True

# --- semester selector (in the page header, on every logged-in page) --------

# Changing this posts /site/semester-change, which switches the semester for
# the whole session — not just the open tab.
SEMESTER_FORM = "#semester-select-form"
SEMESTER_SELECT = "#personalselectform-semester_id"
# The option the server rendered as chosen carries the attribute; the DOM
# property alone would also reflect a selection we made but never posted.
SEMESTER_SELECTED_OPTION = "option[selected]"
# Labels read "2025-2026 [2], 07.01.2026 - 05.06.2026", with the semester the
# school is actually in marked. On the dumps it is also the selected one, so
# whether the mark follows the school year or the selection is untested; the
# code only reads it before switching, where the two agree.
SEMESTER_CURRENT_MARKER = "(поточний)"

# --- journal list -----------------------------------------------------------

JOURNAL_LIST_PATH = "/journal/list"
# One row per subject: <td>subject</td><td><a href=...>class</a>…</td>
JOURNAL_LIST_ROW = "table.journal-choose tbody tr"
JOURNAL_LIST_SUBJECT_CELL = "td:first-child"
JOURNAL_LIST_CLASS_LINK = "td:nth-child(2) a"

# --- journal page -----------------------------------------------------------

JOURNAL_TITLE = ".journal-scores__title"
# Header cells of the marks table; one per existing lesson column.
COLUMN_HEADER_CELLS = "#journalList thead td.pt-point"
# Inside a header cell, present only on the first column of each month.
COLUMN_MONTH_MARKER = "span.pt-month"

ADD_COLUMN_BUTTON = "a.journal-scores-add-col"

# A journal shows twenty lesson columns per page — the marks table and the
# topics table alike — and opens on the *last* page. Each link carries its
# zero-based page in data-page; « and » repeat the neighbours' links.
JOURNAL_PAGE_LINK = ".journal-scores-panel ul.pagination a[data-page]"

# --- add-column dialog ------------------------------------------------------

DIALOG = "#fancybox-wrap"
DIALOG_TITLE = "#fancybox-wrap .popup__title"
DIALOG_FORM = "#fancybox-wrap form.modal-ajax-form"
DIALOG_CLOSE = "#fancybox-close"

LESSON_TYPE_SELECT = "#osvitaschedulereal-lesson_type_id"
DATE_INPUT_HIDDEN = "#lesson_date"       # name="OsvitaScheduleReal[lesson_date]"
DATE_INPUT_VISIBLE = "#lesson_date_alt"  # read-only, datepicker-backed
REPEAT_SELECT = "#osvitaschedulereal-repeate_type"
LESSON_NUMBER_SELECT = "#osvitaschedulereal-buzzer_id"
CABINET_SELECT = "#osvitaschedulereal-room_id"
SAVE_BUTTON = "#fancybox-wrap a.form-submit-btn"

# Exact option labels, copied from the dumps.
LESSON_TYPE_OPTION = "Поточна"
REPEAT_OPTION_WEEKLY_UNTIL_MONTH_END = "Щотижня до кінця місяця"

# Lesson numbers read as "3 урок (10:30 - 11:15)"; cabinets as
# "Кабінет 9-А Клас[4-09]" — both are matched on their leading part.
LESSON_NUMBER_LABEL = "{n} урок"
CABINET_LABEL_PREFIX = "Кабінет {cabinet} "


# --- lesson topics and homework ---------------------------------------------

TOPICS_TABLE = "div.homework-table"
TOPIC_ROW = "div.homework-table div.homework-row:not(.homework-row--header)"
TOPIC_CELL = "div.homework__item"
# The pencil. The neighbouring a.hometask-add opens «Дистанційне завдання»,
# a different dialog, so match on this class alone.
TOPIC_EDIT_LINK = "a.modal-box"

HOMEWORK_DIALOG_TITLE_TEXT = "Домашнє завдання"
TOPIC_TEXTAREA = "#osvitaschedulereal-lesson_topic"
LESSON_NUMBER_INPUT = "#osvitaschedulereal-lesson_number_in_plan"
HOMEWORK_TEXTAREA = "#osvitaschedulereal-hometask"
HOMEWORK_DUE_SELECT = "#osvitaschedulereal-hometask_to"
SUBSTITUTE_TEACHER_SELECT = "#osvitaschedulereal-second_personal_id"
SUBSTITUTE_SUBJECT_SELECT = "#osvitaschedulereal-second_predmet_id"

# The due-date list holds every remaining lesson as an ISO date; the lesson
# being edited is the one labelled like "2026-09-03 (Поточний урок)".
CURRENT_LESSON_MARKER = "(Поточний урок)"


# --- editing or deleting an existing column ---------------------------------

# Every lesson has a schedule id. The topics table's pencil and the marks
# table's date link both carry it in their href, which is how a topic row is
# tied to its column: "/journal/add-edit-lesson?journal=…&schedule=<id>".
SCHEDULE_ID_PATTERN = r"schedule=(\d+)"
# The date in a column header opens «Редагувати урок» — the add-column dialog
# again, with the lesson's own type, date, time and room, plus «Видалити».
# Filled in with the schedule id; the href ends with it.
COLUMN_EDIT_LINK = '#journalList thead a.modal-box[href$="schedule={id}"]'
EDIT_LESSON_DIALOG_TITLE_TEXT = "Редагувати урок"
DELETE_LESSON_LINK = "#fancybox-wrap a.delete-lesson"
# «Видалити» asks through a krajee (bootstrap) modal, not window.confirm.
# Its «Так» is the warning-coloured button; on success the page reloads.
DELETE_CONFIRM_BUTTON = ".bootstrap-dialog .modal-footer button.btn-warning"

# Marks table body: one td.pt-point per column, in header order.
MARK_ROW = "#journalList tbody tr"
MARK_CELL = "td.pt-point"
MARK_INPUT = "input.mark-cell"

# Lesson types set from the topic, by option label. Plain «Поточна» stays
# what add-columns puts in; these are the ones a topic can announce.
LESSON_TYPE_LAB = "Лабораторна робота"
LESSON_TYPE_TEST = "Контрольна робота"


def require_ready() -> None:
    """Kept as a guard so a half-finished selector set cannot drive the site."""
    if not SELECTORS_READY:
        raise RuntimeError(
            "Селектори nz.ua не заповнені.\n"
            "Зроби розвідку:  python -m nzua recon"
        )
