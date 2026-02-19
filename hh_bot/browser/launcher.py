from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from patchright.async_api import async_playwright, BrowserContext, Page

from hh_bot.utils.config import get_config
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

_HOSTS_TO_RESOLVE = ["hh.ru", "hh.kz", "headhunter.ru"]


def _build_host_resolver_rules() -> str | None:
    rules = []
    for host in _HOSTS_TO_RESOLVE:
        try:
            ip = socket.gethostbyname(host)
            rules.append(f"MAP {host} {ip}")
            log.info("Pre-resolved host", host=host, ip=ip)
        except socket.gaierror:
            log.warning("Could not pre-resolve host", host=host)
    return ",".join(rules) if rules else None


async def _mask_webdriver(page: Page) -> None:
    """Mask navigator.webdriver property to avoid detection.
    
    Note: This must be called AFTER page.goto() not before, due to a bug
    where add_init_script causes ERR_NAME_NOT_RESOLVED errors on Windows.
    """
    await page.evaluate("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    """)


@asynccontextmanager
async def launch_browser() -> AsyncGenerator[tuple[BrowserContext, Page], None]:
    """Launch persistent Chrome browser context via Patchright."""
    cfg = get_config()
    profile_dir = Path(cfg.browser.profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    resolver_rules = _build_host_resolver_rules()
    
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if resolver_rules:
        args.append(f"--host-resolver-rules={resolver_rules}")

    log.info("Launching browser", profile=str(profile_dir), headless=cfg.browser.headless)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=cfg.browser.headless,
            args=args,
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Note: add_init_script is NOT used here due to a bug where it causes
        # ERR_NAME_NOT_RESOLVED on Windows. Instead, pages should call
        # await _mask_webdriver(page) after navigation.

        try:
            yield context, page
        finally:
            await context.close()
            log.info("Browser closed")
