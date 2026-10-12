"""The schedule: what lesson columns exist, and on which date each one starts.

This module is deliberately free of any browser or network code so that the
date arithmetic — the part most likely to be wrong — can be tested on its own.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import yaml

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_LABELS_UK = {
    0: "понеділок",
    1: "вівторок",
    2: "середа",
    3: "четвер",
    4: "п'ятниця",
    5: "субота",
    6: "неділя",
}

_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")


@dataclass(frozen=True)
class LessonSlot:
    """One recurring lesson: a class, a subject, a weekday and a period."""

    subject: str
    class_name: str
    weekday: int
    lesson_no: int
    cabinet: str

    def describe(self) -> str:
        return (
            f"{self.subject} {self.class_name} — {WEEKDAY_LABELS_UK[self.weekday]}, "
            f"{self.lesson_no}-й урок, кабінет {self.cabinet}"
        )


@dataclass(frozen=True)
class ColumnTask:
    """A slot pinned to the date of its first occurrence in the target month."""

    slot: LessonSlot
    date: date

    @property
    def journal(self) -> tuple[str, str]:
        return self.slot.subject, self.slot.class_name


@dataclass(frozen=True)
class Schedule:
    lesson_type: str
    repeat: str
    slots: tuple[LessonSlot, ...]
    planning: dict[str, dict[str, str]] = field(default_factory=dict)
    homework: dict[str, dict[str, str]] = field(default_factory=dict)

    def plan_path(self, subject: str, class_name: str) -> str:
        """Which calendar plan a class follows, by subject and year group."""
        from .planning import grade_of  # local: keeps the import cycle open

        return self._path(self.planning, "планування", subject, grade_of(class_name))

    def homework_path(self, subject: str, grade: int) -> str:
        """Where the collected homework of one year group is kept.

        By year group, not by class: last year's 9-Б and this year's 9-А are
        different classes following the same plan, so they share one file.
        """
        return self._path(self.homework, "домашніх завдань", subject, grade)

    def _path(
        self, mapping: dict[str, dict[str, str]], what: str, subject: str, grade: int
    ) -> str:
        try:
            return mapping[subject][str(grade)]
        except KeyError:
            raise KeyError(
                f"У schedule.yaml немає {what} для «{subject}» "
                f"{grade}-ї паралелі."
            ) from None

    @property
    def subjects(self) -> list[str]:
        return list(dict.fromkeys(slot.subject for slot in self.slots))

    @property
    def class_names(self) -> list[str]:
        return list(dict.fromkeys(slot.class_name for slot in self.slots))

    def filter(
        self, subject: str | None = None, class_name: str | None = None
    ) -> list[LessonSlot]:
        """Select slots by subject and/or class, rejecting names not in the file."""
        if subject is not None and subject not in self.subjects:
            raise ValueError(
                f"Невідомий предмет {subject!r}. Доступні: {', '.join(self.subjects)}"
            )
        if class_name is not None and class_name not in self.class_names:
            raise ValueError(
                f"Невідомий клас {class_name!r}. Доступні: {', '.join(self.class_names)}"
            )
        return [
            slot
            for slot in self.slots
            if (subject is None or slot.subject == subject)
            and (class_name is None or slot.class_name == class_name)
        ]


def load_schedule(path: str | Path) -> Schedule:
    """Read schedule.yaml into a Schedule, defaulting each cabinet to its class."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    slots: list[LessonSlot] = []
    for subject, classes in raw["subjects"].items():
        for class_name, entries in classes.items():
            for entry in entries:
                day = str(entry["day"]).lower()
                if day not in WEEKDAYS:
                    raise ValueError(
                        f"{subject} {class_name}: невідомий день тижня {entry['day']!r}"
                    )
                slots.append(
                    LessonSlot(
                        subject=str(subject),
                        class_name=str(class_name),
                        weekday=WEEKDAYS[day],
                        lesson_no=int(entry["lesson"]),
                        cabinet=str(entry.get("cabinet") or class_name),
                    )
                )

    return Schedule(
        lesson_type=raw["lesson_type"],
        repeat=raw["repeat"],
        slots=tuple(slots),
        planning={
            subject: {str(grade): path for grade, path in grades.items()}
            for subject, grades in (raw.get("planning") or {}).items()
        },
        homework={
            subject: {str(grade): path for grade, path in grades.items()}
            for subject, grades in (raw.get("homework") or {}).items()
        },
    )


def parse_month(value: str) -> tuple[int, int]:
    """Parse a --month argument of the form YYYY-MM."""
    match = _MONTH_RE.match(value.strip())
    if not match:
        raise ValueError(f"Місяць має бути у форматі YYYY-MM, отримано {value!r}")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Немає місяця номер {month}")
    return year, month


def first_weekday_in_month(year: int, month: int, weekday: int) -> date:
    """The earliest date in the month that falls on `weekday` (0 = Monday)."""
    first = date(year, month, 1)
    return first.replace(day=1 + (weekday - first.weekday()) % 7)


def last_weekday_in_month(year: int, month: int, weekday: int) -> date:
    """The latest date in the month that falls on `weekday`. Used for reporting."""
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return last.replace(day=last_day - (last.weekday() - weekday) % 7)


def occurrences_in_month(year: int, month: int, weekday: int) -> list[date]:
    """Every date in the month on `weekday` — what the site's weekly repeat creates."""
    start = first_weekday_in_month(year, month, weekday)
    last_day = calendar.monthrange(year, month)[1]
    return [
        start.replace(day=day)
        for day in range(start.day, last_day + 1, 7)
    ]


def plan_month(
    schedule: Schedule,
    year: int,
    month: int,
    subject: str | None = None,
    class_name: str | None = None,
) -> list[ColumnTask]:
    """Expand the schedule into one dated task per lesson slot.

    Only the first occurrence is dated: the site's "щотижня до кінця місяця"
    option creates the remaining weeks itself.

    Tasks are grouped by journal (subject + class) so the runner opens each
    journal once, and ordered by date inside a journal.
    """
    slots: Iterable[LessonSlot] = schedule.filter(subject=subject, class_name=class_name)
    tasks = [
        ColumnTask(slot=slot, date=first_weekday_in_month(year, month, slot.weekday))
        for slot in slots
    ]
    journal_order = list(dict.fromkeys(task.journal for task in tasks))
    return sorted(
        tasks,
        key=lambda t: (journal_order.index(t.journal), t.date, t.slot.lesson_no),
    )
