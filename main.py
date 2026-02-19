#!/usr/bin/env python3
"""hh.ru Auto-Apply Bot CLI."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
import yaml

# Fix Windows console encoding for Cyrillic characters
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from hh_bot.utils.logger import setup_logging, get_logger
from hh_bot.utils.config import set_cli_overrides

log = get_logger(__name__)


def _load_config(config_path: str, cli_opts: dict = None):
    from hh_bot.utils.config import load_config
    try:
        cfg = load_config(config_path)
        if cli_opts:
            set_cli_overrides(cli_opts)
        return cfg
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to config.yaml")
@click.option("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING)")
@click.pass_context
def cli(ctx: click.Context, config: str, log_level: str) -> None:
    """hh.ru Auto-Apply Bot — автоматические отклики на вакансии."""
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["cli_opts"] = {}


@cli.command()
@click.option("--email", "-e", default=None, help="Email для входа (если не указан, берется из config.yaml)")
@click.option("--interactive", "-i", is_flag=True, help="Интерактивный ввод email")
@click.pass_context
def login(ctx: click.Context, email: str | None, interactive: bool) -> None:
    """Войти в hh.ru через браузер (email + код из письма)."""
    cfg = _load_config(ctx.obj["config_path"])
    
    # Определяем email для входа
    if interactive or (not email and not cfg.auth.email):
        email = click.prompt("Введите email для входа в hh.ru")
    elif not email:
        email = cfg.auth.email
    
    if not email:
        click.echo("Ошибка: email не указан. Используйте --email или добавьте в config.yaml", err=True)
        sys.exit(1)

    async def _run():
        from hh_bot.browser.launcher import launch_browser
        from hh_bot.auth.login import do_login_with_email, is_logged_in

        async with launch_browser() as (context, page):
            if await is_logged_in(page):
                click.echo("✅ Уже авторизованы! Сессия активна.")
                return
            await do_login_with_email(page, email)
            click.echo("✅ Авторизация успешна. Сессия сохранена в профиле браузера.")

    asyncio.run(_run())


@cli.command()
@click.option("--query", "-q", default="", help="Поисковый запрос (например: 'Python разработчик')")
@click.option("--area-id", "-a", type=int, help="Регион (113=Россия, 1=Москва, 2=СПб, 48=Грузия)")
@click.option("--area-ids", "-A", help="Несколько регионов через запятую (113,16,40)")
@click.option("--max-pages", "-p", type=int, help="Макс. страниц поиска")
@click.option("--max-apps", "-m", type=int, help="Макс. откликов за сессию")
@click.option("--skip-tests/--no-skip-tests", default=None, help="Пропускать вакансии с тестовым заданием")
@click.option("--skip-direct/--no-skip-direct", default=None, help="Пропускать вакансии с внешней ссылкой")
@click.option("--cover-letter/--no-cover-letter", default=None, help="Добавлять сопроводительное письмо")
@click.option("--ai-letter/--no-ai-letter", default=None, help="Использовать AI для писем")
@click.option("--headless", is_flag=True, help="Запускать браузер в фоновом режиме")
@click.option("--dry-run", is_flag=True, help="Только парсинг без реальных откликов")
@click.option("--interactive", "-i", is_flag=True, help="Интерактивный режим с вопросами")
@click.option("--telegram", "-t", help="Telegram username для писем")
@click.option("--name", "-n", help="Имя для подписи в письмах")
@click.option("--log-level", "-l", default="INFO", help="Уровень логирования")
@click.pass_context
def run(
    ctx: click.Context,
    query: str,
    area_id: int | None,
    area_ids: str | None,
    max_pages: int | None,
    max_apps: int | None,
    skip_tests: bool | None,
    skip_direct: bool | None,
    cover_letter: bool | None,
    ai_letter: bool | None,
    headless: bool,
    dry_run: bool,
    interactive: bool,
    telegram: str | None,
    name: str | None,
    log_level: str,
) -> None:
    """Запустить сессию автоматических откликов."""
    cli_opts = {}
    
    # Обработка area_ids (список через запятую)
    if area_ids:
        try:
            ids = [int(x.strip()) for x in area_ids.split(",")]
            cli_opts["search.area_ids"] = ids
        except ValueError:
            click.echo("❌ Ошибка: area_ids должны быть числами через запятую (например: 113,16,40)", err=True)
            sys.exit(1)
    elif area_id is not None:
        cli_opts["search.area_id"] = area_id
        
    if max_pages is not None:
        cli_opts["search.max_pages"] = max_pages
    if max_apps is not None:
        cli_opts["limits.max_applications_per_session"] = max_apps
    if skip_tests is not None:
        cli_opts["filters.skip_with_tests"] = skip_tests
    if skip_direct is not None:
        cli_opts["filters.skip_direct_vacancies"] = skip_direct
    if cover_letter is not None:
        cli_opts["cover_letter.enabled"] = cover_letter
    if ai_letter is not None:
        cli_opts["cover_letter.ai.enabled"] = ai_letter
    if headless:
        cli_opts["browser.headless"] = True
    if telegram:
        cli_opts["auth.telegram"] = telegram.strip().lstrip("@")
    if name:
        cli_opts["auth.name"] = name
    
    setup_logging(log_level)
    cfg = _load_config(ctx.obj["config_path"], cli_opts)

    # === ИНТЕРАКТИВНЫЙ ВВОД ===
    if interactive or not query:
        click.echo("\n" + "=" * 50)
        click.echo("🤖 Настройка сессии откликов")
        click.echo("=" * 50)
        
        if not query:
            query = click.prompt("🔍 Поисковый запрос", default=cfg.search.query or "")
        
        if not cfg.auth.telegram and not telegram:
            tg = click.prompt("📱 Telegram (опционально)", default="", show_default=False)
            if tg:
                cli_opts["auth.telegram"] = tg.strip().lstrip("@")
                cfg = _load_config(ctx.obj["config_path"], cli_opts)
        
        if not cfg.auth.name and not name:
            nm = click.prompt("👤 Имя для подписи (опционально)", default="", show_default=False)
            if nm:
                cli_opts["auth.name"] = nm
                cfg = _load_config(ctx.obj["config_path"], cli_opts)
        
        click.echo("=" * 50 + "\n")

    if not query.strip():
        click.echo("❌ Поисковый запрос не может быть пустым. Используйте --query или --interactive", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(f"[DRY RUN] Поиск: '{query}' (отклики не отправляются)")

    async def _run():
        from hh_bot.browser.launcher import launch_browser
        from hh_bot.bot.state import StateDB
        from hh_bot.bot.runner import run_session

        db = StateDB()
        try:
            async with launch_browser() as (context, page):
                if dry_run:
                    from hh_bot.scraper.search import search_vacancies
                    from hh_bot.auth.login import ensure_logged_in
                    await ensure_logged_in(page)
                    area = cli_opts.get("search.area_ids", [cli_opts.get("search.area_id", 113)])
                    cards = await search_vacancies(page, query, area, 0)
                    click.echo(f"\nНайдено вакансий: {len(cards)}")
                    for c in cards[:10]:
                        click.echo(f"  [{c.vacancy_id}] {c.title} — {c.employer}")
                    return

                stats = await run_session(page, query, db)
                click.echo("\n" + "=" * 50)
                click.echo(f"✅ Сессия завершена:")
                click.echo(f"  📨 Откликнулся:  {stats.applied}")
                click.echo(f"  ⏭️  Пропущено:    {stats.skipped}")
                click.echo(f"  ❌ Ошибки:       {stats.errors}")
                if stats.skip_reasons:
                    click.echo("  Причины пропуска:")
                    for reason, count in sorted(stats.skip_reasons.items(), key=lambda x: -x[1]):
                        click.echo(f"    • {reason}: {count}")
        finally:
            db.close()

    asyncio.run(_run())


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Показать статистику откликов."""
    _load_config(ctx.obj["config_path"])

    from hh_bot.bot.state import StateDB
    db = StateDB()
    try:
        stats = db.get_stats()
        click.echo(f"\n📊 Статистика откликов:")
        click.echo(f"  ✅ Всего откликнулся: {stats['total_applied']}")
        click.echo(f"  ⏭️  Всего пропущено:   {stats['total_skipped']}")
        if stats["recent"]:
            click.echo(f"\n📋 Последние 10 откликов:")
            for r in stats["recent"]:
                click.echo(f"    [{r['at'][:10]}] {r['title'][:40]}... — {r['employer'][:30]}...")
    finally:
        db.close()


@cli.command(name="clear")
@click.confirmation_option(prompt="⚠️  Удалить все данные об откликах? Это нельзя отменить.")
@click.pass_context
def clear_db(ctx: click.Context) -> None:
    """Очистить базу данных откликов."""
    _load_config(ctx.obj["config_path"])

    from hh_bot.bot.state import StateDB
    db = StateDB()
    try:
        db.clear_all()
        click.echo("🗑️  База данных очищена.")
    finally:
        db.close()


@cli.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Управление конфигурацией."""
    pass


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Показать текущую конфигурацию."""
    cfg = _load_config(ctx.obj["config_path"])
    
    click.echo("\n" + "=" * 50)
    click.echo("⚙️  Текущая конфигурация")
    click.echo("=" * 50)
    
    click.echo(f"\n📧 Auth:")
    click.echo(f"  Email: {cfg.auth.email or '(не указан)'}")
    click.echo(f"  Name: {cfg.auth.name or '(не указан)'}")
    click.echo(f"  Telegram: {cfg.auth.telegram or '(не указан)'}")
    
    click.echo(f"\n🔍 Search:")
    click.echo(f"  Query: {cfg.search.query or '(не указан)'}")
    if cfg.search.area_ids:
        click.echo(f"  Areas: {cfg.search.area_ids} (многострановый поиск)")
    else:
        click.echo(f"  Area ID: {cfg.search.area_id}")
    click.echo(f"  Max pages: {cfg.search.max_pages}")
    
    click.echo(f"\n📨 Cover Letter:")
    click.echo(f"  Enabled: {cfg.cover_letter.enabled}")
    click.echo(f"  AI Enabled: {cfg.cover_letter.ai.enabled}")
    click.echo(f"  AI Provider: {cfg.cover_letter.ai.provider}")
    click.echo(f"  AI Model: {cfg.cover_letter.ai.model}")
    
    click.echo(f"\n🚫 Filters:")
    click.echo(f"  Skip tests: {cfg.filters.skip_with_tests}")
    click.echo(f"  Skip direct: {cfg.filters.skip_direct_vacancies}")
    
    click.echo(f"\n🌐 Browser:")
    click.echo(f"  Headless: {cfg.browser.headless}")
    click.echo(f"  Profile: {cfg.browser.profile_dir}")
    
    click.echo("=" * 50)


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Установить значение в конфиге (key=value)."""
    config_path = Path(ctx.obj["config_path"])
    
    if not config_path.exists():
        click.echo(f"❌ Config file not found: {config_path}", err=True)
        sys.exit(1)
    
    # Load current config
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    # Parse nested key (e.g., "search.query" or "auth.email")
    keys = key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        current = current[k]
    
    # Convert value to appropriate type
    final_value: str | int | bool | list
    if value.lower() in ("true", "yes", "on"):
        final_value = True
    elif value.lower() in ("false", "no", "off"):
        final_value = False
    elif value.isdigit():
        final_value = int(value)
    elif value.startswith("[") and value.endswith("]"):
        # Parse list [1, 2, 3]
        try:
            final_value = [int(x.strip()) for x in value[1:-1].split(",")]
        except ValueError:
            final_value = [x.strip() for x in value[1:-1].split(",")]
    else:
        final_value = value
    
    current[keys[-1]] = final_value
    
    # Save back
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    
    click.echo(f"✅ {key} = {final_value}")


@config.command(name="wizard")
@click.pass_context
def config_wizard(ctx: click.Context) -> None:
    """Интерактивный мастер настройки конфига."""
    config_path = Path(ctx.obj["config_path"])
    
    click.echo("\n" + "=" * 50)
    click.echo("🧙 Мастер настройки конфигурации")
    click.echo("=" * 50)
    
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    
    # Auth
    click.echo("\n📧 Настройка авторизации:")
    email = click.prompt("Email для входа в hh.ru", default=data.get("auth", {}).get("email", ""))
    name = click.prompt("Ваше имя (для подписи в письмах)", default=data.get("auth", {}).get("name", ""))
    telegram = click.prompt("Telegram username", default=data.get("auth", {}).get("telegram", ""))
    
    # Search
    click.echo("\n🔍 Настройка поиска:")
    query = click.prompt("Поисковый запрос по умолчанию", default=data.get("search", {}).get("query", ""))
    area_input = click.prompt("Регионы (через запятую: 113=РФ, 48=Грузия, 16=Беларусь)", 
                               default=",".join(map(str, data.get("search", {}).get("area_ids", [113]))))
    area_ids = [int(x.strip()) for x in area_input.split(",")]
    
    # Cover letter
    click.echo("\n📨 Настройка сопроводительных писем:")
    cover_letter = click.confirm("Включить сопроводительные письма?", default=data.get("cover_letter", {}).get("enabled", True))
    ai_letter = click.confirm("Использовать AI для генерации писем?", default=data.get("cover_letter", {}).get("ai", {}).get("enabled", False))
    
    if ai_letter:
        provider = click.prompt("Провайдер AI (openrouter/groq/auto)", 
                                default=data.get("cover_letter", {}).get("ai", {}).get("provider", "groq"))
        api_key = click.prompt(f"API ключ для {provider}", 
                               default=data.get("cover_letter", {}).get("ai", {}).get("api_key", ""),
                               hide_input=True)
    else:
        provider = "groq"
        api_key = ""
    
    # Filters
    click.echo("\n🚫 Настройка фильтров:")
    skip_tests = click.confirm("Пропускать вакансии с тестами?", default=data.get("filters", {}).get("skip_with_tests", True))
    skip_direct = click.confirm("Пропускать вакансии с внешними ссылками?", 
                                default=data.get("filters", {}).get("skip_direct_vacancies", True))
    
    # Build new config
    new_config = {
        "auth": {
            "email": email,
            "name": name,
            "telegram": telegram.lstrip("@"),
        },
        "browser": {
            "profile_dir": "./data/browser_profile",
            "headless": False,
        },
        "search": {
            "query": query,
            "area_ids": area_ids,
            "max_pages": 5,
        },
        "limits": {
            "max_applications_per_session": 20,
            "min_delay_between_applications": 10,
            "max_delay_between_applications": 30,
        },
        "filters": {
            "skip_with_tests": skip_tests,
            "skip_direct_vacancies": skip_direct,
            "blocked_keywords": [],
            "blocked_employers": [],
        },
        "cover_letter": {
            "enabled": cover_letter,
            "always_include": False,
            "ai": {
                "enabled": ai_letter,
                "provider": provider,
                "api_key": api_key,
                "model": "llama-3.1-8b-instant",
                "max_tokens": 500,
                "temperature": 0.7,
            }
        },
        "resume": {
            "preferred_title": "",
        }
    }
    
    # Save
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(new_config, f, allow_unicode=True, sort_keys=False)
    
    click.echo(f"\n✅ Конфигурация сохранена в {config_path}")
    click.echo("\nТеперь можно запустить: python main.py run -q 'ваш запрос'")


@cli.command()
@click.pass_context
def areas(ctx: click.Context) -> None:
    """Показать список кодов регионов."""
    click.echo("""
📍 КОДЫ СТРАН И РЕГИОНОВ:

Страны:
  113 — Россия (вся)
  16  — Беларусь
  40  — Казахстан  
  48  — Грузия
  70  — Армения
  5   — Украина (ограниченно)

Города России:
  1   — Москва
  2   — Санкт-Петербург
  88  — Казань
  62  — Новосибирск
  126 — Екатеринбург
  143 — Краснодар

Использование:
  --area-id 113        (один регион)
  --area-ids 113,48,16 (несколько регионов)
""")


@cli.command()
@click.pass_context
def test(ctx: click.Context) -> None:
    """Тестовый запуск — проверка настроек без реальных откликов."""
    click.echo("\n🧪 Тестовый запуск...")
    
    cfg = _load_config(ctx.obj["config_path"])
    
    click.echo(f"\n✅ Конфиг загружен: {ctx.obj['config_path']}")
    click.echo(f"📧 Email: {cfg.auth.email or '(не указан)'}")
    click.echo(f"🔍 Area IDs: {cfg.search.area_ids or cfg.search.area_id}")
    click.echo(f"📨 Cover letter: {'ON' if cfg.cover_letter.enabled else 'OFF'}")
    click.echo(f"🤖 AI: {'ON' if cfg.use_ai_cover_letter else 'OFF'}")
    
    # Test browser launch
    click.echo("\n🌐 Тест запуска браузера...")
    async def _test():
        from hh_bot.browser.launcher import launch_browser
        from hh_bot.auth.login import is_logged_in
        
        try:
            async with launch_browser() as (context, page):
                logged_in = await is_logged_in(page)
                if logged_in:
                    click.echo("✅ Авторизация: активна")
                else:
                    click.echo("⚠️  Авторизация: требуется вход (python main.py login)")
        except Exception as e:
            click.echo(f"❌ Ошибка браузера: {e}", err=True)
    
    asyncio.run(_test())


if __name__ == "__main__":
    cli()
