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

# Default system prompt (same as main generator)
DEFAULT_SYSTEM_PROMPT = """Ты — эксперт по написанию сопроводительных писем для отклика на вакансии.
Твоя задача — написать ПЕРСОНАЛИЗИРОВАННОЕ сопроводительное письмо на русском языке.

КЛЮЧЕВЫЕ ПРАВИЛА:
1. АНАЛИЗИРУЙ описание вакансии — найди ключевые требования
2. СВЯЗЫВАЙ навыки кандидата с требованиями вакансии явно
3. Покажи, что кандидат ПОНИМАЕТ чем занимается компания
4. ИЗБЕГАЙ шаблонных фраз — каждое предложение для этой вакансии
5. Максимум 150-200 слов (3-4 коротких абзаца)
6. Профессиональный, но не формальный тон

ЗАПРЕЩЕНО:
- Общие фразы без привязки к вакансии
- Шаблонные конструкции подходящие к любой вакансии"""


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
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
            }
            
            log.info(f"Trying Groq model: {model}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GROQ_URL, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        cover_letter = data["choices"][0]["message"]["content"].strip()
                        log.info(f"✅ Groq generated letter with {model}: {len(cover_letter)} chars")
                        return _clean_cover_letter(cover_letter)
                
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
    
    if not any(text.lower().startswith(g) for g in ["добрый", "здравствуйте", "уважаемый"]):
        text = f"Добрый день!\n\n{text}"
    
    return text
