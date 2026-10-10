from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Draft, Lead, Monitor, Platform, Project, Setting
from app.seed_parse import parse_seed_markdown
from app.timeutil import utcnow

DEFAULT_SLUG = "default"

PLATFORMS = [
    ("reddit", "Reddit", True, False, True),
    ("youtube", "YouTube", False, True, False),
    ("bilibili", "哔哩哔哩", False, True, False),
    ("v2ex", "V2EX", False, False, False),
    ("zhihu", "知乎", False, False, False),
    ("other", "其他", False, False, False),
]


def ensure_catalog(session: Session) -> None:
    for platform_id, name, can_search, can_watch, can_refresh in PLATFORMS:
        row = session.get(Platform, platform_id)
        if row is None:
            session.add(
                Platform(
                    id=platform_id,
                    name=name,
                    can_search=can_search,
                    can_watch=can_watch,
                    can_refresh_reply=can_refresh,
                )
            )
        else:
            row.name = name
            row.can_search = can_search
            row.can_watch = can_watch
            row.can_refresh_reply = can_refresh
    project = _ensure_default(session)
    session.execute(update(Lead).where(Lead.project_id.is_(None)).values(project_id=project.id))
    session.execute(update(Monitor).where(Monitor.project_id.is_(None)).values(project_id=project.id))
    active = session.get(Setting, "active_project_id")
    if active is None or not active.value.strip():
        session.merge(Setting(key="active_project_id", value=str(project.id)))
    session.commit()


def _ensure_default(session: Session) -> Project:
    project = session.scalar(select(Project).order_by(Project.id).limit(1))
    if project is not None:
        return project
    project = Project(slug=DEFAULT_SLUG, name="默认", background="", followup_zh="", followup_en="")
    session.add(project)
    session.flush()
    return project


def active_project(session: Session) -> Project:
    row = session.get(Setting, "active_project_id")
    if row is not None and row.value.strip().isdigit():
        project = session.get(Project, int(row.value))
        if project is not None:
            return project
    project = session.scalar(select(Project).order_by(Project.id))
    if project is None:
        project = _ensure_default(session)
    session.merge(Setting(key="active_project_id", value=str(project.id)))
    session.commit()
    return project


def seed_leads(session: Session, markdown: str, project_id: int) -> int:
    added = 0
    now = utcnow().replace(tzinfo=None)
    for item in parse_seed_markdown(markdown):
        exists = session.scalar(
            select(Lead).where(Lead.platform_id == item.platform_id, Lead.external_id == item.external_id)
        )
        if exists:
            continue
        lead = Lead(
            project_id=project_id,
            platform_id=item.platform_id,
            external_id=item.external_id,
            url=item.url,
            title=item.title,
            excerpt=item.excerpt,
            discovered_at=now,
            status="replied" if item.done else ("drafted" if item.draft else "unread"),
        )
        session.add(lead)
        session.flush()
        if item.draft:
            session.add(Draft(lead_id=lead.id, body=item.draft, updated_at=now))
        added += 1
    session.commit()
    return added
