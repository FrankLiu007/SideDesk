from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Lead, MyReply
from app.platforms.base import ParsedLink
from app.timeutil import utcnow


def track_url(session: Session, project_id: int, parsed: ParsedLink) -> bool:
    """Remember a post as unreplied, or a comment as a reply on that post. Returns True if the lead is new."""
    lead = session.scalar(
        select(Lead).where(Lead.platform_id == parsed.platform_id, Lead.external_id == parsed.external_id)
    )
    created = lead is None
    now = utcnow().replace(tzinfo=None)
    if lead is None:
        lead = Lead(
            project_id=project_id,
            platform_id=parsed.platform_id,
            external_id=parsed.external_id,
            url=parsed.post_url,
            title="",
            excerpt="",
            discovered_at=now,
            status="replied" if parsed.comment_id else "unread",
        )
        session.add(lead)
        session.flush()
    if not parsed.comment_id:
        return created
    existing = session.scalar(
        select(MyReply).where(
            MyReply.lead_id == lead.id,
            or_(
                MyReply.external_comment_id == parsed.comment_id,
                MyReply.comment_url == parsed.canonical_url,
            ),
        )
    )
    if existing is None:
        session.add(
            MyReply(
                lead_id=lead.id,
                body="",
                comment_url=parsed.canonical_url,
                external_comment_id=parsed.comment_id,
                posted_at=now,
            )
        )
    if lead.status in {"unread", "drafted", "skipped"}:
        lead.status = "replied"
    return created
