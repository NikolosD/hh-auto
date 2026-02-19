#!/usr/bin/env python3
"""
Интеграционный тест для проверки заполнения сопроводительного письма.
Запускает браузер, заходит на hh.ru и проверяет работу cover letter.
"""
import asyncio
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from patchright.async_api import async_playwright
from hh_bot.utils.config import load_config
from hh_bot.scraper.resume_parser import ResumeInfo, fetch_resume_content
from hh_bot.scraper.vacancy import fetch_vacancy_details
from hh_bot.scraper.apply import apply_to_vacancy
from hh_bot.ai_generator.generator import generate_ai_cover_letter
from hh_bot.ai_generator.models import AIGeneratorConfig
from hh_bot.utils.logger import get_logger, setup_logging

setup_logging("DEBUG")
log = get_logger(__name__)


async def test_resume_parsing(page):
    """Test 1: Проверяем парсинг резюме."""
    print("\n=== ТЕСТ 1: Парсинг резюме ===")
    
    try:
        resume = await fetch_resume_content(page)
        print(f"Заголовок резюме: {resume.title}")
        print(f"О себе: {resume.about[:100] if resume.about else '(пусто)'}...")
        print(f"Навыки: {resume.skills[:100] if resume.skills else '(пусто)'}...")
        
        if not resume.title:
            print("❌ FAIL: Не удалось спарсить резюме!")
            return None
        
        print("✅ Резюме загружено")
        return resume
        
    except Exception as e:
        print(f"❌ FAIL: Ошибка при загрузке резюме: {e}")
        return None


async def test_vacancy_page(page, vacancy_url):
    """Test 2: Открываем вакансию и проверяем детали."""
    print(f"\n=== ТЕСТ 2: Открытие вакансии ===")
    print(f"URL: {vacancy_url}")
    
    try:
        # Извлекаем ID вакансии из URL
        vacancy_id = vacancy_url.split("/")[-1].split("?")[0]
        
        details = await fetch_vacancy_details(page, vacancy_url, vacancy_id)
        print(f"Название: {details.title}")
        print(f"Компания: {details.employer}")
        print(f"Описание: {details.description[:200] if details.description else '(пусто)'}...")
        print(f"Требуется письмо: {details.response_letter_required}")
        
        if not details.title:
            print("❌ FAIL: Не удалось получить название вакансии!")
            return None
        
        print("✅ Вакансия загружена")
        return details
        
    except Exception as e:
        print(f"❌ FAIL: Ошибка при загрузке вакансии: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_find_letter_field(page):
    """Test 3: Проверяем, находится ли поле для письма."""
    print("\n=== ТЕСТ 3: Поиск поля для письма ===")
    
    from patchright.async_api import TimeoutError as PatchrightTimeout
    
    # Сначала нажимаем кнопку отклика
    apply_btn = page.locator(
        "[data-qa='vacancy-response-link-top'], "
        "[data-qa='vacancy-response-link-bottom']"
    ).first
    
    if await apply_btn.count() == 0:
        print("❌ FAIL: Кнопка отклика не найдена!")
        return False
    
    print("Нажимаю кнопку отклика...")
    await apply_btn.click()
    await asyncio.sleep(2)
    
    # Ищем поле для письма
    letter_selectors = [
        "[data-qa='vacancy-response-letter-text']",
        "textarea[name='text']",
        "textarea[placeholder*='письм']",
        "textarea[placeholder*='Письм']",
    ]
    
    for selector in letter_selectors:
        try:
            field = page.locator(selector).first
            if await field.count() > 0:
                print(f"✅ Поле для письма найдено: {selector}")
                
                # Проверим, видимо ли поле
                is_visible = await field.is_visible()
                print(f"Поле видимо: {is_visible}")
                
                return True
        except Exception as e:
            print(f"  Селектор {selector} не сработал: {e}")
    
    print("❌ FAIL: Поле для письма не найдено!")
    
    # Сделаем скриншот для диагностики
    await page.screenshot(path="test_no_letter_field.png")
    print("Скриншот сохранен: test_no_letter_field.png")
    
    return False


async def test_ai_generation(resume, details):
    """Test 4: Проверяем AI генерацию."""
    print("\n=== ТЕСТ 4: AI генерация письма ===")
    
    cfg = load_config()
    
    if not cfg.use_ai_cover_letter:
        print("⚠️ SKIP: AI не включен в конфиге")
        return None
    
    ai_config = AIGeneratorConfig(
        enabled=True,
        api_key=cfg.cover_letter.ai.api_key,
        model=cfg.cover_letter.ai.model,
    )
    
    print(f"Модель: {ai_config.model}")
    print(f"API ключ: {'***' if ai_config.api_key else '(пусто - бесплатная модель)'}")
    
    try:
        letter = await generate_ai_cover_letter(
            resume=resume,
            vacancy=details,
            vacancy_description=details.description,
            config=ai_config,
        )
        
        if letter:
            print(f"✅ AI сгенерировал письмо! Длина: {len(letter)} chars")
            print(f"\n--- Письмо (первые 400 символов) ---")
            print(letter[:400])
            print("--- конец ---\n")
            return letter
        else:
            print("❌ AI вернул None (возможно, rate limit или ошибка сети)")
            return None
            
    except Exception as e:
        print(f"❌ FAIL: Ошибка при AI генерации: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_fill_letter_field(page, text):
    """Test 5: Проверяем заполнение поля."""
    print("\n=== ТЕСТ 5: Заполнение поля письма ===")
    
    from hh_bot.browser.human import human_type_locator
    
    # Ищем поле
    letter_field = page.locator(
        "[data-qa='vacancy-response-letter-text'], "
        "textarea[name='text'], "
        "textarea[placeholder*='письм']"
    ).first
    
    if await letter_field.count() == 0:
        print("❌ FAIL: Поле не найдено!")
        return False
    
    print(f"Заполняю поле текстом ({len(text)} chars)...")
    
    try:
        await human_type_locator(page, letter_field, text)
        await asyncio.sleep(1)
        
        # Проверяем, что текст введен
        entered_text = await letter_field.input_value()
        
        if len(entered_text) > 0:
            print(f"✅ Текст введен! Длина: {len(entered_text)} chars")
            print(f"Первые 100 символов: {entered_text[:100]}")
            return True
        else:
            print("❌ FAIL: Поле пустое после ввода!")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Ошибка при вводе текста: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_full_apply_flow(page, details, resume):
    """Test 6: Проверяем полный flow apply с письмом."""
    print("\n=== ТЕСТ 6: Полный flow отклика ===")
    
    try:
        # Перезагружаем страницу вакансии для чистого теста
        await page.goto(details.url, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        # Вызываем apply_to_vacancy
        success = await apply_to_vacancy(page, details, "", resume)
        
        print(f"Результат apply_to_vacancy: {success}")
        
        # Делаем скриншот результата
        await page.screenshot(path="test_apply_result.png")
        print("Скриншот сохранен: test_apply_result.png")
        
        return success
        
    except Exception as e:
        print(f"❌ FAIL: Ошибка в apply flow: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 70)
    print("ИНТЕГРАЦИОННЫЙ ТЕСТ: Cover Letter Generation")
    print("=" * 70)
    
    cfg = load_config()
    
    # Спросим URL вакансии для теста
    vacancy_url = input("\nВведите URL вакансии для теста (или Enter для отмены): ").strip()
    if not vacancy_url:
        print("Тест отменен")
        return 0
    
    print(f"\nЗапускаю браузер...")
    
    async with async_playwright() as p:
        # Запускаем браузер (не headless для видимости)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        try:
            # Тест 1: Загружаем резюме
            resume = await test_resume_parsing(page)
            if not resume:
                print("\n❌ Тест остановлен: не удалось загрузить резюме")
                return 1
            
            # Тест 2: Открываем вакансию
            details = await test_vacancy_page(page, vacancy_url)
            if not details:
                print("\n❌ Тест остановлен: не удалось открыть вакансию")
                return 1
            
            # Тест 3: Ищем поле для письма
            has_field = await test_find_letter_field(page)
            if not has_field:
                print("\n⚠️  Поле для письма не найдено - возможно, оно не требуется для этой вакансии")
            
            # Тест 4: AI генерация (если включена)
            ai_letter = None
            if cfg.use_ai_cover_letter:
                ai_letter = await test_ai_generation(resume, details)
            
            # Тест 5: Заполняем поле вручную (если нашли)
            if has_field and ai_letter:
                filled = await test_fill_letter_field(page, ai_letter)
                if filled:
                    print("\n✅ Письмо успешно введено в поле!")
                    input("\nНажми Enter для продолжения (я подожду)...")
            
            # Тест 6: Полный flow (опционально)
            print("\n" + "=" * 70)
            do_apply = input("Запустить полный flow отклика? (yes/no): ").strip().lower()
            if do_apply == 'yes':
                success = await test_full_apply_flow(page, details, resume)
                if success:
                    print("\n✅ Отклик отправлен успешно!")
                else:
                    print("\n❌ Отклик не удался")
            
            print("\n" + "=" * 70)
            print("Тест завершен")
            print("=" * 70)
            
        finally:
            input("\nНажми Enter для закрытия браузера...")
            await browser.close()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
