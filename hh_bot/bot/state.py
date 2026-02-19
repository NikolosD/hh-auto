from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from hh_bot.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_DB_PATH = "./data/applied.db"


class StateDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_vacancies (
                vacancy_id   TEXT PRIMARY KEY,
                title        TEXT,
                employer     TEXT,
                url          TEXT,
                applied_at   TEXT,
                status       TEXT DEFAULT 'applied'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS skipped_vacancies (
                vacancy_id   TEXT PRIMARY KEY,
                title        TEXT,
                employer     TEXT,
                url          TEXT,
                skipped_at   TEXT,
                reason       TEXT
            )
        """)
        self._conn.commit()

    def has_applied(self, vacancy_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM applied_vacancies WHERE vacancy_id = ?", (vacancy_id,)
        )
        return cur.fetchone() is not None

    def has_seen(self, vacancy_id: str) -> bool:
        """Return True if vacancy was already applied or skipped."""
        if self.has_applied(vacancy_id):
            return True
        cur = self._conn.execute(
            "SELECT 1 FROM skipped_vacancies WHERE vacancy_id = ?", (vacancy_id,)
        )
        return cur.fetchone() is not None

    def mark_applied(
        self,
        vacancy_id: str,
        title: str = "",
        employer: str = "",
        url: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO applied_vacancies
                (vacancy_id, title, employer, url, applied_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (vacancy_id, title, employer, url, datetime.utcnow().isoformat()),
        )
        self._conn.commit()
        log.info("Marked as applied", vacancy_id=vacancy_id, title=title)

    def mark_skipped(
        self,
        vacancy_id: str,
        title: str = "",
        employer: str = "",
        url: str = "",
        reason: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO skipped_vacancies
                (vacancy_id, title, employer, url, skipped_at, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, title, employer, url, datetime.utcnow().isoformat(), reason),
        )
        self._conn.commit()
        log.debug("Marked as skipped", vacancy_id=vacancy_id, reason=reason)

    def get_stats(self) -> dict:
        applied = self._conn.execute("SELECT COUNT(*) FROM applied_vacancies").fetchone()[0]
        skipped = self._conn.execute("SELECT COUNT(*) FROM skipped_vacancies").fetchone()[0]
        recent = self._conn.execute(
            "SELECT vacancy_id, title, employer, applied_at FROM applied_vacancies "
            "ORDER BY applied_at DESC LIMIT 10"
        ).fetchall()
        return {
            "total_applied": applied,
            "total_skipped": skipped,
            "recent": [
                {"id": r[0], "title": r[1], "employer": r[2], "at": r[3]}
                for r in recent
            ],
        }

    def clear_all(self) -> None:
        self._conn.execute("DELETE FROM applied_vacancies")
        self._conn.execute("DELETE FROM skipped_vacancies")
        self._conn.commit()
        log.info("State cleared")

    def close(self) -> None:
        self._conn.close()
