"""Models for AI Generator configuration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AIModel(str, Enum):
    """Available free models on OpenRouter."""
    # Бесплатные модели (через OpenRouter) - список актуален на февраль 2025
    # Проверять доступность: https://openrouter.ai/models?max_price=0
    MISTRAL_7B_FREE = "mistralai/mistral-7b-instruct:free"
    LLAMA_3_1_8B_FREE = "meta-llama/llama-3.1-8b-instruct:free"
    QWEN_2_5_7B_FREE = "qwen/qwen-2.5-7b-instruct:free"
    GEMMA_2_9B_FREE = "google/gemma-2-9b-it:free"
    DEEPSEEK_CHAT_FREE = "deepseek/deepseek-chat:free"  # Иногда недоступна
    
    # Платные модели (если есть API ключ)
    GPT_4O_MINI = "openai/gpt-4o-mini"
    CLAUDE_HAIKU = "anthropic/claude-3-haiku"
    GROK_BETA = "x-ai/grok-beta"


@dataclass
class AIGeneratorConfig:
    """Configuration for AI cover letter generation."""
    enabled: bool = False
    api_key: str = ""  # OpenRouter API ключ (опционально, есть бесплатные модели)
    model: str = AIModel.MISTRAL_7B_FREE  # Дефолтная бесплатная модель
    max_tokens: int = 500
    temperature: float = 0.7
    custom_prompt: Optional[str] = None
    
    @property
    def is_free_model(self) -> bool:
        """Check if using a free model."""
        return ":free" in self.model
