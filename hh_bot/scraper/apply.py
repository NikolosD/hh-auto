from __future__ import annotations

import asyncio
from typing import Optional

from patchright.async_api import Page, TimeoutError as PatchrightTimeout

from hh_bot.browser.human import (
    human_click_locator,
    human_type_locator,
    random_micro_move,
)
from hh_bot.scraper.vacancy import VacancyDetails
from hh_bot.scraper.resume_parser import ResumeInfo, generate_cover_letter
from hh_bot.utils.config import get_config
from hh_bot.utils.delays import sleep_after_submit, sleep_micro, sleep_page_load, uniform_delay
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


class ApplyError(Exception):
    pass


async def apply_to_vacancy(
    page: Page,
    details: VacancyDetails,
    preferred_resume_title: str = "",
    resume_info: Optional[ResumeInfo] = None,
) -> bool:
    """
    Attempt to apply to a vacancy.
    Returns True on success, False if skipped/failed gracefully.
    Raises ApplyError on unrecoverable error.
    """
    # Find the apply button
    apply_btn = page.locator(
        "[data-qa='vacancy-response-link-top'], "
        "[data-qa='vacancy-response-link-bottom']"
    ).first

    if await apply_btn.count() == 0:
        log.warning("Apply button not found", vacancy_id=details.vacancy_id)
        return False

    btn_text = (await apply_btn.inner_text()).strip().lower()
    log.info("Clicking apply button", text=btn_text)

    await human_click_locator(page, apply_btn)
    await sleep_after_submit()

    # Check for location warning modal first
    await _handle_location_warning_modal(page)
    
    # Check for photo suggestion modal
    await _handle_photo_suggestion_modal(page)
    
    # Check if a response modal appeared
    modal = page.locator(
        "[data-qa='vacancy-response-popup'], "
        ".vacancy-response-popup, "
        "[class*='response-popup'], "
        "[class*='modal'][class*='response']"
    )

    # Wait briefly for modal
    try:
        await modal.first.wait_for(state="visible", timeout=5000)
        log.info("Response modal appeared")
        return await _handle_response_modal(page, details, preferred_resume_title, resume_info)
    except PatchrightTimeout:
        pass

    # No modal — check if we were redirected to a success page or inline form
    await sleep_page_load()
    current_url = page.url

    if "negotiations" in current_url or "response" in current_url:
        log.info("Redirect to negotiations/response page after apply")
        return await _handle_response_page(page, details, preferred_resume_title, resume_info)

    # Check if success message appeared inline
    success = page.locator(
        "[data-qa='vacancy-response-success'], "
        "span:text('Отклик отправлен'), "
        "span:text('Вы откликнулись')"
    )
    if await success.count() > 0:
        log.info("Apply successful (inline confirmation)", vacancy_id=details.vacancy_id)
        return True

    log.warning("Could not confirm apply result", url=current_url)
    return False


async def _handle_photo_suggestion_modal(page: Page) -> bool:
    """
    Handle 'Add photo?' suggestion modal.
    Returns True if modal was handled, False if not found.
    """
    try:
        # Check for photo suggestion modal
        modal_text = page.locator("text=Добавим фото?").first
        await modal_text.wait_for(state="visible", timeout=2000)
        log.info("Photo suggestion modal detected")
    except PatchrightTimeout:
        return False
    
    # Click "Save and continue" or close button
    continue_btn = page.locator(
        "button:has-text('Сохранить и продолжить'), "
        "button:has-text('Save and continue'), "
        "[data-qa='photo-upload-submit'], "
        "[aria-label='Закрыть'], "
        "[aria-label='Close']"
    ).first
    
    if await continue_btn.count() > 0:
        log.info("Closing photo suggestion modal")
        await human_click_locator(page, continue_btn)
        await sleep_micro()
        return True
    else:
        # Try pressing Escape key
        log.info("Pressing Escape to close photo modal")
        await page.keyboard.press('Escape')
        await sleep_micro()
        return True


async def _handle_location_warning_modal(page: Page) -> bool:
    """
    Handle 'You are applying in a different country' warning modal.
    Returns True if modal was handled, False if not found.
    """
    # Check for location warning modal by text content
    try:
        # Look for the modal with specific text
        modal_text = page.locator("text=Вы откликаетесь на вакансию в другой стране").first
        await modal_text.wait_for(state="visible", timeout=2000)
        log.info("Location warning modal detected (different country)")
    except PatchrightTimeout:
        try:
            # Try English version
            modal_text = page.locator("text=applying for a job in another country").first
            await modal_text.wait_for(state="visible", timeout=2000)
            log.info("Location warning modal detected (different country - EN)")
        except PatchrightTimeout:
            return False
    
    # Click "Все равно откликнуться" / "Apply anyway" button
    continue_btn = page.locator(
        "button:has-text('Все равно откликнуться'), "
        "button:has-text('Apply anyway'), "
        "button:has-text('Продолжить'), "
        "button:has-text('Continue'), "
        "[data-qa='relocations-warning-popup-submit'], "
        "[data-qa='vacancy-response-relocation-submit']"
    ).first
    
    if await continue_btn.count() > 0:
        log.info("Clicking 'Continue' on location warning modal")
        await human_click_locator(page, continue_btn)
        await sleep_micro()
        return True
    else:
        log.warning("Location warning modal found but no continue button")
        return False


async def _handle_response_modal(
    page: Page,
    details: VacancyDetails,
    preferred_resume_title: str,
    resume_info: Optional[ResumeInfo] = None,
) -> bool:
    """Handle the apply modal dialog."""
    # First check for location warning modal
    await _handle_location_warning_modal(page)
    
    # Check for photo suggestion modal
    await _handle_photo_suggestion_modal(page)
    
    # Select resume if multiple are shown
    await _select_resume(page, preferred_resume_title)

    # Handle cover letter
    await _fill_cover_letter(page, details, resume_info)

    # Find and click submit button
    submit_btn = page.locator(
        "[data-qa='vacancy-response-submit-popup'], "
        "[data-qa='vacancy-response-popup-submit'], "
        "button[type='submit']"
    ).first

    if await submit_btn.count() == 0:
        raise ApplyError("Submit button not found in modal")

    await random_micro_move(page, count=1)
    await human_click_locator(page, submit_btn)
    await sleep_after_submit()

    # Verify success
    success_indicators = [
        "[data-qa='vacancy-response-success']",
        "span:text('Отклик отправлен')",
        "span:text('Вы откликнулись')",
        "[class*='response-success']",
    ]
    for sel in success_indicators:
        try:
            if await page.locator(sel).count() > 0:
                log.info("Apply successful (modal)", vacancy_id=details.vacancy_id)
                return True
        except Exception:
            pass

    # Modal may have closed — treat as success if no error visible
    error_el = page.locator("[data-qa='error-message'], .error-message")
    if await error_el.count() > 0:
        err_text = await error_el.first.inner_text()
        raise ApplyError(f"Apply error in modal: {err_text}")

    log.info("Apply submitted (modal closed, assumed success)", vacancy_id=details.vacancy_id)
    return True


async def _handle_response_page(
    page: Page,
    details: VacancyDetails,
    preferred_resume_title: str,
    resume_info: Optional[ResumeInfo] = None,
) -> bool:
    """Handle full-page response form."""
    # Check for location warning on page too
    await _handle_location_warning_modal(page)
    
    await _select_resume(page, preferred_resume_title)
    await _fill_cover_letter(page, details, resume_info)

    submit_btn = page.locator("button[type='submit'], [data-qa='response-submit']").first
    if await submit_btn.count() == 0:
        raise ApplyError("Submit button not found on response page")

    await human_click_locator(page, submit_btn)
    await sleep_after_submit()
    log.info("Apply submitted (response page)", vacancy_id=details.vacancy_id)
    return True


async def _select_resume(page: Page, preferred_title: str) -> None:
    """Select the preferred resume from the list in the modal/form."""
    resume_items = page.locator(
        "[data-qa='resume-in-popup'], "
        "[class*='resume-item'], "
        "label[class*='resume']"
    )
    count = await resume_items.count()
    if count == 0:
        return  # Only one resume or no selection needed

    log.debug("Selecting resume", count=count, preferred=preferred_title)

    if preferred_title:
        for i in range(count):
            item = resume_items.nth(i)
            text = await item.inner_text()
            if preferred_title.lower() in text.lower():
                await human_click_locator(page, item)
                await sleep_micro()
                log.debug("Selected resume by title", title=preferred_title)
                return

    # Fallback: select first resume
    await human_click_locator(page, resume_items.first)
    await sleep_micro()
    log.debug("Selected first resume")


async def _fill_cover_letter(page: Page, details: VacancyDetails, resume_info: Optional[ResumeInfo] = None) -> None:
    """Fill in cover letter if enabled and field is present."""
    cfg = get_config()
    cl_cfg = cfg.cover_letter

    letter_area_loc = page.locator(
        "[data-qa='vacancy-response-letter-text'], "
        "textarea[name='text'], "
        "textarea[placeholder*='письм']"
    )

    if await letter_area_loc.count() == 0:
        return  # No letter field present

    if not cl_cfg.enabled:
        log.debug("Cover letter disabled, skipping")
        return

    # Generate personalized cover letter if resume info available
    if resume_info and resume_info.title:
        text = generate_cover_letter(resume_info, details.title, details.employer)
        log.info("Generated personalized cover letter from resume")
    else:
        # Use template from config
        text = cl_cfg.template.format(
            vacancy_name=details.title,
            company_name=details.employer,
        )

    letter_area = letter_area_loc.first
    log.info("Filling cover letter", chars=len(text))
    await human_type_locator(page, letter_area, text)
    await sleep_micro()
