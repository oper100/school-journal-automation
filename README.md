# nzua — automating a teacher's journal on nz.ua

**English** · [Українська](README.uk.md)

A command-line tool that does a physics teacher's routine admin in
[nz.ua](https://nz.ua), the Ukrainian school e-journal. It drives a visible
Chrome window with Playwright:

- creates the month's lesson columns from the weekly timetable (26 columns
  across 11 journals each month);
- writes lesson topics from the semester's calendar plan, which arrives as
  `.docx` files;
- fills in homework, collected from last year's journals and reused;
- checks journals for gaps, broken numbering and topics that drifted from
  the plan, and offers to fix them.

The tool is in real use on the teacher's journals since September 2026.

The tool's own interface (CLI help, prompts, logs) is in Ukrainian, because
that is the user's language. The code, comments and tests are in English.

## Design

The rule throughout: **never write to a real journal on a guess.** A wrong
write lands in an official school record and has to be undone by hand.

- **Dry runs and a read-only check.** `--dry-run` prints every write it
  would make. `check` reads all journals and reports problems without
  changing anything.
- **Stop and ask instead of guessing.** When the journal disagrees with the
  plan (a duplicate column, a numbering gap, two journals matching one class),
  the tool stops and asks: skip, do it anyway, do the same for all, or stop.
- **Duplicates are counted, not detected.** 9-В has physics twice on
  Tuesday, so two Tuesday columns are correct and a third is not. Presence
  checks would get this wrong.
- **Verification before destruction.** Deleting a lesson is the one action
  that cannot be undone. Before each delete, the tool reads the date back from
  the dialog itself and refuses if it is not the planned one.
- **Side effects get cleaned up.** Switching semester in nz.ua applies to the
  whole account, so the tool always switches back, even after a crash.
  Commands that write check first that the *current* semester is selected.
- **Selectors live in one file.** `selectors.py` holds every CSS/text
  selector. They came from a `recon` pass over the live site, which saves the
  page markup at each step, not from guesses.
- **Pure logic is separate from the browser.** Date math, timetable
  expansion, plan parsing, journal-vs-plan alignment and homework matching
  are plain functions. 260+ tests cover them in about 3 seconds, with no
  network and no browser.

### The browser

nz.ua sits behind Cloudflare. A Chrome launched by Playwright is met with a
"confirm you are human" challenge, even with a persistent profile and no
automation flags. A plain Chrome started as its own process, with Playwright
attached over the DevTools port, is not. The tool therefore attaches to an
ordinary Chrome window that the teacher can see and stop at any time. The
login stays in that profile, so signing in happens once. Both modes were
tested against the live site before choosing; `--browser launch` is kept as a
diagnostic.

## How it was built

I built the whole project with [Claude Code](https://claude.com/claude-code)
as a pair programmer. I owned the problem, the decisions and every run
against the live site. Claude wrote most of the code under that direction.
The working loop:

1. **Recon before code.** Neither of us knew nz.ua's markup. Instead of
   letting the model guess selectors, we first wrote `recon.py`: I walked
   through the real dialogs while it saved the DOM at each step, and the
   selectors were written from those dumps. Nothing in `selectors.py` is guessed.
2. **Experiments over assumptions.** When the site blocked automation, we
   didn't pile on stealth tweaks. We tested launched vs. attached Chrome
   against the live site, kept the result, and wrote down why (see
   "The browser" above).
3. **Root-cause debugging.** Bugs went through a structured debugging
   workflow (the `systematic-debugging` skill): reproduce, find the cause,
   then fix. Examples: a late table refresh wrote one row twice, and a
   redundant navigation aborted the next one.
4. **Tests as the contract for generated code.** Each feature came with
   tests on its pure logic. That made it possible to accept large changes
   from the model without reading every line against the live site.
5. **Human in the loop for anything live.** Every run against the real
   journals needed my explicit go-ahead, and approval for one run did not
   carry over to the next. I recorded this rule, together with "commit
   freely, never push without asking", in Claude Code's persistent memory, so
   it held across sessions.
6. **Decisions are written down.** The reasons for non-obvious choices live
   in code comments and in this README, so the next session (or the next
   reader) does not have to rediscover them.

What I would do differently: split `runner.py`, which grew past 1,000
lines as features landed, into per-command modules earlier.

## Usage

Requires Python 3.10+ and Google Chrome on Windows (the default `attach`
mode looks for `chrome.exe` in the usual install folders).

```bash
pip install -e .
python -m playwright install chromium   # only needed for the diagnostic `--browser launch`

python -m nzua --help           # full guide, in Ukrainian
python -m nzua add-columns --month 2026-09 --dry-run
python -m nzua run-month --month 2026-09 --count 3
python -m nzua check
```

| Command | What it does |
|---|---|
| `recon` | walk the site with the tool and save its markup |
| `add-columns` | create a month of lesson columns from `schedule.yaml` |
| `import-planning` | parse the teacher's `.docx` calendar plans into `planning/*.yaml` |
| `fill-topics` | write lesson topics (and homework) from the plan |
| `run-month` | `add-columns` + `fill-topics` for every class in one browser session |
| `dump-homework` | collect homework from existing journals into `homework/*.yaml` |
| `check` | report gaps, numbering errors and plan drift; changes nothing |
| `delete-lessons` | delete columns in a date range, e.g. holidays |
| `set-lesson-types` | mark lab and test lessons from their topic |

## Layout

| Path | Purpose |
|---|---|
| `schedule.yaml` | weekly timetable |
| `planning/*.yaml`, `homework/*.yaml` | topics and homework per grade; generated by `import-planning` and `dump-homework`, not committed |
| `src/nzua/schedule.py` | timetable model and date math |
| `src/nzua/planning.py` | `.docx` parsing (stdlib `zipfile` + XML, no extra deps) |
| `src/nzua/journal.py` | finding journals, reading the marks table header |
| `src/nzua/topics.py` | topics table, homework dialog, `check` |
| `src/nzua/lessons.py` | editing and deleting existing lessons |
| `src/nzua/homework.py` | homework store and matching |
| `src/nzua/runner.py` | the commands' browser sessions |
| `src/nzua/selectors.py` | every selector for the site |
| `src/nzua/browser.py` | starting and attaching to Chrome |

## Tests

```bash
python -m pytest
```
