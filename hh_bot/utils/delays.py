from __future__ import annotations

import asyncio
import random
import math


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def gauss_delay(mean: float, sigma: float, lo: float, hi: float) -> float:
    """Return a Gaussian-distributed delay clamped to [lo, hi]."""
    return clamp(random.gauss(mean, sigma), lo, hi)


def uniform_delay(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


async def sleep_between_applications(min_s: float, max_s: float) -> None:
    """Delay between job applications using Gaussian distribution."""
    mean = (min_s + max_s) / 2
    sigma = (max_s - min_s) / 6
    delay = gauss_delay(mean, sigma, min_s, max_s)
    await asyncio.sleep(delay)


async def sleep_coffee_break() -> None:
    """Long pause every 5th application ('went for coffee')."""
    delay = uniform_delay(45, 90)
    await asyncio.sleep(delay)


async def sleep_typing(char_index: int) -> None:
    """Per-character typing delay with occasional 'thinking' pauses."""
    base = gauss_delay(130, 30, 80, 220) / 1000  # 80-220ms
    await asyncio.sleep(base)
    # Pause every ~5 characters
    if char_index > 0 and char_index % 5 == 0:
        pause = uniform_delay(0.3, 0.8)
        await asyncio.sleep(pause)


async def sleep_before_click() -> None:
    """Brief drift before clicking (100-400ms)."""
    await asyncio.sleep(uniform_delay(0.1, 0.4))


async def sleep_micro() -> None:
    """Short micro-pause between actions (50-200ms)."""
    await asyncio.sleep(uniform_delay(0.05, 0.2))


async def sleep_page_load() -> None:
    """Wait after navigation (0.8-2s)."""
    await asyncio.sleep(uniform_delay(0.8, 2.0))


async def sleep_after_submit() -> None:
    """Wait after form submission (1-3s)."""
    await asyncio.sleep(uniform_delay(1.0, 3.0))
