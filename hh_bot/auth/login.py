from __future__ import annotations

import asyncio

from patchright.async_api import Page, TimeoutError as PatchrightTimeout

from hh_bot.browser.human import human_click_locator, human_type_locator, random_micro_move
from hh_bot.utils.config import get_config
from hh_bot.utils.delays import sleep_page_load, sleep_after_submit, sleep_micro
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

LOGIN_URL = "https://hh.ru/account/login?role=applicant"
APPLICANT_URL = "https://hh.ru/applicant/resumes"


async def is_logged_in(page: Page) -> bool:
    """Check if the user is already logged in by looking for profile elements."""
    try:
        await page.goto("https://hh.ru/", wait_until="domcontentloaded", timeout=15000)
        await sleep_page_load()
        # Look for account menu or avatar that only appears when logged in
        avatar = page.locator("[data-qa='account-icon'], [data-qa='user-avatar'], .account-icon")
        if await avatar.count() > 0:
            log.info("Already logged in (found account icon)")
            return True
        
        # Navigate to applicant area and check for actual logged-in content
        # (not just URL, because hh.ru shows login form on the same URL)
        await page.goto(APPLICANT_URL, wait_until="domcontentloaded", timeout=15000)
        await sleep_page_load()
        
        # Check for login form - if present, user is NOT logged in
        login_form = page.locator(
            "[data-qa='account-login-form'], "
            "input[name='login'], "
            "input[placeholder*='почта'], "
            "input[placeholder*='email']"
        )
        if await login_form.count() > 0:
            log.info("Login form found - user is not logged in")
            return False
        
        # Check for resume content that only appears when logged in
        resume_content = page.locator(
            "[data-qa='resume'], "
            ".applicant-resumes, "
            "[data-qa='resumes-empty-state'], "
            ".resume-item"
        )
        if await resume_content.count() > 0:
            log.info("Already logged in (found resume content)")
            return True
            
    except Exception as e:
        log.debug("Login check error", error=str(e))
    return False


async def do_login_with_email(page: Page, email: str) -> None:
    """Perform full email login flow with provided email."""
    log.info("Starting login with provided email", email=email)
    
    log.info("Navigating to login page")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
    await sleep_page_load()

    # Step 1: Click "Войти" (Log in) button on the account type selection screen
    login_btn = page.locator("button:has-text('Войти')").first
    if await login_btn.count() > 0:
        log.info("Clicking 'Войти' button")
        await human_click_locator(page, login_btn)
        await sleep_page_load()

    # Step 2: Select "Почта" (Email) tab - click on the label text
    email_label = page.locator("text=Почта").first
    if await email_label.count() > 0:
        log.info("Clicking email tab")
        await human_click_locator(page, email_label)
        await sleep_micro()
    else:
        log.debug("Email tab not found, assuming already on email form")

    # Step 3: Fill in email field
    email_input = page.locator(
        "[data-qa='applicant-login-input-email'], "
        "[data-qa='login-input-username'], "
        "[data-qa='magritte-input-email'], "
        "input[type='email'], "
        "input[name='username'], "
        "input[name='login'], "
        "input[placeholder*='почта'], "
        "input[placeholder*='email']"
    ).first
    await email_input.wait_for(state="visible", timeout=10000)
    log.info("Typing email", email=email)
    await human_type_locator(page, email_input, email)
    await sleep_micro()

    # Step 4: Click "Continue" button ("Дальше")
    continue_btn = page.locator(
        "[data-qa='account-login-submit'], "
        "[data-qa='magritte-button-main-action'], "
        "button[type='submit'], "
        "button:has-text('Дальше'), "
        "button:has-text('Продолжить')"
    ).first
    await continue_btn.wait_for(state="visible", timeout=5000)
    await human_click_locator(page, continue_btn)
    await sleep_after_submit()

    # Step 5: Wait for OTP/code input field
    log.info("Waiting for verification code field...")
    code_input = page.locator(
        "[data-qa='account-login-code-input'], "
        "[data-qa='magritte-code-input'], "
        "input[name='code'], "
        "input[autocomplete='one-time-code'], "
        "input[maxlength='6'], "
        "input[placeholder*='код']"
    ).first
    try:
        await code_input.wait_for(state="visible", timeout=30000)
    except PatchrightTimeout:
        log.warning("Code input not found after 30s - check browser manually")
        raise RuntimeError("Verification code input did not appear. Check the browser window.")

    # Step 6: Prompt user for code
    print("\n" + "=" * 50)
    code = input("Enter code from email: ").strip()
    print("=" * 50 + "\n")

    if not code:
        raise RuntimeError("No verification code entered.")

    log.info("Typing verification code")
    await human_type_locator(page, code_input, code)
    await sleep_micro()

    # Step 7: Submit code
    submit_btn = page.locator(
        "[data-qa='account-login-code-submit'], "
        "[data-qa='account-login-submit'], "
        "button[type='submit'], "
        "button:has-text('Подтвердить'), "
        "button:has-text('Войти')"
    ).first
    if await submit_btn.count() > 0:
        await human_click_locator(page, submit_btn)

    log.info("Waiting for redirect after login...")
    try:
        await page.wait_for_url("**/applicant/**", timeout=30000)
        log.info("Login successful", url=page.url)
    except PatchrightTimeout:
        # Some flows redirect to homepage
        current = page.url
        if "hh.ru" in current and "login" not in current:
            log.info("Login appears successful", url=current)
        else:
            raise RuntimeError(f"Login redirect did not happen. Current URL: {current}")


async def do_login(page: Page) -> None:
    """Perform full email login flow with manual code entry (uses config email)."""
    cfg = get_config()
    email = cfg.auth.email
    if not email:
        email = input("Enter your hh.ru email: ").strip()
    
    await do_login_with_email(page, email)

    log.info("Navigating to login page")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
    await sleep_page_load()

    # Step 1: Click "Войти" (Log in) button on the account type selection screen
    login_btn = page.locator("button:has-text('Войти')").first
    if await login_btn.count() > 0:
        log.info("Clicking 'Войти' button")
        await human_click_locator(page, login_btn)
        await sleep_page_load()

    # Step 2: Select "Почта" (Email) tab - click on the label text
    email_label = page.locator("text=Почта").first
    if await email_label.count() > 0:
        log.info("Clicking email tab")
        await human_click_locator(page, email_label)
        await sleep_micro()
    else:
        log.debug("Email tab not found, assuming already on email form")

    # Step 3: Fill in email field
    email_input = page.locator(
        "[data-qa='applicant-login-input-email'], "
        "[data-qa='login-input-username'], "
        "[data-qa='magritte-input-email'], "
        "input[type='email'], "
        "input[name='username'], "
        "input[name='login'], "
        "input[placeholder*='почта'], "
        "input[placeholder*='email']"
    ).first
    await email_input.wait_for(state="visible", timeout=10000)
    log.info("Typing email", email=email)
    await human_type_locator(page, email_input, email)
    await sleep_micro()

    # Step 4: Click "Continue" button ("Дальше")
    continue_btn = page.locator(
        "[data-qa='account-login-submit'], "
        "[data-qa='magritte-button-main-action'], "
        "button[type='submit'], "
        "button:has-text('Дальше'), "
        "button:has-text('Продолжить')"
    ).first
    await continue_btn.wait_for(state="visible", timeout=5000)
    await human_click_locator(page, continue_btn)
    await sleep_after_submit()

    # Step 5: Wait for OTP/code input field
    log.info("Waiting for verification code field...")
    code_input = page.locator(
        "[data-qa='account-login-code-input'], "
        "[data-qa='magritte-code-input'], "
        "input[name='code'], "
        "input[autocomplete='one-time-code'], "
        "input[maxlength='6'], "
        "input[placeholder*='код']"
    ).first
    try:
        await code_input.wait_for(state="visible", timeout=30000)
    except PatchrightTimeout:
        log.warning("Code input not found after 30s - check browser manually")
        raise RuntimeError("Verification code input did not appear. Check the browser window.")

    # Step 6: Prompt user for code
    print("\n" + "=" * 50)
    code = input("Enter code from email: ").strip()
    print("=" * 50 + "\n")

    if not code:
        raise RuntimeError("No verification code entered.")

    log.info("Typing verification code")
    await human_type_locator(page, code_input, code)
    await sleep_micro()

    # Step 7: Submit code
    submit_btn = page.locator(
        "[data-qa='account-login-code-submit'], "
        "[data-qa='account-login-submit'], "
        "button[type='submit'], "
        "button:has-text('Подтвердить'), "
        "button:has-text('Войти')"
    ).first
    if await submit_btn.count() > 0:
        await human_click_locator(page, submit_btn)

    log.info("Waiting for redirect after login...")
    try:
        await page.wait_for_url("**/applicant/**", timeout=30000)
        log.info("Login successful", url=page.url)
    except PatchrightTimeout:
        # Some flows redirect to homepage
        current = page.url
        if "hh.ru" in current and "login" not in current:
            log.info("Login appears successful", url=current)
        else:
            raise RuntimeError(f"Login redirect did not happen. Current URL: {current}")


async def ensure_logged_in(page: Page) -> None:
    """Check login state; perform login if needed."""
    if await is_logged_in(page):
        return
    log.info("Not logged in, starting login flow")
    await do_login(page)
