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

# Default system prompt - letter body ONLY, no contacts/signature
DEFAULT_SYSTEM_PROMPT = """Ты пишешь ТОЛЬКО тело сопроводительного письма (без подписи и контактов).

ПРИМЕР (только тело, без Telegram и подписи):
---
Добрый день!

Меня заинтересовала вакансия Frontend Developer в вашей компании. В вашем стеке React/TypeScript — мои основные инструменты последние 3 года.

Работал с похожими задачами в EPAM: мигрировал легаси на React. Уверен, что опыт поможет продукту.

Готов обсудить детали.
---

СТРОГИЕ ПРАВИЛА:
1. Только 3-4 абзаца (приветствие, опыт, призыв)
2. Макс 300 символов
3. БЕЗ "Telegram: ..." в конце
4. БЕЗ "С уважением, ..." в конце
5. Без общих фраз типа "я ответственный"
6. Конкретика: технологии из вакансии + твой опыт

Контакты и подпись будут добавлены отдельно, не пиши их!"""


async def generate_with_groq(
    resume: ResumeInfo,
    vacancy: VacancyDetails,
    vacancy_description: Optional[str] = None,
    config: Optional[AIGeneratorConfig] = None,
    telegram: Optional[str] = None,
    author_name: Optional[str] = None,
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
        user_prompt = _build_groq_prompt(resume, vacancy, vacancy_description, telegram, author_name)
        
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
                "max_tokens": 250,  # Hard limit to ~400-500 chars output
                "temperature": 0.3,  # Low temperature for concise output
            }
            
            log.info(f"Trying Groq model: {model}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GROQ_URL, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        cover_letter = data["choices"][0]["message"]["content"].strip()
                        log.info(f"✅ Groq generated: {len(cover_letter)} chars")
                        # Clean, ensure contacts, then truncate to 500 chars
                        cover_letter = _clean_cover_letter(cover_letter)
                        # Add contacts BEFORE truncation so they have priority
                        cover_letter = _ensure_contacts(cover_letter, telegram, author_name)
                        # Truncate but keep contacts visible
                        cover_letter = _smart_truncate(cover_letter, max_chars=500)
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
    telegram: Optional[str] = None,
    author_name: Optional[str] = None,
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
        "5. Максимум 3 абзаца (приветствие, опыт, призыв)",
        "6. НЕ добавляй Telegram — будет добавлен отдельно",
        "7. НЕ добавляй подпись 'С уважением' — будет добавлена отдельно",
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


def _smart_truncate(text: str, max_chars: int = 500) -> str:
    """Smart truncate that keeps contacts (last 2 paragraphs) visible.
    
    Priority: keep Telegram and signature, truncate body if needed.
    """
    if len(text) <= max_chars:
        return text
    
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    # Identify contact paragraphs (last 1-2 paragraphs usually)
    contact_markers = ['telegram', 'с уважением', 'телеграм', '@', 'tel:', 'phone:']
    contact_paragraphs = []
    body_paragraphs = []
    
    for i, p in enumerate(paragraphs):
        p_lower = p.lower()
        if any(m in p_lower for m in contact_markers) or i >= len(paragraphs) - 2:
            # Last 2 paragraphs or paragraphs with contact markers
            contact_paragraphs.append(p)
        else:
            body_paragraphs.append(p)
    
    # Calculate space needed for contacts
    contacts_text = '\n\n'.join(contact_paragraphs)
    contacts_len = len(contacts_text)
    
    # Available space for body
    available_for_body = max_chars - contacts_len - 10  # 10 for padding
    
    if available_for_body < 100:
        # Not enough space, keep only greeting + minimal body + contacts
        if body_paragraphs:
            body_text = body_paragraphs[0][:100] + "..." if len(body_paragraphs[0]) > 100 else body_paragraphs[0]
            result = body_text + '\n\n' + contacts_text
        else:
            result = contacts_text
    else:
        # Build body within limit
        body_parts = []
        current_len = 0
        for p in body_paragraphs:
            if current_len + len(p) + 2 <= available_for_body:  # +2 for \n\n
                body_parts.append(p)
                current_len += len(p) + 2
            else:
                # Try to add partial paragraph ending with sentence
                remaining = available_for_body - current_len
                if remaining > 50:
                    partial = p[:remaining]
                    for sep in ['. ', '! ', '? ']:
                        last_end = partial.rfind(sep)
                        if last_end > remaining * 0.5:
                            body_parts.append(partial[:last_end + 1])
                            break
                break
        
        # Combine body + contacts
        if body_parts:
            result = '\n\n'.join(body_parts) + '\n\n' + contacts_text
        else:
            result = contacts_text
    
    log.warning(f"Letter SMART truncated from {len(text)} to {len(result)} chars, kept {len(contact_paragraphs)} contact paragraphs")
    return result.strip()


def _ensure_contacts(text: str, telegram: Optional[str], author_name: Optional[str]) -> str:
    """Append Telegram and name signature to the end of letter.
    
    Assumes AI generated only the body without contacts.
    """
    name = author_name
    
    # Clean up any accidental contacts AI might have added
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        lower = line.lower().strip()
        # Skip lines that look like contacts (but keep the rest)
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
