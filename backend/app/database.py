import json
from collections.abc import Iterator

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import AiSource, Base, Setting

settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_column("leads", "project_id", "INTEGER")
    _add_column("leads", "chat_summary", "TEXT DEFAULT ''")
    _add_column("leads", "chat_summary_until_id", "INTEGER DEFAULT 0")
    _add_column("draft_messages", "reasoning", "TEXT DEFAULT ''")
    _add_column("monitors", "project_id", "INTEGER")
    _migrate_ai_sources()


def _migrate_ai_sources() -> None:
    from app.ai import source_label

    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(AiSource)) or 0
        if count:
            return
        rows = {row.key: row.value for row in session.scalars(select(Setting)).all()}
        base = (rows.get("ai_base_url") or "").strip().rstrip("/")
        key = (rows.get("ai_api_key") or "").strip()
        if not base and not key:
            return
        listed = (rows.get("ai_model_list_base") or "").strip().rstrip("/")
        models_json = (rows.get("ai_model_list") or "[]") if listed == base else "[]"
        try:
            parsed = json.loads(models_json)
        except ValueError:
            parsed = None
        if not isinstance(parsed, list):
            models_json = "[]"
        source = AiSource(name=source_label(base), base_url=base, api_key=key, models_json=models_json)
        session.add(source)
        session.flush()
        session.merge(Setting(key="ai_source_id", value=str(source.id)))
        for old in ("ai_base_url", "ai_api_key", "ai_model_list", "ai_model_list_base"):
            row = session.get(Setting, old)
            if row is not None:
                session.delete(row)
        session.commit()


def _add_column(table: str, column: str, ddl: str) -> None:
    names = inspect(engine).get_table_names()
    if table not in names:
        return
    existing = {item["name"] for item in inspect(engine).get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
