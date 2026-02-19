from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from patchright.async_api import Page

from hh_bot.utils.delays import sleep_page_load, sleep_micro
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class ResumeInfo:
    """Parsed resume information."""
    title: str
    about: str = ""
    experience: str = ""
    skills: str = ""
    full_text: str = ""


async def fetch_resume_content(page: Page, resume_url: Optional[str] = None) -> ResumeInfo:
    """
    Fetch resume content from hh.ru.
    If resume_url is not provided, navigates to /applicant/resumes and gets the first resume.
    """
    if resume_url:
        log.info("Opening resume", url=resume_url)
        await page.goto(resume_url, wait_until="domcontentloaded", timeout=20000)
        await sleep_page_load()
    else:
        # Navigate to resumes page and click first resume
        log.info("Fetching resumes list")
        await page.goto("https://hh.ru/applicant/resumes", wait_until="domcontentloaded", timeout=20000)
        await sleep_page_load()
        
        # Try to find and click first resume
        resume_link = page.locator(
            "a[href*='/resume/']"
        ).first
        
        if await resume_link.count() == 0:
            log.warning("No resumes found")
            return ResumeInfo(title="", full_text="")
        
        await resume_link.click()
        await sleep_page_load()
    
    # Extract resume information
    info = await _parse_resume_page(page)
    return info


async def _parse_resume_page(page: Page) -> ResumeInfo:
    """Parse resume page and extract key information."""
    
    # Scroll to load all content
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)
    
    # Get resume title
    title_el = page.locator(
        "[data-qa='resume-block-title-position']"
    ).first
    title = await title_el.inner_text() if await title_el.count() > 0 else ""
    
    # Get about/summary section - look for "О себе" section
    about = ""
    about_header = page.locator("text=О себе").first
    if await about_header.count() > 0:
        # Get parent and then the content
        parent = about_header.locator("xpath=../..")
        if await parent.count() > 0:
            about = await parent.inner_text()
            # Remove the "О себе" header from text
            about = about.replace("О себе", "", 1).strip()
    
    # Get skills - look for "Навыки" section  
    skills = ""
    skills_header = page.locator("text=Ключевые навыки").first
    if await skills_header.count() > 0:
        parent = skills_header.locator("xpath=../..")
        if await parent.count() > 0:
            skills = await parent.inner_text()
            skills = skills.replace("Ключевые навыки", "", 1).strip()
    
    # Get experience section
    experience = ""
    exp_header = page.locator("text=Опыт работы").first
    if await exp_header.count() > 0:
        parent = exp_header.locator("xpath=../..")
        if await parent.count() > 0:
            experience = await parent.inner_text()
    
    # Get full text (limited)
    full_text_parts = [title, about, skills]
    full_text = "\n\n".join(filter(None, full_text_parts))
    
    log.info("Parsed resume", title=title[:50], has_about=bool(about), has_skills=bool(skills))
    
    return ResumeInfo(
        title=title.strip(),
        about=about.strip(),
        experience=experience.strip(),
        skills=skills.strip(),
        full_text=full_text[:1000]  # Limit text length
    )


def generate_cover_letter(resume: ResumeInfo, vacancy_title: str, company_name: str) -> str:
    """
    Generate a personalized cover letter based on resume and vacancy info.
    """
    if not resume.title:
        # Fallback to simple template if no resume info
        return (
            f"Добрый день!\n\n"
            f"Меня заинтересовала вакансия {vacancy_title} в компании {company_name}. "
            f"Готов обсудить детали."
        )
    
    # Extract key skills for matching
    skills_list = []
    if resume.skills:
        # Take first 3-5 skills
        skills_parts = resume.skills.replace(",", "•").replace(";", "•").split("•")
        skills_list = [s.strip() for s in skills_parts[:5] if s.strip()]
    
    skills_text = ", ".join(skills_list) if skills_list else "своих навыках"
    
    # Build personalized letter
    letter_parts = [
        f"Добрый день!",
        "",
        f"Меня заинтересовала вакансия {vacancy_title} в компании {company_name}.",
    ]
    
    # Add about section if available
    if resume.about:
        about_short = resume.about[:150] + "..." if len(resume.about) > 150 else resume.about
        letter_parts.extend([
            "",
            f"{about_short}",
        ])
    
    # Add skills mention
    if skills_list:
        letter_parts.extend([
            "",
            f"Мои ключевые навыки: {skills_text}.",
        ])
    
    # Add position relevance
    if resume.title:
        letter_parts.extend([
            "",
            f"Моя текущая позиция: {resume.title}.",
        ])
    
    # Closing
    letter_parts.extend([
        "",
        "Готов обсудить детали и ответить на ваши вопросы.",
        "",
        "С уважением"
    ])
    
    return "\n".join(letter_parts)
