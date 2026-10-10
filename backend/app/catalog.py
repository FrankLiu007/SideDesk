from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.drafts import FOLLOWUP_EN, FOLLOWUP_ZH
from app.models import Draft, Lead, Monitor, Platform, Project, Setting
from app.seed_parse import parse_seed_markdown
from app.timeutil import utcnow

THINKNOTE_SLUG = "thinknote"
THINKNOTE_BACKGROUND = """产品：ThinkNote。作者本人在公开帖子下回复。

能做的：
- 贴进 Word / WPS：公式、表格、代码、图片进桌面 Word 或 Windows 桌面 WPS 后仍可编辑，不是贴图。
- 精准追问：选中回复里的一段（含公式）再问。
- 边聊边记、一键分享：聊天时把片段存进笔记，再发成链接。

不要说成这些也能做：Google Docs、OneNote、网页版 Word、金山文档、手机版 Word。文档正文里用 Ctrl+V 会丢掉原生公式，要走「开始 → ThinkNote → 一键粘贴」。Word 加载项商店还在审核，现在用安装脚本；WPS 只支持 Windows 桌面版。

语气：先把原因说清楚，再给一个不用装插件也能用的小办法，最后用一句话说明自己是 ThinkNote 作者。Reddit 对纯广告很敏感。第一条回复不要写 thinknote.pro，安装地址只留给对方追问。"""

PLATFORMS = [
    ("reddit", "Reddit", True, False, True),
    ("youtube", "YouTube", False, True, False),
    ("bilibili", "哔哩哔哩", False, True, False),
    ("v2ex", "V2EX", False, False, False),
    ("zhihu", "知乎", False, False, False),
    ("other", "其他", False, False, False),
]

DEFAULT_MONITORS = [
    ("reddit", "keyword", "copy ChatGPT equations Word"),
    ("reddit", "keyword", "paste ChatGPT table Word formatting"),
    ("reddit", "keyword", "DeepSeek copy formula Word"),
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
    project = _ensure_thinknote(session)
    session.execute(update(Lead).where(Lead.project_id.is_(None)).values(project_id=project.id))
    session.execute(update(Monitor).where(Monitor.project_id.is_(None)).values(project_id=project.id))
    active = session.get(Setting, "active_project_id")
    if active is None or not active.value.strip():
        session.merge(Setting(key="active_project_id", value=str(project.id)))
    existing = session.scalars(select(Monitor.id).limit(1)).first()
    if existing is None:
        for platform_id, kind, content in DEFAULT_MONITORS:
            session.add(
                Monitor(project_id=project.id, platform_id=platform_id, kind=kind, content=content, enabled=True)
            )
    session.commit()


def _ensure_thinknote(session: Session) -> Project:
    project = session.scalar(select(Project).where(Project.slug == THINKNOTE_SLUG))
    if project is not None:
        return project
    project = Project(
        slug=THINKNOTE_SLUG,
        name="ThinkNote",
        background=THINKNOTE_BACKGROUND,
        followup_zh=FOLLOWUP_ZH,
        followup_en=FOLLOWUP_EN,
    )
    session.add(project)
    session.flush()
    return project


def active_project(session: Session) -> Project:
    row = session.get(Setting, "active_project_id")
    if row is not None and row.value.strip().isdigit():
        project = session.get(Project, int(row.value))
        if project is not None:
            return project
    project = session.scalar(select(Project).where(Project.slug == THINKNOTE_SLUG))
    if project is None:
        project = session.scalar(select(Project).order_by(Project.id))
    if project is None:
        project = _ensure_thinknote(session)
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
