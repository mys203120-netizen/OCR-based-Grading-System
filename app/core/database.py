from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


@dataclass(frozen=True)
class Database:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    async def init(self) -> None:
        from app.models import Base

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if self.settings.database_url.startswith("sqlite"):
                await _ensure_sqlite_columns(conn)

    async def dispose(self) -> None:
        await self.engine.dispose()


def create_database(settings: Settings) -> Database:
    engine = create_async_engine(settings.database_url, echo=settings.sql_echo, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return Database(settings=settings, engine=engine, sessionmaker=sessionmaker)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    database: Database = request.app.state.db
    async with database.sessionmaker() as session:
        yield session


async def _ensure_sqlite_columns(conn) -> None:
    table_columns = {
        "students": {
            "instructor_id": "VARCHAR(36)",
            "parent_phone": "VARCHAR(40)",
            "student_phone": "VARCHAR(40)",
            "level_band": "VARCHAR(40)",
            "grade_level": "VARCHAR(40)",
            "grade_anchor_level": "INTEGER",
            "grade_anchor_year": "INTEGER",
            "school": "VARCHAR(120)",
            "memo": "TEXT",
            "is_active": "BOOLEAN DEFAULT 1 NOT NULL",
            "deleted_at": "DATETIME",
        },
        "class_rooms": {
            "class_kind": "VARCHAR(30) DEFAULT 'manual' NOT NULL",
            "grade_level_code": "INTEGER",
        },
        "exams": {
            "class_id": "VARCHAR(36)",
            "exam_date": "DATE",
        },
        "submissions": {
            "student_match_status": "VARCHAR(30) DEFAULT 'unmatched' NOT NULL",
            "student_candidates_json": "TEXT",
        },
        "sms_messages": {
            "channel": "VARCHAR(30) DEFAULT 'kakao' NOT NULL",
            "provider": "VARCHAR(50) DEFAULT 'solapi_kakao' NOT NULL",
            "provider_payload_json": "TEXT",
        },
    }
    for table_name, columns in table_columns.items():
        existing_rows = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        existing = {row[1] for row in existing_rows}
        for column_name, column_sql in columns.items():
            if column_name not in existing:
                await conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                )
