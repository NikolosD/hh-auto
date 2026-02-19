from __future__ import annotations

import asyncio
import random
import math
from typing import Tuple

from patchright.async_api import Page, Locator

from hh_bot.utils.delays import (
    sleep_typing,
    sleep_before_click,
    sleep_micro,
    uniform_delay,
    gauss_delay,
)
from hh_bot.utils.logger import get_logger

log = get_logger(__name__)


def _bezier_point(
    t: float,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
) -> Tuple[float, float]:
    """Cubic Bezier interpolation."""
    mt = 1 - t
    x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
    return x, y


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text into a field with human-like behavior."""
    element = page.locator(selector).first
    await element.scroll_into_view_if_needed()
    await element.click()
    await sleep_micro()
    
    # Use fill() for atomic, reliable text input
    # This works even if page loses focus, and is much faster than character-by-character
    await element.fill(text)

    log.debug("Typed text", chars=len(text))


async def human_type_locator(page: Page, locator: Locator, text: str) -> None:
    """Type text into a Locator with human-like delays.
    
    Uses element.fill() for atomic text input which ensures:
    1. Text goes to the specific element regardless of page focus state
    2. No lost characters when user clicks outside the browser
    3. Fast, reliable operation (no character-by-character delays that can fail)
    """
    # Ensure element is visible and focused
    await locator.scroll_into_view_if_needed()
    await locator.click()
    await sleep_micro()
    
    # Atomic fill - reliable and focus-independent
    await locator.fill(text)
    
    log.debug("Typed text into locator", chars=len(text))


async def human_click(page: Page, selector: str) -> None:
    """Click element with human-like mouse movement via Bezier curve."""
    element = page.locator(selector).first
    await _bezier_move_and_click(page, element)


async def human_click_locator(page: Page, locator: Locator) -> None:
    """Click a Locator with human-like mouse movement."""
    await _bezier_move_and_click(page, locator)


async def _bezier_move_and_click(page: Page, locator: Locator) -> None:
    """Move mouse along a Bezier curve to element, then click."""
    try:
        box = await locator.bounding_box()
    except Exception:
        await locator.click()
        return

    if box is None:
        await locator.click()
        return

    # Random target point within element bounds
    target_x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
    target_y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)

    # Get current mouse position (use viewport center as fallback)
    vp = page.viewport_size or {"width": 1280, "height": 800}
    start_x = random.uniform(vp["width"] * 0.3, vp["width"] * 0.7)
    start_y = random.uniform(vp["height"] * 0.3, vp["height"] * 0.7)

    # Random control points for natural-looking curve
    cp1 = (
        start_x + random.uniform(-100, 100),
        start_y + random.uniform(-80, 80),
    )
    cp2 = (
        target_x + random.uniform(-80, 80),
        target_y + random.uniform(-60, 60),
    )

    steps = random.randint(18, 32)
    for i in range(steps + 1):
        t = i / steps
        x, y = _bezier_point(t, (start_x, start_y), cp1, cp2, (target_x, target_y))
        await page.mouse.move(x, y)
        await asyncio.sleep(uniform_delay(0.005, 0.02))

    await sleep_before_click()
    await page.mouse.click(target_x, target_y)
    log.debug("Human click", x=round(target_x), y=round(target_y))


async def human_scroll(page: Page, distance: int = 400) -> None:
    """Scroll the page smoothly, simulating reading."""
    steps = random.randint(8, 16)
    per_step = distance / steps
    for _ in range(steps):
        await page.mouse.wheel(0, per_step)
        await asyncio.sleep(uniform_delay(0.05, 0.15))


async def random_micro_move(page: Page, count: int = 2) -> None:
    """Perform 1-3 small random mouse movements without clicking."""
    vp = page.viewport_size or {"width": 1280, "height": 800}
    for _ in range(count):
        x = random.uniform(vp["width"] * 0.1, vp["width"] * 0.9)
        y = random.uniform(vp["height"] * 0.1, vp["height"] * 0.9)
        await page.mouse.move(x, y)
        await sleep_micro()
