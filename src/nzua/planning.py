"""Reading the calendar plans: which topic belongs to which lesson number.

The teacher's five .docx files use two different table layouts:

* 8 and 9 grade — «№ уроку | Дата уроку | Тема уроку | Примітки», with the
  number column left empty, so a lesson's number is its position;
* 10, 11 and astronomy — «№ уроку | Параграф | Тема уроку | Дата | Дата»,
  with the numbers written out.

Both interleave single-cell rows that name a section («РОЗДІЛ 1. …»,
«Виставлення оцінок за тему.»), and the numbered layout also carries rows with
a topic but no number («Демонстрації 1. …»). Neither is a lesson.

.docx is a zip holding WordprocessingML, so it is read with the standard
library rather than a dependency: python-docx would add nothing here.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import yaml

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HEADER_FIRST_CELL = "№ уроку"


class PlanError(ValueError):
    """The plan does not hold what was asked of it."""


@dataclass(frozen=True)
class Lesson:
    number: int
    topic: str


@dataclass(frozen=True)
class Plan:
    subject: str
    grade: int
    source: str
    lessons: tuple[Lesson, ...]

    def lesson(self, number: int) -> Lesson:
        for lesson in self.lessons:
            if lesson.number == number:
                return lesson
        raise PlanError(
            f"У плануванні «{self.source}» немає уроку № {number}: "
            f"усього {len(self.lessons)} уроків."
        )


@dataclass(frozen=True)
class DocxSource:
    filename: str
    subject: str
    grade: int
    output: str


DOCX_SOURCES = (
    DocxSource("8 клас.docx", "Фізика", 8, "physics-8.yaml"),
    DocxSource("9 клас.docx", "Фізика", 9, "physics-9.yaml"),
    DocxSource("10 клас.docx", "Фізика", 10, "physics-10.yaml"),
    DocxSource("11 клас.docx", "Фізика", 11, "physics-11.yaml"),
    DocxSource("астрономія.docx", "Астрономія", 11, "astronomy-11.yaml"),
)


def grade_of(class_name: str) -> int:
    """The year a class belongs to: 9-Б is in the 9th, and reads its plan."""
    match = re.match(r"\s*(\d{1,2})", class_name)
    if not match:
        raise ValueError(f"Не бачу номера паралелі в назві класу {class_name!r}")
    return int(match.group(1))


def _cell_text(cell: ElementTree.Element) -> str:
    """All the text of one table cell, with line breaks folded into spaces."""
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(f"{{{W}}}t")).strip()
        for paragraph in cell.iter(f"{{{W}}}p")
    ]
    return " ".join(" ".join(paragraphs).split())


def _rows(path: Path):
    """Every table row of the document, as a list of cell strings."""
    with zipfile.ZipFile(path) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    for table in document.iter(f"{{{W}}}tbl"):
        for row in table.iter(f"{{{W}}}tr"):
            yield [_cell_text(cell) for cell in row.iter(f"{{{W}}}tc")]


def _is_numbered_layout(rows: list[list[str]], name: str) -> bool:
    """Which of the two layouts this document uses, decided by its header.

    The header alone can say this; a data row cannot. Astronomy's
    «Демонстрації …» row leaves the number cell empty inside the *numbered*
    layout, so treating an empty cell as "number by position" would quietly
    hand it a lesson number.
    """
    for cells in rows:
        if cells and cells[0] == HEADER_FIRST_CELL:
            return len(cells) >= 5
    raise PlanError(
        f"У «{name}» не знайшлось шапки таблиці «{HEADER_FIRST_CELL}»."
    )


def parse_planning_docx(path: Path, subject: str, grade: int) -> Plan:
    """Turn one planning document into a numbered list of topics."""
    path = Path(path)
    rows = list(_rows(path))
    numbered = _is_numbered_layout(rows, path.name)
    lessons: list[Lesson] = []

    for cells in rows:
        if len(cells) < 4:
            continue  # a section heading spans a single cell
        if cells[0] == HEADER_FIRST_CELL:
            continue
        topic = cells[2]
        if not topic:
            continue

        if numbered:
            written = cells[0].strip()
            if not written.isdigit():
                continue  # «Демонстрації …» and other unnumbered notes
            number = int(written)
        else:
            number = len(lessons) + 1

        lessons.append(Lesson(number=number, topic=topic))

    if not lessons:
        raise PlanError(f"У «{path.name}» не знайшлось жодного уроку.")

    expected = list(range(1, len(lessons) + 1))
    actual = [lesson.number for lesson in lessons]
    if actual != expected:
        first_bad = next(
            (a for a, e in zip(actual, expected) if a != e), actual[-1]
        )
        raise PlanError(
            f"У «{path.name}» нумерація уроків не суцільна: "
            f"збій біля уроку № {first_bad}."
        )

    return Plan(
        subject=subject, grade=grade, source=path.name, lessons=tuple(lessons)
    )


def write_plan(plan: Plan, path: Path) -> Path:
    """Save a plan as YAML that a person can read and correct."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "subject": plan.subject,
                "grade": plan.grade,
                "source": plan.source,
                "lessons": [
                    {"number": lesson.number, "topic": lesson.topic}
                    for lesson in plan.lessons
                ],
            },
            allow_unicode=True,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )
    return path


def load_plan(path: Path) -> Plan:
    """Read back a plan written by `write_plan`."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Plan(
        subject=raw["subject"],
        grade=int(raw["grade"]),
        source=raw["source"],
        lessons=tuple(
            Lesson(number=int(item["number"]), topic=item["topic"])
            for item in raw["lessons"]
        ),
    )
