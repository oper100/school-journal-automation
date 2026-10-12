"""Recon: capture the real nz.ua markup so selectors can be written against it.

The site's markup is unknown until a human walks the flow once. This module
drives that walk: it pauses at each step, waits for the operator to reach the
right screen, and dumps everything a selector author needs.

Nothing here changes data on the site. It only reads and screenshots.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Frame, Page

from .browser import BASE_URL, PROJECT_ROOT, ensure_logged_in

RECON_DIR = PROJECT_ROOT / "recon"

INTERACTIVE_JS = """
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type'),
    id: el.id || null,
    name: el.getAttribute('name'),
    classes: el.getAttribute('class'),
    role: el.getAttribute('role'),
    placeholder: el.getAttribute('placeholder'),
    ariaLabel: el.getAttribute('aria-label'),
    dataAttrs: Object.fromEntries(
      [...el.attributes]
        .filter((a) => a.name.startsWith('data-'))
        .map((a) => [a.name, a.value])
    ),
    text: (el.innerText || el.value || '').trim().slice(0, 120),
    options: el.tagName === 'SELECT'
      ? [...el.options].map((o) => ({ value: o.value, label: o.text.trim() }))
      : undefined,
  });
  const nodes = [...document.querySelectorAll(
    'input, select, textarea, button, a[role=button], [role=combobox], ' +
    '[role=listbox], [role=option], [role=dialog], [class*=modal], ' +
    '[class*=popup], [class*=dropdown], [class*=select]'
  )];
  return nodes.filter(visible).map(describe);
}
"""


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _dump_frame(frame: Frame, out_dir: Path, index: int) -> dict:
    """Write one frame's HTML and return a summary record."""
    name = f"frame{index}"
    try:
        html = frame.content()
    except Exception as exc:  # detached frames happen on busy pages
        return {"frame": name, "url": frame.url, "error": str(exc)}
    (out_dir / f"{name}.html").write_text(html, encoding="utf-8")
    try:
        interactive = frame.evaluate(INTERACTIVE_JS)
    except Exception as exc:
        interactive = [{"error": str(exc)}]
    (out_dir / f"{name}.interactive.json").write_text(
        json.dumps(interactive, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "frame": name,
        "url": frame.url,
        "html_bytes": len(html),
        "interactive_elements": len(interactive),
    }


def capture(page: Page, label: str) -> Path:
    """Dump the current screen: every frame's HTML, its widgets, a screenshot."""
    out_dir = RECON_DIR / f"{_timestamp()}-{label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = [_dump_frame(frame, out_dir, i) for i, frame in enumerate(page.frames)]
    try:
        page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
    except Exception:
        page.screenshot(path=str(out_dir / "screenshot.png"))

    summary = {
        "label": label,
        "url": page.url,
        "title": page.title(),
        "frames": frames,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  [дамп] {out_dir.name}: {page.url}")
    return out_dir


def _pause(message: str) -> None:
    print()
    print(message)
    input("  Коли зробиш — натисни Enter тут у консолі: ")


STEPS = [
    (
        "01-landing",
        None,
    ),
    (
        "02-after-login",
        "1) Якщо видно «Триває перевірка безпеки» — зачекай, поки вона мине.\n"
        "   Потім увійди в nz.ua під своїм акаунтом.\n"
        "   Якщо профіль уже пам'ятає вхід — просто переконайся, що ти всередині.",
    ),
    (
        "03-journal-9a-physics",
        "2) Перейди до журналу: Фізика, 9-А.\n"
        "   Зупинись на сторінці, де видно таблицю з оцінками\n"
        "   і кнопку «Додати стовпчик».",
    ),
    (
        "04-add-column-dialog",
        "3) Натисни «Додати стовпчик», щоб відкрився діалог.\n"
        "   Нічого не заповнюй і не зберігай.",
    ),
    (
        "05-journal-list",
        "4) Закрий діалог без збереження і відкрий сторінку «Журнали».\n"
        "   Списки в діалозі розкривати не треба: це звичайні <select>,\n"
        "   і їхній вміст уже потрапив у дамп разом із діалогом.",
    ),
]


def run_recon(page: Page) -> None:
    """Walk the operator through the flow, dumping each screen along the way."""
    RECON_DIR.mkdir(exist_ok=True)

    page.goto(BASE_URL, wait_until="domcontentloaded")

    for label, prompt in STEPS:
        if prompt is not None:
            _pause(prompt)
        if label.startswith("02"):
            ensure_logged_in(page)
        capture(page, label)

    print()
    print(f"Готово. Дампи у теці: {RECON_DIR}")
    print("Вхід лишається у профілі браузера — наступні запуски його підхоплять.")
    print("Тепер я прочитаю дампи і напишу селектори.")
