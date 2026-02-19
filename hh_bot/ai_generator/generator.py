"""AI Cover Letter Generator using OpenRouter API."""
from __future__ import annotations

import json
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None  # type: ignore

from hh_bot.ai_generator.models import AIGeneratorConfig, AIModel
from hh_bot.scraper.resume_parser import ResumeInfo
from hh_bot.scraper.vacancy import VacancyDetails
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

# OpenRouter API endpoint
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default system prompt for cover letter generation
DEFAULT_SYSTEM_PROMPT = """Ты — эксперт по написанию сопроводительных писем для отклика на вакансии.
Твоя задача — написать краткое, профессиональное и убедительное сопроводительное письмо на русском языке.

Правила:
1. Письмо должно быть персонализированным — учитывай навыки кандидата и требования вакансии
2. Максимум 200-300 слов (3-4 абзаца)
3. Профессиональный, но дружелюбный тон
4. Покажи, почему кандидат подходит именно на эту вакансию
5. Упомяни 2-3 ключевых навыка из резюме, которые релевантны вакансии
6. Закончи призывом к действию (готовность на собеседование)

Письмо должно быть готово к отправке — без шаблонных фраз вроде "[Вставить имя]"."""


async def generate_ai_cover_letter(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
    config: Optional[AIGeneratorConfig] = None,
) -> Optional[str]:
    """
    Generate a cover letter using AI via OpenRouter API.
    
    Args:
        resume: Parsed resume information
        vacancy: Vacancy details
        vacancy_description: Full vacancy description (optional)
        config: AI generator configuration
        
    Returns:
        Generated cover letter text or None if generation failed
    """
    log.info("=== GENERATE_AI_COVER_LETTER DEBUG ===")
    
    if config is None:
        config = AIGeneratorConfig()
    
    log.info(f"config.enabled: {config.enabled}")
    log.info(f"config.model: {config.model}")
    log.info(f"HAS_HTTPX: {HAS_HTTPX}")
    
    if not config.enabled:
        log.warning("❌ AI cover letter generation disabled in config")
        return None
    
    if not HAS_HTTPX:
        log.warning("❌ httpx not installed, cannot use AI generation. Install with: pip install httpx")
        return None
    
    log.info("✅ AI generation prerequisites OK, proceeding...")
    
    try:
        # Build prompt
        system_prompt = config.custom_prompt or DEFAULT_SYSTEM_PROMPT
        user_prompt = _build_user_prompt(resume, vacancy, vacancy_description)
        
        # Prepare API request
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/hh-autop",  # Required by OpenRouter
            "X-Title": "HH Auto-Apply Bot",
        }
        
        # Add API key if provided (for non-free models or higher rate limits)
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        
        log.info(
            "Generating AI cover letter",
            model=config.model,
            vacancy=vacancy.title[:50],
        )
        
        log.info(f"Sending request to OpenRouter... URL: {OPENROUTER_URL}")
        log.info(f"Headers: { {k: '***' if k == 'Authorization' else v for k, v in headers.items()} }")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            
            log.info(f"Response status: {response.status_code}")
            
            if response.status_code == 429:
                log.warning("Rate limit hit (429), retrying with fallback model...")
                # Try with a different free model
                payload["model"] = AIModel.MISTRAL_7B_FREE
                response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
                log.info(f"Retry response status: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            
            log.info(f"Response data keys: {list(data.keys())}")
            
            # Extract generated text
            if "choices" in data and len(data["choices"]) > 0:
                cover_letter = data["choices"][0]["message"]["content"].strip()
                log.info(f"✅ AI cover letter generated successfully: {len(cover_letter)} chars")
                return _clean_cover_letter(cover_letter)
            else:
                log.error(f"❌ Unexpected API response format: {data}")
                return None
                
    except httpx.HTTPStatusError as e:
        log.error(
            f"❌ API request failed: HTTP {e.response.status_code}",
            body=e.response.text[:500],
        )
        return None
    except Exception as e:
        log.error(f"❌ Failed to generate AI cover letter: {type(e).__name__}: {e}")
        import traceback
        log.error(f"Traceback: {traceback.format_exc()}")
        return None


def _build_user_prompt(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
) -> str:
    """Build user prompt for AI."""
    parts = [
        "# ДАННЫЕ КАНДИДАТА",
        f"## Желаемая позиция:\n{resume.title or 'Не указана'}"
    ]
    
    if resume.about:
        parts.append(f"## О себе:\n{resume.about}")
    
    if resume.skills:
        parts.append(f"## Ключевые навыки:\n{resume.skills}")
    
    if resume.experience:
        exp_short = resume.experience[:500] + "..." if len(resume.experience) > 500 else resume.experience
        parts.append(f"## Опыт работы:\n{exp_short}")
    
    parts.extend([
        "",
        "# ВАКАНСИЯ",
        f"## Название:\n{vacancy.title}",
        f"## Компания:\n{vacancy.employer}",
    ])
    
    if vacancy_description:
        desc_short = vacancy_description[:800] + "..." if len(vacancy_description) > 800 else vacancy_description
        parts.append(f"## Описание:\n{desc_short}")
    
    parts.extend([
        "",
        "# ЗАДАЧА",
        "Напиши сопроводительное письмо для отклика на эту вакансию.",
        "Письмо должно быть на русском языке.",
    ])
    
    return "\n\n".join(parts)


def _clean_cover_letter(text: str) -> str:
    """Clean up generated cover letter."""
    # Remove common AI artifacts
    text = text.replace("```", "").replace("```text", "")
    
    # Remove "Subject:" or "Re:" lines if present
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("subject:") or lower.startswith("re:"):
            continue
        cleaned_lines.append(line)
    
    text = "\n".join(cleaned_lines).strip()
    
    # Ensure proper greeting if missing
    if not any(text.lower().startswith(g) for g in ["добрый", "здравствуйте", "уважаемый"]):
        text = f"Добрый день!\n\n{text}"
    
    return text


def generate_fallback_cover_letter(
    resume: ResumeInfo,
    vacancy_title: str,
    company_name: str,
) -> str:
    """Generate a simple fallback cover letter without AI."""
    parts = ["Добрый день!"]
    
    if resume.title:
        parts.append(f"\nМеня заинтересовала вакансия {vacancy_title} в компании {company_name}.")
        parts.append(f"Моя текущая позиция: {resume.title}.")
    else:
        parts.append(f"\nМеня заинтересовала вакансия {vacancy_title} в компании {company_name}.")
    
    if resume.skills:
        skills_parts = resume.skills.replace(",", "•").replace(";", "•").split("•")
        skills_list = [s.strip() for s in skills_parts[:4] if s.strip()]
        if skills_list:
            parts.append(f"\nМои ключевые навыки: {', '.join(skills_list)}.")
    
    if resume.about:
        about_short = resume.about[:120] + "..." if len(resume.about) > 120 else resume.about
        parts.append(f"\n{about_short}")
    
    parts.append("\nГотов обсудить детали и ответить на ваши вопросы.")
    parts.append("\nС уважением")
    
    return "\n".join(parts)
