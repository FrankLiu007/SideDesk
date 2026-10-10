from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.timeutil import utcnow


class Base(DeclarativeBase):
    pass


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    can_search: Mapped[bool] = mapped_column(Boolean, default=False)
    can_watch: Mapped[bool] = mapped_column(Boolean, default=False)
    can_refresh_reply: Mapped[bool] = mapped_column(Boolean, default=False)

    monitors: Mapped[list["Monitor"]] = relationship(back_populates="platform")
    leads: Mapped[list["Lead"]] = relationship(back_populates="platform")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    background: Mapped[str] = mapped_column(Text, default="")
    followup_zh: Mapped[str] = mapped_column(Text, default="")
    followup_en: Mapped[str] = mapped_column(Text, default="")

    monitors: Mapped[list["Monitor"]] = relationship(back_populates="project")
    leads: Mapped[list["Lead"]] = relationship(back_populates="project")


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    platform_id: Mapped[str] = mapped_column(ForeignKey("platforms.id"))
    kind: Mapped[str] = mapped_column(String(16))  # keyword | url
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cursor_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    platform: Mapped[Platform] = relationship(back_populates="monitors")
    project: Mapped[Project] = relationship(back_populates="monitors")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("platform_id", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    platform_id: Mapped[str] = mapped_column(ForeignKey("platforms.id"))
    external_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="unread")
    chat_summary: Mapped[str] = mapped_column(Text, default="")
    chat_summary_until_id: Mapped[int] = mapped_column(Integer, default=0)

    platform: Mapped[Platform] = relationship(back_populates="leads")
    project: Mapped[Project] = relationship(back_populates="leads")
    draft: Mapped["Draft | None"] = relationship(back_populates="lead", uselist=False)
    replies: Mapped[list["MyReply"]] = relationship(back_populates="lead")
    messages: Mapped[list["DraftMessage"]] = relationship(back_populates="lead")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), unique=True)
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="draft")


class DraftMessage(Base):
    __tablename__ = "draft_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    role: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="messages")


class MyReply(Base):
    __tablename__ = "my_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    body: Mapped[str] = mapped_column(Text, default="")
    comment_url: Mapped[str] = mapped_column(Text, default="")
    external_comment_id: Mapped[str] = mapped_column(String(128), default="")
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_count: Mapped[int] = mapped_column(Integer, default=0)
    child_ids: Mapped[str] = mapped_column(Text, default="[]")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped[Lead] = relationship(back_populates="replies")
    events: Mapped[list["ReplyEvent"]] = relationship(back_populates="reply")


class ReplyEvent(Base):
    __tablename__ = "reply_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reply_id: Mapped[int] = mapped_column(ForeignKey("my_replies.id"))
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)

    reply: Mapped[MyReply] = relationship(back_populates="events")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class AiSource(Base):
    __tablename__ = "ai_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(512), unique=True)
    api_key: Mapped[str] = mapped_column(Text, default="")
    models_json: Mapped[str] = mapped_column(Text, default="[]")
