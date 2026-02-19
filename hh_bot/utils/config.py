from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, field_validator


class AuthConfig(BaseModel):
    email: str = ""


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


class CoverLetterConfig(BaseModel):
    enabled: bool = False
    always_include: bool = False
    template: str = (
        "Добрый день! Меня заинтересовала вакансия {vacancy_name} в компании {company_name}.\n"
        "Готов обсудить детали."
    )


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


_config: Optional[Config] = None


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
    return _config


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
