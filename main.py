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

log = get_logger(__name__)


def _load_config(config_path: str):
    from hh_bot.utils.config import load_config
    try:
        return load_config(config_path)
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


@cli.command()
@click.pass_context
def login(ctx: click.Context) -> None:
    """Войти в hh.ru через браузер (email + код из письма)."""
    cfg = _load_config(ctx.obj["config_path"])

    async def _run():
        from hh_bot.browser.launcher import launch_browser
        from hh_bot.auth.login import do_login, is_logged_in

        async with launch_browser() as (context, page):
            if await is_logged_in(page):
                click.echo("Уже авторизованы! Сессия активна.")
                return
            await do_login(page)
            click.echo("Авторизация успешна. Сессия сохранена в профиле браузера.")

    asyncio.run(_run())


@cli.command()
@click.option("--query", "-q", default="", help="Поисковый запрос (например: 'Python разработчик')")
@click.option("--dry-run", is_flag=True, help="Только парсинг без реальных откликов")
@click.pass_context
def run(ctx: click.Context, query: str, dry_run: bool) -> None:
    """Запустить сессию автоматических откликов."""
    cfg = _load_config(ctx.obj["config_path"])

    # Get query from config or prompt
    if not query:
        query = cfg.search.query
    if not query:
        query = click.prompt("Введите поисковый запрос")
    if not query.strip():
        click.echo("Поисковый запрос не может быть пустым.", err=True)
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
