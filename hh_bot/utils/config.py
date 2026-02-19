from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, field_validator


class AuthConfig(BaseModel):
    email: str = ""
    telegram: str = ""  # Telegram username для сопроводительных писем


class BrowserConfig(BaseModel):
    profile_dir: str = "./data/browser_profile"
    headless: bool = False
    proxy: str = ""  # e.g. "http://127.0.0.1:1080" or "socks5://127.0.0.1:1080"


class SearchConfig(BaseModel):
    query: str = ""
    area_id: int = 113
    max_pages: int = 5


class LimitsConfig(BaseModel):
    max_applications_per_session: int = 20
    min_delay_between_applications: int = 10
    max_delay_between_applications: int = 30


class FiltersConfig(BaseModel):
    skip_with_tests: bool = True
    skip_direct_vacancies: bool = True
    blocked_keywords: List[str] = []
    blocked_employers: List[str] = []


class AIGeneratorConfig(BaseModel):
    enabled: bool = False  # Использовать AI для генерации писем
    api_key: str = ""  # OpenRouter API ключ (опционально)
    model: str = "deepseek/deepseek-chat:free"  # Модель (бесплатные: deepseek/deepseek-chat:free, mistralai/mistral-7b-instruct:free)
    max_tokens: int = 500
    temperature: float = 0.7
    custom_prompt: str = ""  # Кастомный системный промпт (опционально)


class CoverLetterConfig(BaseModel):
    enabled: bool = False
    always_include: bool = False
    template: str = (
        "Добрый день! Меня заинтересовала вакансия {vacancy_name} в компании {company_name}.\n"
        "Готов обсудить детали."
    )
    ai: AIGeneratorConfig = AIGeneratorConfig()  # AI-генерация писем


class ResumeConfig(BaseModel):
    preferred_title: str = ""


class Config(BaseModel):
    auth: AuthConfig = AuthConfig()
    browser: BrowserConfig = BrowserConfig()
    search: SearchConfig = SearchConfig()
    limits: LimitsConfig = LimitsConfig()
    filters: FiltersConfig = FiltersConfig()
    cover_letter: CoverLetterConfig = CoverLetterConfig()
    resume: ResumeConfig = ResumeConfig()
    
    @property
    def use_ai_cover_letter(self) -> bool:
        """Check if AI cover letter generation is enabled."""
        return self.cover_letter.enabled and self.cover_letter.ai.enabled


_config: Optional[Config] = None
_cli_overrides: dict = {}


def set_cli_overrides(overrides: dict) -> None:
    """Установить переопределения конфига из CLI-аргументов."""
    global _cli_overrides
    _cli_overrides = overrides


def _apply_overrides(config: Config, overrides: dict) -> Config:
    """Применить CLI-переопределения к конфигу."""
    for key, value in overrides.items():
        parts = key.split(".")
        obj = config
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
    return config


def load_config(path: str = "config.yaml") -> Config:
    global _config
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file '{path}' not found. "
            "Copy config.example.yaml to config.yaml and fill in your details."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _config = Config.model_validate(data)
    
    # Применяем CLI-переопределения
    if _cli_overrides:
        _config = _apply_overrides(_config, _cli_overrides)
    
    return _config


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
