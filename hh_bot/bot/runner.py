from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from patchright.async_api import Page

from hh_bot.auth.login import ensure_logged_in
from hh_bot.bot.filters import deep_filter, quick_filter
from hh_bot.bot.state import StateDB
from hh_bot.browser.human import random_micro_move
from hh_bot.scraper.apply import apply_to_vacancy, ApplyError
from hh_bot.scraper.resume_parser import fetch_resume_content, ResumeInfo, bump_resume_if_available
from hh_bot.scraper.search import search_vacancies
from hh_bot.scraper.vacancy import fetch_vacancy_details
from hh_bot.utils.config import get_config
from hh_bot.utils.delays import (
    sleep_between_applications,
    sleep_coffee_break,
    sleep_micro,
    sleep_page_load,
)
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class SessionStats:
    applied: int = 0
    skipped: int = 0
    errors: int = 0
    skip_reasons: dict = field(default_factory=dict)


async def run_session(page: Page, query: str, db: StateDB) -> SessionStats:
    """Main bot session loop."""
    cfg = get_config()
    stats = SessionStats()
    max_apps = cfg.limits.max_applications_per_session
    preferred_resume = cfg.resume.preferred_title

    # 1. Ensure authenticated and fetch resume info
    await ensure_logged_in(page)
    
    # Fetch resume content for personalized cover letters
    resume_info: Optional[ResumeInfo] = None
    if cfg.cover_letter.enabled:
        log.info("Fetching resume content for personalized cover letters")
        try:
            resume_info = await fetch_resume_content(page)
            if resume_info.title:
                log.info("Resume loaded", title=resume_info.title[:50])
            else:
                log.warning("Could not parse resume, using default cover letter")
        except Exception as e:
            log.warning("Failed to fetch resume content", error=str(e))
    
    # Try to bump resume (move to top of search results)
    log.info("Attempting to bump resume...")
    try:
        bumped = await bump_resume_if_available(page)
        if bumped:
            log.info("Resume bumped to top of search results")
        else:
            log.info("Resume not bumped (may be on cooldown or already at top)")
    except Exception as e:
        log.warning("Failed to bump resume", error=str(e))

    # Determine which area IDs to use
    if cfg.search.area_ids:
        area_ids = cfg.search.area_ids
        area_desc = f"{len(area_ids)} countries: {area_ids}"
    else:
        area_ids = cfg.search.area_id
        area_desc = str(area_ids)
    
    log.info(
        "Starting session",
        query=query,
        areas=area_desc,
        max_pages=cfg.search.max_pages,
        max_apps=max_apps,
    )

    # 2. Iterate search pages
    for page_num in range(cfg.search.max_pages):
        if stats.applied >= max_apps:
            log.info("Reached max applications limit", limit=max_apps)
            break

        cards = await search_vacancies(page, query, area_ids, page_num)
        if not cards:
            log.info("No more vacancies found", page=page_num)
            break

        # 3. Process each card
        for card in cards:
            if stats.applied >= max_apps:
                break

            # Quick filter (no page open needed)
            qf = quick_filter(card, db)
            if qf.skip:
                log.debug("Quick-filtered", id=card.vacancy_id, reason=qf.reason)
                stats.skipped += 1
                stats.skip_reasons[qf.reason] = stats.skip_reasons.get(qf.reason, 0) + 1
                if qf.reason != "already_seen":
                    db.mark_skipped(
                        card.vacancy_id, card.title, card.employer, card.url, qf.reason
                    )
                continue

            # Open vacancy page
            try:
                details = await fetch_vacancy_details(page, card.url, card.vacancy_id)
            except Exception as e:
                log.warning("Failed to fetch vacancy details", id=card.vacancy_id, error=str(e))
                stats.errors += 1
                continue

            # Check if already applied (no apply button on page)
            if details.already_applied:
                log.info(
                    "Skipping - already applied",
                    id=card.vacancy_id,
                    title=details.title,
                )
                stats.skipped += 1
                stats.skip_reasons["already_applied"] = stats.skip_reasons.get("already_applied", 0) + 1
                db.mark_skipped(
                    card.vacancy_id, details.title, details.employer, card.url, "already_applied"
                )
                continue

            # Deep filter (after page open)
            df = deep_filter(details)
            if df.skip:
                log.info(
                    "Deep-filtered",
                    id=card.vacancy_id,
                    title=details.title,
                    reason=df.reason,
                )
                stats.skipped += 1
                stats.skip_reasons[df.reason] = stats.skip_reasons.get(df.reason, 0) + 1
                db.mark_skipped(
                    card.vacancy_id, details.title, details.employer, card.url, df.reason
                )
                continue

            # Apply
            try:
                log.info(
                    "Applying",
                    id=card.vacancy_id,
                    title=details.title,
                    employer=details.employer,
                )
                success = await apply_to_vacancy(page, details, preferred_resume, resume_info)
            except ApplyError as e:
                log.error("Apply error", id=card.vacancy_id, error=str(e))
                stats.errors += 1
                continue
            except Exception as e:
                log.error("Unexpected apply error", id=card.vacancy_id, error=str(e))
                stats.errors += 1
                continue

            if success:
                db.mark_applied(card.vacancy_id, details.title, details.employer, card.url)
                stats.applied += 1

                # Coffee break every 5 applications
                if stats.applied % 5 == 0:
                    log.info("Taking coffee break", applied_so_far=stats.applied)
                    await sleep_coffee_break()
                else:
                    await sleep_between_applications(
                        cfg.limits.min_delay_between_applications,
                        cfg.limits.max_delay_between_applications,
                    )

                # Random micro-movements between applications
                await random_micro_move(page, count=2)
            else:
                stats.skipped += 1
                stats.skip_reasons["apply_failed"] = stats.skip_reasons.get("apply_failed", 0) + 1

        # Brief pause between pages
        await asyncio.sleep(2.0)

    log.info(
        "Session complete",
        applied=stats.applied,
        skipped=stats.skipped,
        errors=stats.errors,
        reasons=stats.skip_reasons,
    )
    return stats
