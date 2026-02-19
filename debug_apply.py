#!/usr/bin/env python3
"""
Дебаг-скрипт для проверки отклика с логированием каждого шага.
Запускает ОДИН отклик и подробно показывает что происходит.
"""
import asyncio
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from hh_bot.utils.config import load_config
from hh_bot.utils.logger import setup_logging, get_logger
from hh_bot.browser.launcher import launch_browser
from hh_bot.auth.login import ensure_logged_in
from hh_bot.scraper.resume_parser import fetch_resume_content, ResumeInfo
from hh_bot.scraper.search import search_vacancies
from hh_bot.scraper.vacancy import fetch_vacancy_details
from hh_bot.scraper.apply import apply_to_vacancy

# Максимальное логирование
setup_logging("DEBUG")
log = get_logger(__name__)


async def debug_single_apply():
    """Отладка одного отклика."""
    cfg = load_config()
    
    query = input("Введи поисковый запрос (например 'Python junior'): ").strip()
    if not query:
        print("Отменено")
        return
    
    print(f"\n{'='*60}")
    print(f"ДЕБАГ: Запуск с query='{query}'")
    print(f"{'='*60}")
    print(f"Конфиг:")
    print(f"  cover_letter.enabled: {cfg.cover_letter.enabled}")
    print(f"  cover_letter.ai.enabled: {cfg.cover_letter.ai.enabled}")
    print(f"  use_ai_cover_letter: {cfg.use_ai_cover_letter}")
    print(f"{'='*60}\n")
    
    async with launch_browser(headless=False) as (context, page):
        # 1. Логин
        print("[1/5] Проверяю авторизацию...")
        await ensure_logged_in(page)
        print("✅ Авторизован\n")
        
        # 2. Загружаем резюме
        print("[2/5] Загружаю резюме...")
        resume_info = None
        if cfg.cover_letter.enabled:
            try:
                resume_info = await fetch_resume_content(page)
                print(f"✅ Резюме загружено:")
                print(f"   title: {resume_info.title}")
                print(f"   about: {resume_info.about[:100] if resume_info.about else '(пусто)'}...")
                print(f"   skills: {resume_info.skills[:100] if resume_info.skills else '(пусто)'}...")
            except Exception as e:
                print(f"⚠️  Ошибка загрузки резюме: {e}")
        else:
            print("ℹ️  Cover letter disabled, резюме не загружаем")
        print()
        
        # 3. Ищем вакансии
        print("[3/5] Ищу вакансии...")
        cards = await search_vacancies(page, query, cfg.search.area_id, 0)
        print(f"✅ Найдено вакансий: {len(cards)}\n")
        
        if not cards:
            print("❌ Вакансии не найдены")
            return
        
        # Берем первую подходящую
        target_card = None
        for card in cards:
            print(f"Проверяю: {card.title} - {card.employer}")
            
            # Открываем для проверки
            details = await fetch_vacancy_details(page, card.url, card.vacancy_id)
            
            # Пропускаем если уже откликались, есть тест или внешняя ссылка
            if details.already_applied:
                print(f"  -> Пропуск: уже откликались")
                continue
            if details.has_test and cfg.filters.skip_with_tests:
                print(f"  -> Пропуск: есть тестовое")
                continue
            if details.is_external and cfg.filters.skip_direct_vacancies:
                print(f"  -> Пропуск: внешняя ссылка")
                continue
            
            print(f"  -> Подходит!")
            target_card = card
            break
        
        if not target_card:
            print("\n❌ Нет подходящих вакансий для теста")
            return
        
        # 4. Открываем выбранную вакансию
        print(f"\n[4/5] Открываю вакансию: {target_card.title}")
        details = await fetch_vacancy_details(page, target_card.url, target_card.vacancy_id)
        print(f"✅ Вакансия открыта")
        print(f"   ID: {details.vacancy_id}")
        print(f"   Название: {details.title}")
        print(f"   Компания: {details.employer}")
        print(f"   Описание: {details.description[:150] if details.description else '(пусто)'}...")
        print(f"   Требуется письмо: {details.response_letter_required}")
        print()
        
        # 5. Пытаемся откликнуться
        print("[5/5] Отправляю отклик...")
        print(f"   resume_info: {resume_info}")
        print(f"   resume_info.title: {resume_info.title if resume_info else 'N/A'}")
        
        input("\n⚠️  ГОТОВ К ОТКЛИКУ! Нажми Enter для продолжения...")
        
        try:
            success = await apply_to_vacancy(page, details, "", resume_info)
            print(f"\n{'='*60}")
            print(f"Результат: {'✅ УСПЕХ' if success else '❌ НЕУДАЧА'}")
            print(f"{'='*60}")
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ ОШИБКА: {e}")
            print(f"{'='*60}")
            import traceback
            traceback.print_exc()
        
        # Делаем скриншот
        await page.screenshot(path="debug_result.png")
        print("\n📸 Скриншот сохранен: debug_result.png")
        
        input("\nНажми Enter для закрытия...")


if __name__ == "__main__":
    asyncio.run(debug_single_apply())
