"""AI Cover Letter Generator using Groq API (fast, free tier available)."""
from __future__ import annotations

from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None  # type: ignore

from hh_bot.ai_generator.models import AIGeneratorConfig
from hh_bot.scraper.resume_parser import ResumeInfo
from hh_bot.scraper.vacancy import VacancyDetails
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

# Groq API endpoint
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Default system prompt with STRICT length constraints and few-shot example
DEFAULT_SYSTEM_PROMPT = """Ты пишешь КОРОТКИЕ сопроводительные письма (макс 500 символов).

ПРИМЕР правильного письма (497 символов):
---
Добрый день!

Меня заинтересовала вакансия Frontend Developer в вашей компании. В вашем стеке React/TypeScript — это мои основные инструменты последние 3 года.

Работал с похожими задачами в EPAM: мигрировал легаси на React, внедрял accessibility. Уверен, что этот опыт поможет вашему продукту.

Готов обсудить детали на собеседовании.

Telegram: @username
С уважением,
Иван
---

ТВОИ ПРАВИЛА:
1. МАКСИМУМ 500 символов (строго!)
2. Ровно 4 абзаца: приветствие, опыт, релевантность, призыв
3. Каждый абзац: 1-2 коротких предложения
4. Никаких общих фраз типа "я ответственный"
5. Конкретика: технологии из вакансии + твой опыт

Если не умещаешься — удали лишнее, но уложись в 500 символов."""


async def generate_with_groq(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
    config: Optional[AIGeneratorConfig] = None,
) -> Optional[str]:
    """Generate cover letter using Groq API."""
    if not HAS_HTTPX:
        log.warning("❌ httpx not installed")
        return None
    
    if not config or not config.api_key:
        log.warning("❌ Groq API key not provided")
        return None
    
    try:
        from hh_bot.utils.config import get_config
        cfg = get_config()
        
        # Build prompt
        user_prompt = _build_groq_prompt(resume, vacancy, vacancy_description)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        }
        
        # Groq supported models (fast, cheap)
        models_to_try = [
            "llama-3.1-8b-instant",  # Fastest, cheapest
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
        ]
        
        for model in models_to_try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": config.custom_prompt or DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 300,  # Limit tokens to force short output
                "temperature": 0.5,  # Lower temperature for more focused output
            }
            
            log.info(f"Trying Groq model: {model}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GROQ_URL, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        cover_letter = data["choices"][0]["message"]["content"].strip()
                        log.info(f"✅ Groq generated: {len(cover_letter)} chars")
                        # Clean and HARD truncate to 700 chars max (to fit Telegram)
                        cover_letter = _clean_cover_letter(cover_letter)
                        cover_letter = _hard_truncate(cover_letter, max_chars=700)
                        # Ensure Telegram is in the letter
                        cover_letter = _ensure_contacts(cover_letter, cfg)
                        log.info(f"✅ After truncate: {len(cover_letter)} chars")
                        return cover_letter
                
                log.warning(f"Groq model {model} failed: {response.status_code}")
        
        return None
        
    except Exception as e:
        log.error(f"❌ Groq generation failed: {e}")
        return None


def _build_groq_prompt(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
) -> str:
    """Build prompt for Groq."""
    from hh_bot.utils.config import get_config
    cfg = get_config()
    
    parts = [
        "Напиши сопроводительное письмо для отклика на вакансию.",
        "",
        "# ДАННЫЕ КАНДИДАТА",
        f"Позиция: {resume.title or 'Не указана'}",
    ]
    
    if resume.about:
        # Clean about text
        about = resume.about.replace("О себе", "").strip()[:300]
        parts.append(f"О себе: {about}")
    
    if resume.skills:
        parts.append(f"Навыки: {resume.skills}")
    
    parts.extend([
        "",
        "# ВАКАНСИЯ",
        f"Название: {vacancy.title}",
        f"Компания: {vacancy.employer}",
    ])
    
    if vacancy_description:
        desc = vacancy_description[:500] if len(vacancy_description) > 500 else vacancy_description
        parts.append(f"Описание: {desc}")
    
    parts.extend([
        "",
        "# ТРЕБОВАНИЯ К ПИСЬМУ",
        "1. Начни с 'Добрый день!'",
        "2. Упомяни вакансию и компанию",
        "3. Свяжи свои навыки с требованиями вакансии",
        "4. Будь конкретным — укажи технологии из вакансии",
        "5. Максимум 4 абзаца",
        f"6. Telegram: @{cfg.auth.telegram}" if cfg.auth.telegram else "",
        f"7. Подпись: С уважением, {cfg.auth.name}" if cfg.auth.name else "7. Подпись: С уважением",
    ])
    
    return "\n".join(filter(None, parts))


def _clean_cover_letter(text: str) -> str:
    """Clean up generated cover letter."""
    text = text.replace("```", "").replace("```text", "")
    
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("subject:") or lower.startswith("re:"):
            continue
        cleaned_lines.append(line)
    
    text = "\n".join(cleaned_lines).strip()
    
    # Ensure proper greeting
    if not any(text.lower().startswith(g) for g in ["добрый", "здравствуйте", "уважаемый"]):
        text = f"Добрый день!\n\n{text}"
    
    return text


def _hard_truncate(text: str, max_chars: int = 700) -> str:
    """Hard truncate text to max_chars, preserving sentence boundaries.
    
    This FORCEFULLY limits letter length regardless of AI output.
    """
    if len(text) <= max_chars:
        return text
    
    # Find best cut point
    truncated = text[:max_chars]
    
    # Try to end at sentence boundary
    for sep in ['.\n', '!\n', '?\n', '. ', '! ', '? ']:
        last_end = truncated.rfind(sep)
        if last_end > max_chars * 0.6:  # At least 60% of max
            truncated = truncated[:last_end + 1]
            break
    
    # Remove incomplete last paragraph if any
    paragraphs = [p.strip() for p in truncated.split('\n\n') if p.strip()]
    if len(paragraphs) > 1:
        # Check if last paragraph is incomplete (no ending punctuation)
        last_p = paragraphs[-1]
        if not last_p.endswith(('.', '!', '?')):
            paragraphs = paragraphs[:-1]
            truncated = '\n\n'.join(paragraphs)
    
    log.warning(f"Letter HARD truncated from {len(text)} to {len(truncated)} chars")
    return truncated.strip()


def _ensure_contacts(text: str, cfg) -> str:
    """Ensure Telegram and name signature are in the letter."""
    # Check if Telegram is already there
    has_telegram = "telegram" in text.lower() or "@" in text
    
    # Add Telegram if missing and configured
    if not has_telegram and cfg.auth.telegram:
        text += f"\n\nTelegram: @{cfg.auth.telegram}"
    
    # Add name signature if missing
    if "с уважением" not in text.lower():
        name = cfg.auth.name or cfg.auth.email.split('@')[0] if cfg.auth.email else ""
        if name:
            text += f"\n\nС уважением,\n{name}"
    
    return text
