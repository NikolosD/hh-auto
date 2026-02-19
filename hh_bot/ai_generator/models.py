"""Models for AI Generator configuration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AIModel(str, Enum):
    """Available free models on OpenRouter."""
    # Бесплатные модели (через OpenRouter)
    DEEPSEEK_CHAT_FREE = "deepseek/deepseek-chat:free"
    MISTRAL_7B_FREE = "mistralai/mistral-7b-instruct:free"
    LLAMA_3_8B_FREE = "meta-llama/llama-3-8b-instruct:free"
    GEMMA_2_9B_FREE = "google/gemma-2-9b-it:free"
    
    # Платные модели (если есть API ключ)
    GPT_4O_MINI = "openai/gpt-4o-mini"
    CLAUDE_HAIKU = "anthropic/claude-3-haiku"
    GROK_BETA = "x-ai/grok-beta"


@dataclass
class AIGeneratorConfig:
    """Configuration for AI cover letter generation."""
    enabled: bool = False
    api_key: str = ""  # OpenRouter API ключ (опционально, есть бесплатные модели)
    model: str = AIModel.DEEPSEEK_CHAT_FREE
    max_tokens: int = 500
    temperature: float = 0.7
    custom_prompt: Optional[str] = None
    
    @property
    def is_free_model(self) -> bool:
        """Check if using a free model."""
        return ":free" in self.model
