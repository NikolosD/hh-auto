from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from patchright.async_api import Page

from hh_bot.browser.human import human_scroll, random_micro_move
from hh_bot.utils.delays import sleep_page_load, sleep_micro
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class VacancyDetails:
    vacancy_id: str
    title: str
    employer: str
    url: str
    description: str = ""  # Описание вакансии для AI генерации
    has_test: bool = False
    response_letter_required: bool = False
    already_applied: bool = False
    is_external: bool = False
    archived: bool = False


async def fetch_vacancy_details(page: Page, url: str, vacancy_id: str) -> VacancyDetails:
    """Open a vacancy page and extract details needed for apply decision."""
    log.info("Opening vacancy", url=url)
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await sleep_page_load()

    # Scroll a bit to appear like reading
    await human_scroll(page, 200)
    await sleep_micro()
    await random_micro_move(page, count=1)

    title = await _get_title(page)
    employer = await _get_employer(page)
    description = await _get_description(page)
    has_test = await _check_has_test(page)
    letter_required = await _check_letter_required(page)
    already_applied = await _check_already_applied(page)
    is_external = await _check_is_external(page)
    archived = await _check_archived(page)

    details = VacancyDetails(
        vacancy_id=vacancy_id,
        title=title,
        employer=employer,
        url=url,
        description=description,
        has_test=has_test,
        response_letter_required=letter_required,
        already_applied=already_applied,
        is_external=is_external,
        archived=archived,
    )
    log.debug(
        "Vacancy details",
        id=vacancy_id,
        title=title,
        has_test=has_test,
        letter_required=letter_required,
        already_applied=already_applied,
        is_external=is_external,
    )
    return details


async def _get_title(page: Page) -> str:
    el = page.locator("[data-qa='vacancy-title'], h1")
    if await el.count() > 0:
        return (await el.first.inner_text()).strip()
    return ""


async def _get_employer(page: Page) -> str:
    el = page.locator("[data-qa='vacancy-company-name'], [data-qa='bloko-header-2']")
    if await el.count() > 0:
        return (await el.first.inner_text()).strip()
    return ""


async def _get_description(page: Page) -> str:
    """Extract vacancy description text."""
    # Try multiple selectors for description
    selectors = [
        "[data-qa='vacancy-description']",
        ".vacancy-description",
        "[data-qa='job-description']",
        "[class*='description']",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                # Clean up the text
                text = text.strip()
                # Limit length for AI prompt
                return text[:2000] if len(text) > 2000 else text
        except Exception:
            pass
    return ""


async def _check_has_test(page: Page) -> bool:
    """Detect if vacancy has a test assignment."""
    test_selectors = [
        "[data-qa='vacancy-test-required']",
        "[data-qa='test-required']",
        ".vacancy-test",
        "span:text('тест')",
        "span:text('Тест')",
        "div:text('тестовое задание')",
    ]
    for sel in test_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


async def _check_letter_required(page: Page) -> bool:
    """Detect if a cover letter is mandatory."""
    selectors = [
        "[data-qa='vacancy-response-letter-required']",
        "span:text('Сопроводительное письмо обязательно')",
    ]
    for sel in selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


async def _check_already_applied(page: Page) -> bool:
    """Detect if user already applied to this vacancy."""
    # Check for explicit indicators that we already applied
    already_applied_indicators = [
        "[data-qa='vacancy-response-link-already-applied']",
        "[data-qa='vacancy-response-link-view-topic']",  # Кнопка "Чат" - уже откликнулись
        "span:text('Вы уже откликнулись')",
        "span:text('Отклик отправлен')",
        "span:text('Резюме доставлено')",
        "text=Резюме доставлено",
        ".vacancy-response-status",
    ]
    for sel in already_applied_indicators:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass
    
    # Check if apply button exists and has "Откликнуться" text
    # If no such button found - likely already applied
    apply_button_selectors = [
        "[data-qa='vacancy-response-link-top']",
        "[data-qa='vacancy-response-link-bottom']",
        "button:has-text('Откликнуться')",
    ]
    
    for sel in apply_button_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                text = await loc.inner_text()
                # Если текст кнопки содержит "отклик" - можно откликнуться
                if 'отклик' in text.lower():
                    return False
                # Если текст "Чат", "Уже откликнулись" и т.д. - уже откликнулись
                if any(word in text.lower() for word in ['чат', 'уже', 'отправлен', 'доставлено']):
                    return True
        except Exception:
            pass
    
    # If no apply button found at all - likely already applied
    return True


async def _check_is_external(page: Page) -> bool:
    """Detect if the apply button leads to an external site."""
    external_selectors = [
        "[data-qa='vacancy-response-link-direct']",
        "a[data-qa='vacancy-response-link-top'][target='_blank']",
    ]
    for sel in external_selectors:
        try:
            el = page.locator(sel)
            if await el.count() > 0:
                href = await el.first.get_attribute("href") or ""
                if href and "hh.ru" not in href:
                    return True
        except Exception:
            pass
    return False


async def _check_archived(page: Page) -> bool:
    """Detect if the vacancy is archived/closed."""
    selectors = [
        "[data-qa='vacancy-archived']",
        "span:text('Вакансия архивирована')",
        "span:text('Вакансия закрыта')",
    ]
    for sel in selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False
