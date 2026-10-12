"""Browser lifecycle: how the automation reaches a browser nz.ua will serve.

nz.ua sits behind Cloudflare. Measured on the live site:

* `launch` — Chrome started by Playwright, even the real Chrome binary on a
  persistent profile with the automation switches stripped — is blocked. The
  page stays on "Триває перевірка безпеки" and escalates to an interactive
  "Підтвердьте, що ви людина" challenge.
* `attach` — an ordinary Chrome we start as a plain subprocess, which
  Playwright then connects to over the debugging port — is served normally.

So `attach` is the default. `launch` is kept only to re-check that verdict
when the site changes.

Both modes keep their own user data directory, so the Cloudflare cookie and
the nz.ua login survive between runs.
"""

from __future__ import annotations

import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

BASE_URL = "https://nz.ua"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = PROJECT_ROOT / ".browser-profile"
CDP_PROFILE_DIR = PROJECT_ROOT / ".browser-profile-cdp"
CDP_PORT = 9222
CDP_ENDPOINT = f"http://localhost:{CDP_PORT}"

# Chrome refuses --remote-debugging-port on its default profile, so the
# attach flow needs a user data directory of its own.
CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
]

# Chrome ships these on by default under automation; the bot check reads them.
_AUTOMATION_ARGS = ["--enable-automation", "--disable-extensions"]
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
]


def chrome_executable() -> Path:
    """Locate the installed Chrome, or say plainly that it is missing."""
    for candidate in CHROME_PATHS:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "Не знайшов chrome.exe у типових місцях. "
        "Встанови Google Chrome або пропиши шлях у browser.CHROME_PATHS."
    )


def start_chrome_for_attach() -> subprocess.Popen:
    """Start Chrome ourselves with debugging on, but with no automation flags.

    The bot check inspects the browser process, so this is a plain Chrome that
    merely happens to have a debugging port open: nothing marks it as driven.
    """
    CDP_PROFILE_DIR.mkdir(exist_ok=True)
    return subprocess.Popen(
        [
            str(chrome_executable()),
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CDP_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            BASE_URL,
        ]
    )


def wait_for_cdp(timeout: float = 60.0) -> bool:
    """Poll the debugging port until Chrome answers, or give up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _first_page(context: BrowserContext) -> Page:
    page = context.pages[0] if context.pages else context.new_page()
    page.bring_to_front()
    return page


@contextmanager
def launch(slow_mo: int = 0, channel: str = "chrome") -> Iterator[Page]:
    """Start Chrome on our own persistent profile and yield its page."""
    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel=channel,
            headless=False,
            slow_mo=slow_mo,
            args=_LAUNCH_ARGS,
            ignore_default_args=_AUTOMATION_ARGS,
            no_viewport=True,
            locale="uk-UA",
            timezone_id="Europe/Kyiv",
        )
        context.set_default_timeout(60_000)
        try:
            yield _first_page(context)
        finally:
            context.close()


@contextmanager
def attach(
    endpoint: str = CDP_ENDPOINT, slow_mo: int = 0, autostart: bool = True
) -> Iterator[Page]:
    """Attach to a plain Chrome instead of driving a Playwright-launched one.

    Use this when the bot check refuses a launched browser. Chrome is started
    as an ordinary browser that merely has a debugging port open; Playwright
    only connects to it afterwards and never owns it.
    """
    if autostart and not wait_for_cdp(timeout=1.0):
        print("Запускаю Chrome із портом налагодження…")
        start_chrome_for_attach()
        if not wait_for_cdp():
            raise RuntimeError(
                f"Chrome не відповів на {endpoint} за хвилину. "
                "Спробуй закрити всі вікна Chrome і запустити команду ще раз."
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, slow_mo=slow_mo)
        if not browser.contexts:
            raise RuntimeError(
                f"Chrome на {endpoint} відповідає, але не має жодного вікна."
            )
        context = browser.contexts[0]
        context.set_default_timeout(60_000)

        # Work in a tab of our own: hijacking whichever tab happens to be open
        # would fight the user for it, and closing it at the end would shut
        # down a window they were using.
        page = context.new_page()
        try:
            page.bring_to_front()
            yield page
        finally:
            # Never close the browser here. Over CDP `browser.close()` shuts
            # Chrome down rather than merely disconnecting, which kills the
            # session — and with it the Cloudflare cookie that took a manual
            # check to earn. Leaving the scope disconnects on its own.
            if not page.is_closed():
                page.close()


CHALLENGE_MARKERS = ("перевірка безпеки", "підтвердьте, що ви людина")


def is_challenged(page: Page) -> bool:
    """Whether Cloudflare is holding the page on its interstitial."""
    try:
        body = page.inner_text("body").lower()
    except Exception:
        return False
    return any(marker in body for marker in CHALLENGE_MARKERS)


def wait_out_challenge(page: Page, timeout: float = 60.0) -> bool:
    """Sit through Cloudflare's check instead of hammering past it.

    Navigating in quick succession is what trips the check in the first place,
    so the answer is to wait rather than retry harder.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_challenged(page):
            return True
        page.wait_for_timeout(3_000)
    return not is_challenged(page)


def is_logged_in(page: Page) -> bool:
    """Whether the session still has a teacher behind it.

    Logged out, nz.ua does not redirect to a login form: /journal/list answers
    with its own error page, "Помилка (#8) — Trying to get property 'school'
    of non-object". So presence of the journals table is the honest test.
    """
    page.goto(BASE_URL + "/journal/list", wait_until="domcontentloaded")
    if is_challenged(page):
        wait_out_challenge(page)
    try:
        page.wait_for_selector("table.journal-choose", timeout=15_000)
        return True
    except Exception:
        return False


def ensure_logged_in(page: Page, ask: bool = True) -> None:
    """Stop with a clear instruction rather than a timeout deep in the run."""
    while not is_logged_in(page):
        if is_challenged(page):
            message = (
                "Cloudflare показує перевірку безпеки і вона не минає сама.\n"
                "У вікні Chrome пройди її (може знадобитись натиснути галочку)."
            )
        else:
            message = (
                "Сесія nz.ua не активна — сайт віддає «Помилка (#8)».\n"
                "У вікні Chrome, що відкрите, увійди в свій акаунт."
            )
        if not ask:
            raise RuntimeError(message)
        print()
        print(message)
        input("  Коли буде готово — натисни Enter тут у консолі: ")


@contextmanager
def open_browser(mode: str = "attach", slow_mo: int = 0) -> Iterator[Page]:
    """Open a page in the requested way: our own Chrome profile, or yours."""
    if mode == "attach":
        with attach(slow_mo=slow_mo) as page:
            yield page
    elif mode == "launch":
        with launch(slow_mo=slow_mo) as page:
            yield page
    elif mode == "edge":
        with launch(slow_mo=slow_mo, channel="msedge") as page:
            yield page
    else:
        raise ValueError(f"Невідомий режим браузера: {mode!r}")
