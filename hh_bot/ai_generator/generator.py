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
Твоя задача — написать КОРОТКОЕ, ПЕРСОНАЛИЗИРОВАННОЕ сопроводительное письмо на русском языке.

СТРОГИЕ ОГРАНИЧЕНИЯ (ОБЯЗАТЕЛЬНЫ К СОБЛЮДЕНИЮ):
- МАКСИМУМ 150-200 слов
- МАКСИМУМ 800-1000 символов с пробелами
- Ровно 3-4 абзаца
- Каждый абзац: максимум 2 коротких предложения
- Если текст получается длиннее — сокращай, убирая второстепенное

СТРУКТУРА ПИСЬМА:
1. Приветствие + упоминание вакансии (1 предложение)
2. Связь твоих навыков с требованиями (1-2 предложения)
3. Почему эта компания/продукт интересен (1 предложение)
4. Призыв к действию + контакт (1 предложение)

ТРЕБОВАНИЯ:
- Анализируй требования вакансии и упоминай конкретные технологии
- Связывай свой опыт с их стеком
- Без общих фраз типа "я ответственный и коммуникабельный"
- Профессиональный, но не формальный тон
- Покажи, что изучил вакансию, а не шлешь шаблон

ЗАПРЕЩЕНО:
- Повторять содержимое резюме дословно
- Общие фразы без конкретики
- Больше 4 абзацев
- Длинные предложения более 20 слов"""


async def generate_ai_cover_letter(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
    config: Optional[AIGeneratorConfig] = None,
) -> Optional[str]:
    """
    Generate a cover letter using AI.
    Tries OpenRouter first, then Groq as fallback.
    
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
    
    from hh_bot.ai_generator.models import AIProvider
    
    # Route to appropriate provider
    if config.provider == AIProvider.GROQ:
        log.info("Using Groq provider")
        from hh_bot.ai_generator.groq_generator import generate_with_groq
        return await generate_with_groq(resume, vacancy, vacancy_description, config)
    
    elif config.provider == AIProvider.OPENROUTER:
        log.info("Using OpenRouter provider")
        return await _generate_with_openrouter(resume, vacancy, vacancy_description, config)
    
    else:  # AUTO - try all providers
        log.info("Auto mode: trying OpenRouter first...")
        result = await _generate_with_openrouter(resume, vacancy, vacancy_description, config)
        if result:
            return result
        
        log.info("🔄 OpenRouter failed, trying Groq...")
        from hh_bot.ai_generator.groq_generator import generate_with_groq
        result = await generate_with_groq(resume, vacancy, vacancy_description, config)
        if result:
            return result
        
        log.warning("❌ All AI providers failed")
        return None


async def _generate_with_openrouter(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
    config: Optional[AIGeneratorConfig] = None,
) -> Optional[str]:
    """Generate using OpenRouter API."""
    if config is None:
        config = AIGeneratorConfig()
    
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
            
            # Handle rate limit or model not found - try fallback models
            if response.status_code in (429, 404):
                log.warning(f"Model error ({response.status_code}), trying fallback models...")
                fallback_models = [
                    AIModel.MISTRAL_7B_FREE,
                    AIModel.LLAMA_3_1_8B_FREE,
                    AIModel.QWEN_2_5_7B_FREE,
                    AIModel.GEMMA_2_9B_FREE,
                ]
                for fallback_model in fallback_models:
                    if fallback_model == config.model:
                        continue
                    log.info(f"Trying fallback model: {fallback_model}")
                    payload["model"] = fallback_model
                    response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
                    log.info(f"Fallback response status: {response.status_code}")
                    if response.status_code == 200:
                        break
            
            response.raise_for_status()
            data = response.json()
            
            log.info(f"Response data keys: {list(data.keys())}")
            
            # Extract generated text
            if "choices" in data and len(data["choices"]) > 0:
                cover_letter = data["choices"][0]["message"]["content"].strip()
                log.info(f"✅ AI cover letter generated: {len(cover_letter)} chars")
                # Clean and truncate if too long
                cover_letter = _clean_cover_letter(cover_letter)
                cover_letter = _truncate_letter(cover_letter, max_chars=700, max_paragraphs=5)
                # Ensure contacts are present
                cover_letter = _ensure_letter_contacts(cover_letter)
                log.info(f"✅ Final letter length: {len(cover_letter)} chars")
                return cover_letter
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
    from hh_bot.utils.config import get_config
    cfg = get_config()
    
    # Clean up about text
    about_clean = ""
    if resume.about:
        about_clean = _clean_about_text(resume.about)
    
    parts = [
        "# ДАННЫЕ КАНДИДАТА",
        f"## Желаемая позиция:\n{resume.title or 'Не указана'}"
    ]
    
    if about_clean:
        parts.append(f"## Опыт и навыки:\n{about_clean}")
    
    if resume.skills:
        parts.append(f"## Ключевые навыки:\n{resume.skills}")
    
    if resume.experience:
        exp_short = resume.experience[:300] + " …" if len(resume.experience) > 300 else resume.experience
        parts.append(f"## Опыт работы:\n{exp_short}")
    
    # Add Telegram for contact
    if cfg.auth.telegram:
        parts.append(f"## Контакт для связи:\nTelegram: @{cfg.auth.telegram}")
    
    parts.extend([
        "",
        "# ВАКАНСИЯ",
        f"## Название:\n{vacancy.title}",
        f"## Компания:\n{vacancy.employer}",
        f"## Формулировка:\nИспользуй 'в вашей компании {vacancy.employer}' в письме",
    ])
    
    if vacancy_description:
        desc_short = vacancy_description[:600] + " …" if len(vacancy_description) > 600 else vacancy_description
        parts.append(f"## Описание:\n{desc_short}")
    
    parts.extend([
        "",
        "# ЗАДАЧА",
        "Напиши сопроводительное письмо для отклика на эту вакансию.",
        "",
        "КРИТИЧЕСКИ ВАЖНЫЕ ТРЕБОВАНИЯ:",
        "1. Проанализируй ТРЕБОВАНИЯ вакансии из описания выше",
        "2. Найди 2-3 навыка кандидата, которые ПРЯМО соответствуют требованиям вакансии",
        "3. ЯВНО укажи, почему кандидат подходит именно на эту вакансию (например: 'Вашим требованиям соответствует мой опыт работы с...')",
        "4. Приведи КОНКРЕТНЫЙ пример из опыта, релевантный задачам вакансии",
        "",
        "СТРОГИЕ ОГРАНИЧЕНИЯ ПО ДЛИНЕ:",
        "- МАКСИМУМ 150-200 слов (это ОБЯЗАТЕЛЬНО)",
        "- МАКСИМУМ 800-1000 символов с пробелами",
        "- 3-4 коротких абзаца",
        "- Каждый абзац: 1-2 предложения",
        "- Если не умещаешься — сократи, но сохрани ключевые моменты",
        "",
        "Формат письма:",
        "- Начни с приветствия 'Добрый день!'",
        "- Упомяни вакансию и компанию (1 предложение)",
        "- Свяжи свой опыт с требованиями (1-2 предложения)",
        "- Призыв к действию (1 предложение)",
        "- НЕ используй общие фразы типа 'у меня есть опыт разработки'",
        f"- В конце: Telegram: @{cfg.auth.telegram if cfg.auth.telegram else '(указать при наличии)'}",
        f"- Закончи: 'С уважением, {cfg.auth.name}'",
    ])
    
    return "\n".join(parts)


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


def _truncate_letter(text: str, max_chars: int = 1000, max_paragraphs: int = 5) -> str:
    """Truncate letter to reasonable length.
    
    Args:
        text: Generated letter text
        max_chars: Maximum characters (including spaces)
        max_paragraphs: Maximum number of paragraphs
    
    Returns:
        Truncated text with proper ending
    """
    # Split into paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    
    # Limit paragraphs
    if len(paragraphs) > max_paragraphs:
        paragraphs = paragraphs[:max_paragraphs]
    
    # Build text and check length
    result = "\n\n".join(paragraphs)
    
    # If still too long, truncate at sentence boundary
    if len(result) > max_chars:
        # Find last sentence end before max_chars
        truncated = result[:max_chars]
        # Look for sentence endings: . ! ? 
        for sep in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            last_end = truncated.rfind(sep)
            if last_end > max_chars * 0.7:  # At least 70% of max length
                truncated = truncated[:last_end + 1]
                break
        result = truncated.strip()
        log.warning(f"Letter truncated from {len(text)} to {len(result)} chars")
    
    # Ensure it ends with proper signature indicator
    if not result.endswith((".", "!", "?")):
        result += "."
    
    return result


def _ensure_letter_contacts(text: str) -> str:
    """Append Telegram and name signature to the end of letter.
    
    Assumes AI generated only the body without contacts.
    """
    from hh_bot.utils.config import get_config
    cfg = get_config()
    
    telegram = cfg.auth.telegram
    name = cfg.auth.name or (cfg.auth.email.split('@')[0] if cfg.auth.email else "")
    
    # Clean up any accidental contacts AI might have added
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        lower = line.lower().strip()
        # Skip lines that look like contacts
        if lower.startswith('telegram:') or lower.startswith('с уважением') or lower.startswith('tel:'):
            continue
        # Skip standalone @usernames at the end
        if line.strip().startswith('@') and len(line.strip()) < 30:
            continue
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines).strip()
    
    # Add contacts at the end
    if telegram:
        text += f"\n\nTelegram: @{telegram}"
    
    if name:
        text += f"\n\nС уважением,\n{name}"
    
    return text


def _clean_about_text(text: str) -> str:
    """Clean up 'About' text by removing headers and extra whitespace."""
    # Remove common headers
    text = text.replace("О себе", "").replace("О себе", "")  # NBSP and regular space
    text = text.replace("About", "").replace("ABOUT", "")
    
    # Remove Telegram and Email lines (we add them separately)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip contact info lines
        if line.lower().startswith(("telegram", "телеграм", "e-mail", "email", "телефон", "phone")):
            continue
        # Skip location lines
        if "грузия" in line.lower() or "тбилиси" in line.lower() or "открыт к" in line.lower():
            continue
        cleaned_lines.append(line)
    
    # Join and clean up extra whitespace
    text = " ".join(cleaned_lines)
    text = " ".join(text.split())  # Remove multiple spaces
    
    return text.strip()


def generate_fallback_cover_letter(
    resume: ResumeInfo,
    vacancy_title: str,
    company_name: str,
    vacancy_description: Optional[str] = None,
) -> str:
    """Generate a simple fallback cover letter without AI."""
    from hh_bot.utils.config import get_config
    cfg = get_config()
    
    parts = ["Добрый день!"]
    
    # More personalized opening
    parts.append(f"Меня заинтересовала вакансия {vacancy_title} в вашей компании {company_name}.")
    
    # Try to extract relevant skills from vacancy description if available
    relevant_skills = []
    if vacancy_description and resume.skills:
        # Simple keyword matching
        desc_lower = vacancy_description.lower()
        skills_parts = resume.skills.replace(",", "•").replace(";", "•").split("•")
        for skill in skills_parts:
            skill_clean = skill.strip()
            if skill_clean and skill_clean.lower() in desc_lower:
                relevant_skills.append(skill_clean)
    
    # If no matching skills found, use first few skills
    if not relevant_skills and resume.skills:
        skills_parts = resume.skills.replace(",", "•").replace(";", "•").split("•")
        relevant_skills = [s.strip() for s in skills_parts[:3] if s.strip()]
    
    # Build experience paragraph
    exp_parts = []
    if resume.title:
        exp_parts.append(f"Работаю на позиции {resume.title}")
    if relevant_skills:
        exp_parts.append(f"мой стек: {', '.join(relevant_skills[:4])}")
    
    if exp_parts:
        parts.append(". ".join(exp_parts) + ".")
    
    # Add about section if available (1-2 sentences)
    if resume.about:
        about_clean = _clean_about_text(resume.about)
        if about_clean:
            sentences = []
            current_len = 0
            for sent in about_clean.split('. '):
                sent = sent.strip()
                if not sent:
                    continue
                if not sent.endswith('.'):
                    sent += '.'
                if current_len + len(sent) <= 150:
                    sentences.append(sent)
                    current_len += len(sent) + 1
                else:
                    break
            if sentences:
                parts.append(' '.join(sentences))
    
    parts.append("Готов обсудить детали и ответить на ваши вопросы.")
    
    # Add Telegram if provided (with blank line before)
    if cfg.auth.telegram:
        parts.append("")
        parts.append(f"Telegram: @{cfg.auth.telegram}")
    
    # Add name if provided
    if cfg.auth.name:
        parts.append("")
        parts.append(f"С уважением,\n{cfg.auth.name}")
    else:
        parts.append("")
        parts.append("С уважением,")
        if cfg.auth.email:
            parts.append(cfg.auth.email.split('@')[0])
    
    # Join with single newlines, no extra blank lines
    return "\n".join(parts)
