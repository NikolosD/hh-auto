#!/usr/bin/env python3
"""hh.ru Auto-Apply Bot CLI."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

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
        # Интерактивный ввод
        email = click.prompt("Введите email для входа в hh.ru")
    elif email:
        # Используем email из аргумента командной строки
        pass
    else:
        # Используем email из конфига
        email = cfg.auth.email
    
    if not email:
        click.echo("Ошибка: email не указан. Используйте --email или добавьте в config.yaml", err=True)
        sys.exit(1)

    async def _run():
        from hh_bot.browser.launcher import launch_browser
        from hh_bot.auth.login import do_login_with_email, is_logged_in

        async with launch_browser() as (context, page):
            if await is_logged_in(page):
                click.echo("Уже авторизованы! Сессия активна.")
                return
            await do_login_with_email(page, email)
            click.echo("Авторизация успешна. Сессия сохранена в профиле браузера.")

    asyncio.run(_run())


@cli.command()
@click.option("--query", "-q", default="", help="Поисковый запрос (например: 'Python разработчик')")
@click.option("--area-id", "-a", type=int, help="Регион (113=Россия, 1=Москва, 2=СПб)")
@click.option("--max-pages", "-p", type=int, help="Макс. страниц поиска")
@click.option("--max-apps", "-m", type=int, help="Макс. откликов за сессию")
@click.option("--skip-tests/--no-skip-tests", default=None, help="Пропускать вакансии с тестовым заданием")
@click.option("--skip-direct/--no-skip-direct", default=None, help="Пропускать вакансии с внешней ссылкой")
@click.option("--cover-letter/--no-cover-letter", default=None, help="Добавлять сопроводительное письмо")
@click.option("--headless", is_flag=True, help="Запускать браузер в фоновом режиме")
@click.option("--dry-run", is_flag=True, help="Только парсинг без реальных откликов")
@click.option("--log-level", "-l", default="INFO", help="Уровень логирования (DEBUG/INFO/WARNING/ERROR)")
@click.pass_context
def run(
    ctx: click.Context,
    query: str,
    area_id: int | None,
    max_pages: int | None,
    max_apps: int | None,
    skip_tests: bool | None,
    skip_direct: bool | None,
    cover_letter: bool | None,
    headless: bool,
    dry_run: bool,
    log_level: str,
) -> None:
    """Запустить сессию автоматических откликов."""
    # Собираем CLI-опции для переопределения конфига
    cli_opts = {}
    if area_id is not None:
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
    if headless:
        cli_opts["browser.headless"] = True
    
    # Настройка логирования
    setup_logging(log_level)
    
    cfg = _load_config(ctx.obj["config_path"], cli_opts)

    # === ИНТЕРАКТИВНЫЙ ВВОД ДАННЫХ ===
    click.echo("\n" + "=" * 50)
    click.echo("🤖 Настройка сессии откликов")
    click.echo("=" * 50)
    
    # 1. Поисковый запрос
    if not query:
        query = cfg.search.query
    if not query:
        query = click.prompt("🔍 Введите поисковый запрос (например: Python разработчик)")
    if not query.strip():
        click.echo("❌ Поисковый запрос не может быть пустым.", err=True)
        sys.exit(1)
    click.echo(f"✅ Запрос: {query}")
    
    # 2. Email для входа (если не залогинены)
    email = cfg.auth.email
    if not email:
        email = click.prompt("📧 Введите email для входа в hh.ru")
        if email:
            # Сохраняем во временном конфиге для сессии
            cli_opts["auth.email"] = email
            cfg = _load_config(ctx.obj["config_path"], cli_opts)
    
    # 3. Telegram для сопроводительных писем
    telegram = click.prompt(
        "📱 Введите Telegram для сопроводительных писем (опционально)",
        default="",
        show_default=False
    )
    if telegram:
        # Очищаем от @ и https://t.me/
        telegram = telegram.strip()
        if telegram.startswith("https://t.me/"):
            telegram = telegram.replace("https://t.me/", "")
        elif telegram.startswith("t.me/"):
            telegram = telegram.replace("t.me/", "")
        if telegram.startswith("@"):
            telegram = telegram[1:]
        cli_opts["auth.telegram"] = telegram
        cfg = _load_config(ctx.obj["config_path"], cli_opts)
        click.echo(f"✅ Telegram: @{telegram}")
    
    click.echo("=" * 50 + "\n")

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
                    # Just list vacancies without applying
                    from hh_bot.scraper.search import search_vacancies
                    from hh_bot.auth.login import ensure_logged_in
                    await ensure_logged_in(page)
                    cards = await search_vacancies(page, query, cfg.search.area_id, 0)
                    click.echo(f"\nНайдено вакансий на 1-й странице: {len(cards)}")
                    for c in cards[:10]:
                        click.echo(f"  [{c.vacancy_id}] {c.title} — {c.employer}")
                    return

                stats = await run_session(page, query, db)
                click.echo("\n" + "=" * 50)
                click.echo(f"Сессия завершена:")
                click.echo(f"  Откликнулся:  {stats.applied}")
                click.echo(f"  Пропущено:    {stats.skipped}")
                click.echo(f"  Ошибки:       {stats.errors}")
                if stats.skip_reasons:
                    click.echo("  Причины пропуска:")
                    for reason, count in sorted(stats.skip_reasons.items(), key=lambda x: -x[1]):
                        click.echo(f"    {reason}: {count}")
        finally:
            db.close()

    asyncio.run(_run())


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Показать статистику откликов из базы данных."""
    _load_config(ctx.obj["config_path"])

    from hh_bot.bot.state import StateDB
    db = StateDB()
    try:
        stats = db.get_stats()
        click.echo(f"\nСтатистика откликов:")
        click.echo(f"  Всего откликнулся: {stats['total_applied']}")
        click.echo(f"  Всего пропущено:   {stats['total_skipped']}")
        if stats["recent"]:
            click.echo(f"\nПоследние 10 откликов:")
            for r in stats["recent"]:
                click.echo(f"  [{r['at'][:10]}] {r['title']} — {r['employer']}")
    finally:
        db.close()


@cli.command()
@click.confirmation_option(prompt="Удалить все данные об откликах? Это нельзя отменить.")
@click.pass_context
def clear(ctx: click.Context) -> None:
    """Очистить базу данных откликов."""
    _load_config(ctx.obj["config_path"])

    from hh_bot.bot.state import StateDB
    db = StateDB()
    try:
        db.clear_all()
        click.echo("База данных очищена.")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
