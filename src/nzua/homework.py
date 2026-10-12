"""The homework store: which homework belongs to which lesson of a plan.

Homework is entered in nz.ua once, lesson by lesson, and is then worth reusing
— by next year's class of the same year group, or by the other classes of this
year's parallel. This module holds the collected «lesson → homework» pairs and
answers the only question the runner asks: what homework goes with this lesson.

A lesson is keyed by its number *and* its topic, never by the topic alone:
«Розв'язування задач.» appears dozens of times in one plan, each time with
different homework. The topic is still kept and compared, because plans are
renumbered between years — when the numbers have shifted, a topic that occurs
exactly once still identifies its lesson.

Storage mirrors `planning/`: one YAML file per subject and year group, meant to
be read and corrected by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


class HomeworkError(ValueError):
    """The store does not hold what was asked of it."""


def normalise(text: str) -> str:
    """Compare text by its words: the page re-wraps and pads cells."""
    return " ".join(text.split())


# Below this, a shared fragment says nothing: "Задачі." sits inside plenty of
# unrelated topics.
_SHORTEST_MEANINGFUL_TOPIC = 12


def topics_match(one: str, other: str) -> bool:
    """Whether two spellings name the same lesson.

    Equal after normalising, or one contained in the other: the teacher adds
    «Вступний інструктаж.» to the first lesson of the year, and the calendar
    plan carries notes («Демонстрації 1. …») that the journal does not. Used
    only where the lesson number already agrees — on its own, a shared
    fragment would not be evidence enough.
    """
    one, other = normalise(one), normalise(other)
    if one == other:
        return True
    shorter, longer = sorted((one, other), key=len)
    return len(shorter) >= _SHORTEST_MEANINGFUL_TOPIC and shorter in longer


@dataclass(frozen=True)
class HomeworkEntry:
    number: int
    topic: str
    homework: str


@dataclass(frozen=True)
class HomeworkStore:
    subject: str
    grade: int
    sources: tuple[str, ...]
    entries: tuple[HomeworkEntry, ...]

    def lookup(self, number: int, topic: str) -> str | None:
        """The homework for one lesson, or None when the store cannot tell.

        Tried in order: the entry with this number whose topic matches — see
        `topics_match`, which forgives a note added to one side — then a topic
        that occurs exactly once in the whole store, compared strictly. A
        number whose topic disagrees outright is not used: that is a
        renumbered plan, not this lesson.
        """
        wanted = normalise(topic)
        for entry in self.entries:
            if entry.number == number and topics_match(entry.topic, wanted):
                return entry.homework

        matches = {
            entry.homework
            for entry in self.entries
            if normalise(entry.topic) == wanted
        }
        if len(matches) == 1:
            return next(iter(matches))
        return None


def harvest(rows: Iterable, source: str = "") -> list[HomeworkEntry]:
    """Collect the filled-in homework of one journal's topics table.

    Takes `TopicRow` records as `topics.read_topic_rows` produces them. A row
    without a number, a topic or homework has nothing to contribute.
    """
    entries: list[HomeworkEntry] = []
    for row in rows:
        if row.lesson_number is None:
            continue
        topic = normalise(row.topic)
        homework = row.homework.strip()
        if not topic or not homework:
            continue
        entries.append(
            HomeworkEntry(number=row.lesson_number, topic=topic, homework=homework)
        )
    return entries


def combine(
    first: Iterable[HomeworkEntry], second: Iterable[HomeworkEntry]
) -> tuple[list[HomeworkEntry], int]:
    """Merge two sets of entries; `first` wins. Returns (entries, overridden).

    `overridden` counts the lessons where the two disagreed, so a run can say
    how much it changed rather than overwriting in silence.
    """
    merged: dict[int, HomeworkEntry] = {entry.number: entry for entry in first}
    overridden = 0
    for entry in second:
        kept = merged.get(entry.number)
        if kept is None:
            merged[entry.number] = entry
        elif kept.homework != entry.homework:
            overridden += 1
    return [merged[number] for number in sorted(merged)], overridden


def store_of(
    subject: str,
    grade: int,
    entries: Iterable[HomeworkEntry],
    sources: Iterable[str] = (),
) -> HomeworkStore:
    return HomeworkStore(
        subject=subject,
        grade=grade,
        sources=tuple(dict.fromkeys(sources)),
        entries=tuple(sorted(entries, key=lambda e: e.number)),
    )


def write_store(store: HomeworkStore, path: Path) -> Path:
    """Save a store as YAML a person can read and correct."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "subject": store.subject,
                "grade": store.grade,
                "sources": list(store.sources),
                "lessons": [
                    {
                        "number": entry.number,
                        "topic": entry.topic,
                        "homework": entry.homework,
                    }
                    for entry in store.entries
                ],
            },
            allow_unicode=True,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )
    return path


def load_store(path: Path) -> HomeworkStore:
    """Read back a store written by `write_store`."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return HomeworkStore(
            subject=raw["subject"],
            grade=int(raw["grade"]),
            sources=tuple(raw.get("sources") or ()),
            entries=tuple(
                HomeworkEntry(
                    number=int(item["number"]),
                    topic=item["topic"],
                    homework=item["homework"],
                )
                for item in raw.get("lessons") or ()
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HomeworkError(f"Файл ДЗ «{path.name}» не читається: {exc}") from None


def load_store_if_present(path: Path) -> HomeworkStore | None:
    """The store for a journal, or None when none has been collected yet."""
    path = Path(path)
    return load_store(path) if path.exists() else None
