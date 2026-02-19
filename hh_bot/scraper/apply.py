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
    log.info(f"=== APPLY DEBUG === vacancy_id={details.vacancy_id}")
    log.info(f"resume_info: {resume_info}")
    log.info(f"resume_info.title: {resume_info.title if resume_info else 'None'}")
    
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
    location_handled = await _handle_location_warning_modal(page)
    if location_handled:
        log.info("Location warning was handled, waiting for form...")
        await asyncio.sleep(2)  # Даём время на появление формы
    
    # Check for photo suggestion modal
    await _handle_photo_suggestion_modal(page)
    
    # Check if a response modal appeared (with multiple possible selectors)
    modal_selectors = [
        "[data-qa='vacancy-response-popup']",
        "[data-qa='vacancy-response-popup-form']",
        ".vacancy-response-popup",
        "[class*='response-popup']",
        "[class*='modal'][class*='response']",
        "div[class*='bloko-modal']",  # Общий селектор модалок hh.ru
        "div[data-qa='bloko-modal']",
        "div:has-text('Отклик на вакансию'):above(form)",
    ]
    
    modal = None
    for selector in modal_selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                modal = loc
                log.info(f"Found response modal with selector: {selector}")
                break
        except Exception:
            pass
    
    if modal:
        try:
            await modal.wait_for(state="visible", timeout=3000)
            log.info("Response modal is visible, handling...")
            return await _handle_response_modal(page, details, preferred_resume_title, resume_info)
        except PatchrightTimeout:
            log.warning("Modal found but not visible after 3s")
    else:
        log.info("No response modal found with any selector")

    # No modal — check if we were redirected to a success page or inline form
    await sleep_page_load()
    current_url = page.url

    if "negotiations" in current_url or "response" in current_url:
        log.info("Redirect to negotiations/response page after apply")
        return await _handle_response_page(page, details, preferred_resume_title, resume_info)

    # Check if success message appeared inline
    success_indicators = [
        "[data-qa='vacancy-response-success']",
        "span:text-is('Отклик отправлен')",
        "span:text-is('Вы откликнулись')",
    ]
    
    for sel in success_indicators:
        try:
            if await page.locator(sel).count() > 0:
                log.info("Apply successful (inline confirmation)", vacancy_id=details.vacancy_id)
                # Try to add cover letter after quick apply
                if resume_info and resume_info.title:
                    log.info("Quick apply success - trying to add cover letter...")
                    await _add_cover_letter_after_quick_apply(page, details, resume_info)
                return True
        except Exception:
            pass

    # Check for quick-apply success (resume delivered) with cover letter form
    try:
        resume_delivered = page.locator("text=Резюме доставлено").first
        if await resume_delivered.count() > 0 and await resume_delivered.is_visible():
            log.info("Quick apply success (resume delivered)", vacancy_id=details.vacancy_id)
            # Try to add cover letter
            if resume_info and resume_info.title:
                await _add_cover_letter_after_quick_apply(page, details, resume_info)
            return True
    except Exception:
        pass

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
    log.info(f"=== HANDLE_RESPONSE_MODAL === resume_info={resume_info is not None}")
    
    # Check for employer questions/test form
    cfg = get_config()
    has_employer_questions = await page.locator(
        "[data-qa='employer-asking-for-test'], "
        "[data-qa='test-description'], "
        "input[name*='task_'], "
        "textarea[name*='task_']"
    ).count() > 0
    
    if has_employer_questions:
        if cfg.filters.skip_with_tests:
            log.info("Skipping vacancy with employer questions (test)", vacancy_id=details.vacancy_id)
            return False
        else:
            log.warning("Vacancy has employer questions but skip_with_tests is False", vacancy_id=details.vacancy_id)
    
    # First check for location warning modal
    await _handle_location_warning_modal(page)
    
    # Check for photo suggestion modal
    await _handle_photo_suggestion_modal(page)
    
    # Select resume if multiple are shown
    await _select_resume(page, preferred_resume_title)

    # Handle cover letter
    log.info("Calling _fill_cover_letter...")
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


async def _add_cover_letter_after_quick_apply(
    page: Page,
    details: VacancyDetails,
    resume_info: Optional[ResumeInfo] = None,
) -> bool:
    """
    Add cover letter after quick apply (when form appears on vacancy page).
    This handles the case when 'Откликнуться' button submits immediately 
    and shows a form for adding cover letter.
    """
    log.info("Checking for post-apply cover letter form...")
    
    # Check for the cover letter form that appears after quick apply
    letter_form = page.locator(
        "[data-qa='vacancy-response-letter-informer'], "
        "form:has([data-qa='vacancy-response-letter-submit'])"
    ).first
    
    if await letter_form.count() == 0:
        log.debug("No post-apply cover letter form found")
        return False
    
    if not await letter_form.is_visible():
        log.debug("Cover letter form is not visible")
        return False
    
    log.info("Found post-apply cover letter form, filling...")
    
    # Find textarea in the form
    textarea = letter_form.locator("textarea[name='text']").first
    if await textarea.count() == 0:
        textarea = letter_form.locator("textarea").first
    
    if await textarea.count() == 0:
        log.warning("No textarea found in cover letter form")
        return False
    
    # Generate and fill cover letter
    cfg = get_config()
    if not cfg.cover_letter.enabled:
        log.debug("Cover letter disabled, skipping")
        return False
    
    if resume_info and resume_info.title:
        text = await generate_cover_letter(
            resume_info, details.title, details.employer, details.description
        )
    else:
        text = cfg.cover_letter.template.format(
            vacancy_name=details.title,
            company_name=details.employer,
        )
    
    log.info(f"Filling post-apply cover letter ({len(text)} chars)...")
    await human_type_locator(page, textarea, text)
    await sleep_micro()
    
    # Submit the form
    submit_btn = letter_form.locator(
        "[data-qa='vacancy-response-letter-submit'], "
        "button[type='submit']"
    ).first
    
    if await submit_btn.count() > 0:
        log.info("Submitting cover letter...")
        await human_click_locator(page, submit_btn)
        await sleep_after_submit()
        log.info("Cover letter submitted successfully")
        return True
    else:
        log.warning("Submit button not found in cover letter form")
        return False


async def _handle_response_page(
    page: Page,
    details: VacancyDetails,
    preferred_resume_title: str,
    resume_info: Optional[ResumeInfo] = None,
) -> bool:
    """Handle full-page response form."""
    # Check for location warning on page too
    await _handle_location_warning_modal(page)
    
    # Check for post-apply cover letter form
    await _add_cover_letter_after_quick_apply(page, details, resume_info)
    
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
    
    log.info("=== COVER LETTER DEBUG ===")
    log.info(f"cover_letter.enabled: {cl_cfg.enabled}")
    log.info(f"cover_letter.ai.enabled: {cl_cfg.ai.enabled}")
    log.info(f"use_ai_cover_letter: {cfg.use_ai_cover_letter}")
    log.info(f"resume_info: {resume_info}")
    log.info(f"resume_info.title: {resume_info.title if resume_info else 'None'}")

    # Ищем поле для сопроводительного письма
    letter_area_loc = None
    
    # Сначала проверяем, есть ли признаки формы отклика (кнопка отправки письма)
    response_indicators = [
        "[data-qa='vacancy-response-letter-submit']",
        "[data-qa='vacancy-response-submit-popup']", 
        "button:has-text('Отправить')",
        "button:has-text('Откликнуться')",
    ]
    
    is_response_form = False
    for indicator in response_indicators:
        try:
            loc = page.locator(indicator).first
            if await loc.count() > 0 and await loc.is_visible():
                is_response_form = True
                log.info(f"Response form detected via: {indicator}")
                break
        except:
            pass
    
    # Если это форма отклика - ищем любой видимый textarea
    if is_response_form:
        log.info("Looking for textarea in response form...")
        all_textareas = page.locator("textarea")
        count = await all_textareas.count()
        log.info(f"Found {count} textarea(s) on page")
        
        for i in range(count):
            try:
                textarea = all_textareas.nth(i)
                if await textarea.is_visible():
                    letter_area_loc = textarea
                    log.info(f"Using visible textarea #{i}")
                    break
            except:
                continue
    
    # Если не нашли, ищем по стандартным селекторам
    if letter_area_loc is None:
        letter_selectors = [
            "[data-qa='vacancy-response-letter-text']",
            "textarea[data-qa='vacancy-response-letter-text']",
            "textarea[name='text']",
            "textarea[placeholder*='опроводительное']",
            "textarea[placeholder*='исьм']",
            "textarea[placeholder*='Письм']",
            "label:has-text('Сопроводительное письмо') ~ textarea",
            "label:has-text('опроводительное') ~ textarea",
        ]
        
        for selector in letter_selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    is_visible = await loc.is_visible()
                    if is_visible:
                        letter_area_loc = loc
                        log.info(f"Found letter field with selector: {selector}")
                        break
            except Exception as e:
                log.debug(f"Selector {selector} failed: {e}")
    
    # Если всё ещё не нашли, но есть кнопка отправки письма - ищем любой textarea
    if letter_area_loc is None:
        submit_btn = page.locator("[data-qa='vacancy-response-letter-submit']")
        if await submit_btn.count() > 0 and await submit_btn.is_visible():
            log.info("Found submit button, looking for any textarea...")
            # Ищем любой видимый textarea на странице
            all_textareas = page.locator("textarea")
            count = await all_textareas.count()
            for i in range(count):
                ta = all_textareas.nth(i)
                if await ta.is_visible():
                    letter_area_loc = ta
                    log.info(f"Using textarea #{i} as letter field")
                    break
    
    if letter_area_loc is None:
        letter_area_loc = page.locator("[data-qa='vacancy-response-letter-text']")
    
    field_count = await letter_area_loc.count()
    log.info(f"Found {field_count} letter field(s) on page")

    if field_count == 0:
        log.warning("❌ No cover letter field found on page - skipping")
        return  # No letter field present

    if not cl_cfg.enabled:
        log.warning("❌ Cover letter disabled in config - skipping")
        return

    # Generate personalized cover letter if resume info available
    log.info("Generating cover letter...")
    log.info(f"  has_resume: {bool(resume_info and resume_info.title)}")
    log.info(f"  use_ai: {cfg.use_ai_cover_letter}")
    
    if resume_info and resume_info.title:
        log.info(f"  resume.title: {resume_info.title}")
        log.info(f"  vacancy.title: {details.title}")
        log.info(f"  vacancy.employer: {details.employer}")
        log.info(f"  vacancy.description: {details.description[:100] if details.description else 'None'}...")
        
        text = await generate_cover_letter(resume_info, details.title, details.employer, details.description)
        log.info(f"✅ Generated cover letter: {len(text)} chars")
        log.info(f"   AI used: {cfg.use_ai_cover_letter}")
        log.info(f"   Preview: {text[:100]}...")
    else:
        # Use template from config
        log.warning("⚠️  No resume info, using template")
        text = cl_cfg.template.format(
            vacancy_name=details.title,
            company_name=details.employer,
        )
        log.info(f"Template letter: {len(text)} chars")

    letter_area = letter_area_loc.first
    log.info(f"Filling cover letter field with {len(text)} chars...")
    await human_type_locator(page, letter_area, text)
    await sleep_micro()
    log.info("✅ Cover letter filled successfully")
