from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlencode

from patchright.async_api import Page

from hh_bot.browser.human import human_scroll, random_micro_move
from hh_bot.utils.delays import sleep_page_load, sleep_micro, uniform_delay
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

SEARCH_BASE = "https://hh.ru/search/vacancy"


@dataclass
class VacancyCard:
    vacancy_id: str
    title: str
    employer: str
    url: str
    has_quick_response: bool = False


async def search_vacancies(
    page: Page,
    query: str,
    area_id: int | list[int] = 113,
    page_num: int = 0,
) -> List[VacancyCard]:
    """Navigate to search results page and parse vacancy cards.
    
    Args:
        area_id: Single area ID or list of area IDs for multiple countries
                 Common IDs: 113=Russia, 16=Belarus, 40=Kazakhstan, 
                 1=Moscow, 2=St.Petersburg
    """
    # Build params with support for multiple areas
    params_list = [
        ("text", query),
        ("page", page_num),
        ("per_page", 20),
        ("search_field", "name"),
    ]
    
    # Handle single or multiple area IDs
    if isinstance(area_id, list):
        for aid in area_id:
            params_list.append(("area", aid))
    else:
        params_list.append(("area", area_id))
    
    # Build URL manually to support multiple area params
    params_str = "&".join(f"{k}={v}" for k, v in params_list)
    url = f"{SEARCH_BASE}?{params_str}"
    
    log.info("Loading search page", url=url, page=page_num, areas=area_id)

    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await sleep_page_load()

    # Scroll to load lazy content
    await human_scroll(page, 300)
    await sleep_micro()
    await human_scroll(page, 300)
    await sleep_micro()

    cards = await _parse_vacancy_cards(page)
    log.info("Found vacancies on page", count=len(cards), page=page_num)
    return cards


async def _parse_vacancy_cards(page: Page) -> List[VacancyCard]:
    """Extract vacancy card data from the current search results page."""
    cards: List[VacancyCard] = []

    # Main vacancy card containers
    card_locators = page.locator("[data-qa='vacancy-serp__vacancy']")
    count = await card_locators.count()
    log.debug(f"Found {count} card containers")

    for i in range(count):
        card = card_locators.nth(i)
        try:
            vacancy = await _parse_single_card(card)
            if vacancy:
                cards.append(vacancy)
            else:
                log.debug(f"Card {i} returned None")
        except Exception as e:
            log.debug("Failed to parse card", index=i, error=str(e))

    return cards


async def _parse_single_card(card) -> Optional[VacancyCard]:
    """Parse a single vacancy card element."""
    try:
        # Get title and link
        title_el = card.locator("[data-qa='serp-item__title']")
        if await title_el.count() == 0:
            title_el = card.locator("a[data-qa*='vacancy']").first

        if await title_el.count() == 0:
            log.debug("No title element found in card")
            return None

        title = await title_el.inner_text()
        href = await title_el.get_attribute("href")

        if not href:
            log.debug("No href found in title element")
            return None
    except Exception as e:
        log.debug("Error parsing card title", error=str(e))
        return None

    # Strip query params first for ID extraction
    href_clean = href.split("?")[0]
    
    # Extract vacancy ID from URL
    # URL format: /vacancy/12345678 or https://hh.ru/vacancy/12345678
    vacancy_id = ""
    for part in href_clean.split("/"):
        if part.isdigit():
            vacancy_id = part
            break

    if not vacancy_id:
        log.debug(f"No vacancy_id found in href: {href_clean}")
        return None

    # Normalize URL
    if href_clean.startswith("/"):
        url = f"https://hh.ru{href_clean}"
    else:
        url = href_clean

    # Get employer name
    employer_el = card.locator("[data-qa='vacancy-serp__vacancy-employer']")
    employer = await employer_el.inner_text() if await employer_el.count() > 0 else ""
    employer = employer.strip()

    # Check for quick response button
    quick_btn = card.locator("[data-qa='vacancy-serp__vacancy_response']")
    has_quick = await quick_btn.count() > 0

    return VacancyCard(
        vacancy_id=vacancy_id,
        title=title.strip(),
        employer=employer,
        url=url,
        has_quick_response=has_quick,
    )


async def has_next_page(page: Page) -> bool:
    """Check if there is a next page of results."""
    next_btn = page.locator("[data-qa='pager-next']")
    return await next_btn.count() > 0
