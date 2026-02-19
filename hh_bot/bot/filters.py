from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hh_bot.bot.state import StateDB
from hh_bot.scraper.search import VacancyCard
from hh_bot.scraper.vacancy import VacancyDetails
from hh_bot.utils.config import get_config
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class FilterResult:
    skip: bool
    reason: str = ""


def quick_filter(card: VacancyCard, db: StateDB) -> FilterResult:
    """
    Fast pre-filters applied before opening the vacancy page.
    These only use data available from the search results card.
    """
    cfg = get_config()

    # Already seen (applied or skipped)
    if db.has_seen(card.vacancy_id):
        return FilterResult(skip=True, reason="already_seen")

    # Stop-word in title
    title_lower = card.title.lower()
    for kw in cfg.filters.blocked_keywords:
        if kw.lower() in title_lower:
            return FilterResult(skip=True, reason=f"blocked_keyword:{kw}")

    # Blocked employer
    employer_lower = card.employer.lower()
    for emp in cfg.filters.blocked_employers:
        if emp.lower() in employer_lower:
            return FilterResult(skip=True, reason=f"blocked_employer:{emp}")

    return FilterResult(skip=False)


def deep_filter(details: VacancyDetails) -> FilterResult:
    """
    Filters applied after opening the vacancy page.
    These use detailed vacancy information.
    """
    cfg = get_config()

    # Already applied
    if details.already_applied:
        return FilterResult(skip=True, reason="already_applied")

    # Archived/closed
    if details.archived:
        return FilterResult(skip=True, reason="archived")

    # External link
    if details.is_external and cfg.filters.skip_direct_vacancies:
        return FilterResult(skip=True, reason="external_link")

    # Has test
    if details.has_test and cfg.filters.skip_with_tests:
        return FilterResult(skip=True, reason="has_test")

    # Cover letter required but no template
    if details.response_letter_required:
        if not cfg.cover_letter.enabled or not cfg.cover_letter.template.strip():
            return FilterResult(skip=True, reason="letter_required_no_template")

    return FilterResult(skip=False)
