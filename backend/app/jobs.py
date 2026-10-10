import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import THINKNOTE_SLUG, active_project, seed_leads
from app.config import settings
from app.models import Draft, DraftMessage, Lead, Monitor, MyReply, Project, ReplyEvent
from app.platforms import adapter_for, reply_adapter_for
from app.platforms.base import SearchAdapter
from app.platforms.parse import parse_link
from app.reddit import RedditClient, RedditError, RedditNotConfigured
from app.timeutil import as_utc, utcnow
from app.tracking import track_url

OPEN_STATUSES = ("unread", "drafted")

reddit = RedditClient()


def import_seed_file(session: Session, path: Path | None = None) -> int:
    seed_path = path or Path(settings.seed_path)
    if not seed_path.is_file():
        return 0
    if session.scalar(select(Lead.id).limit(1)) is not None:
        return 0
    project = session.scalar(select(Project).where(Project.slug == THINKNOTE_SLUG))
    if project is None:
        return 0
    return seed_leads(session, seed_path.read_text(encoding="utf-8"), project.id)


def run_monitors(session: Session) -> dict:
    found = 0
    removed = 0
    errors: list[str] = []
    now = utcnow().replace(tzinfo=None)
    project = active_project(session)
    monitors = session.scalars(
        select(Monitor).where(Monitor.enabled.is_(True), Monitor.project_id == project.id)
    ).all()
    purged: set[str] = set()
    for monitor in monitors:
        platform = monitor.platform
        monitor.last_run_at = now
        try:
            if monitor.kind == "keyword" and platform.can_search:
                adapter = adapter_for(platform.id, reddit)
                if adapter is None:
                    monitor.last_error = "这个平台还没有搜索适配"
                    continue
                if platform.id not in purged:
                    removed += purge_unanswerable(session, project.id, adapter)
                    purged.add(platform.id)
                found += _ingest(session, monitor, adapter)
            elif monitor.kind == "url":
                parsed = parse_link(monitor.content)
                if monitor.platform_id != parsed.platform_id:
                    monitor.platform_id = parsed.platform_id
                if track_url(session, monitor.project_id, parsed):
                    found += 1
                monitor.last_error = None
            else:
                monitor.last_error = "这个监控还不能自动跑"
        except (RedditNotConfigured, RedditError) as exc:
            monitor.last_error = str(exc)
            errors.append(f"{platform.name}: {exc}")
        except Exception as exc:
            monitor.last_error = str(exc)[:500]
            errors.append(f"{platform.name}: {exc}")
    session.commit()
    return {"leads_found": found, "leads_removed": removed, "monitor_errors": errors}


def purge_unanswerable(session: Session, project_id: int, adapter: SearchAdapter) -> int:
    """Delete open leads the platform can no longer accept a reply on."""
    leads = session.scalars(
        select(Lead).where(
            Lead.project_id == project_id,
            Lead.platform_id == adapter.platform_id,
            Lead.status.in_(OPEN_STATUSES),
        )
    ).all()
    if not leads:
        return 0
    gone = adapter.unanswerable_ids([lead.external_id for lead in leads if lead.external_id])
    removed = 0
    for lead in leads:
        if lead.external_id not in gone:
            continue
        if session.scalar(select(MyReply.id).where(MyReply.lead_id == lead.id)):
            continue
        delete_lead(session, lead)
        removed += 1
    if removed:
        session.flush()
    return removed


def delete_lead(session: Session, lead: Lead) -> None:
    draft = session.scalar(select(Draft).where(Draft.lead_id == lead.id))
    if draft is not None:
        session.delete(draft)
    for message in session.scalars(select(DraftMessage).where(DraftMessage.lead_id == lead.id)).all():
        session.delete(message)
    replies = session.scalars(select(MyReply).where(MyReply.lead_id == lead.id)).all()
    for reply in replies:
        for event in session.scalars(select(ReplyEvent).where(ReplyEvent.reply_id == reply.id)).all():
            session.delete(event)
        session.delete(reply)
    session.delete(lead)


def _ingest(session: Session, monitor: Monitor, adapter: SearchAdapter) -> int:
    since = as_utc(monitor.cursor_at) if monitor.cursor_at else None
    batch = adapter.search(monitor.content, since)
    added = 0
    newest = monitor.cursor_at
    if batch.newest is not None and (newest is None or batch.newest > newest):
        newest = batch.newest
    for hit in batch.hits:
        exists = session.scalar(
            select(Lead).where(Lead.platform_id == adapter.platform_id, Lead.external_id == hit.external_id)
        )
        if exists:
            continue
        session.add(
            Lead(
                project_id=monitor.project_id,
                platform_id=adapter.platform_id,
                external_id=hit.external_id,
                url=hit.url,
                title=hit.title,
                excerpt=hit.excerpt,
                author=hit.author,
                discovered_at=hit.created_at,
                status="unread",
            )
        )
        session.flush()
        added += 1
    monitor.cursor_at = newest
    monitor.last_error = None
    return added


def refresh_replies(session: Session) -> dict:
    from app.diff import diff_reply
    from app.models import MyReply, ReplyEvent

    checked = 0
    new_events = 0
    now = utcnow().replace(tzinfo=None)
    project = active_project(session)
    replies = session.scalars(select(MyReply).join(MyReply.lead).where(Lead.project_id == project.id)).all()
    for reply in replies:
        adapter = reply_adapter_for(reply.lead.platform_id, reddit)
        if adapter is None:
            reply.last_checked_at = now
            reply.last_error = "这个平台还不能自动看追问"
            checked += 1
            continue
        if not adapter.configured():
            reply.last_error = "还没有配置 Reddit 密钥"
            continue
        try:
            snap = adapter.refresh_reply(reply.comment_url)
        except RedditError as exc:
            reply.last_checked_at = now
            reply.last_error = str(exc)
            checked += 1
            continue
        except Exception as exc:
            reply.last_error = str(exc)[:500]
            checked += 1
            continue
        old_ids = json.loads(reply.child_ids or "[]")
        events = diff_reply(
            has_baseline=reply.last_checked_at is not None,
            old_score=reply.score,
            old_child_ids=old_ids,
            old_deleted=reply.deleted,
            snap=snap,
        )
        for kind, detail in events:
            session.add(ReplyEvent(reply_id=reply.id, kind=kind, detail=detail, created_at=now))
            new_events += 1
        reply.score = snap.score
        reply.child_ids = json.dumps(snap.child_ids)
        reply.child_count = len(snap.child_ids)
        reply.deleted = snap.deleted
        reply.last_checked_at = now
        reply.last_error = None
        checked += 1
    session.commit()
    return {"replies_checked": checked, "new_events": new_events}
