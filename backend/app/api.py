import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.ai import AiError, complete_parts, iter_parts, list_models, probe, source_label
from app.catalog import active_project
from app.chat import (
    MAX_STORED,
    Turn,
    apply_adopted,
    build_model_messages,
    fold_summary,
    post_block,
    slide_window,
)
from app.database import get_session
from app.platforms.parse import parse_link
from app.jobs import delete_lead, reddit, refresh_replies, run_monitors
from app.reddit import FRAME_BLOCKED, RedditError
from app.models import AiSource, Draft, DraftMessage, Lead, Monitor, MyReply, Platform, Project, ReplyEvent, Setting
from app.schemas import (
    STATUSES,
    AdoptIn,
    AiSelectionIn,
    AiSourceIn,
    AiSourcePatch,
    AiTestIn,
    ChatIn,
    DraftIn,
    LeadIn,
    MonitorIn,
    MonitorPatch,
    ProjectIn,
    ProjectPatch,
    ReplyIn,
    StatusIn,
)
from app.timeutil import iso, utcnow
from app.tracking import track_url

router = APIRouter(prefix="/api")


def _lead_query():
    return select(Lead).options(
        joinedload(Lead.platform),
        joinedload(Lead.project),
        selectinload(Lead.draft),
        selectinload(Lead.replies),
    )


def _lead_json(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "platform_id": lead.platform_id,
        "platform_name": lead.platform.name,
        "url": lead.url,
        "title": lead.title,
        "excerpt": lead.excerpt,
        "author": lead.author,
        "discovered_at": iso(lead.discovered_at),
        "status": lead.status,
        "draft": lead.draft.body if lead.draft else "",
        "reply_count": len(lead.replies),
        "project_id": lead.project_id,
        "project_name": lead.project.name if lead.project else "",
        "followup_zh": lead.project.followup_zh if lead.project else "",
        "followup_en": lead.project.followup_en if lead.project else "",
    }


def _queue_json(lead: Lead) -> dict:
    data = _lead_json(lead)
    unseen = []
    urls: list[str] = []
    for reply in lead.replies:
        if reply.comment_url:
            urls.append(reply.comment_url)
        for event in reply.events:
            if not event.seen:
                unseen.append(event)
    unseen.sort(key=lambda item: item.created_at, reverse=True)
    data["unseen"] = [
        {"id": event.id, "kind": event.kind, "detail": event.detail, "created_at": iso(event.created_at)}
        for event in unseen
    ]
    data["comment_urls"] = urls
    return data


def _needs_reply(lead: Lead) -> bool:
    return not lead.replies and lead.status in {"unread", "drafted"}


def _is_followup(lead: Lead) -> bool:
    return bool(lead.replies) or lead.status == "replied"


def _reply_json(reply: MyReply) -> dict:
    unseen = [event for event in reply.events if not event.seen]
    return {
        "id": reply.id,
        "lead_id": reply.lead_id,
        "lead_title": reply.lead.title,
        "lead_url": reply.lead.url,
        "platform_name": reply.lead.platform.name,
        "body": reply.body,
        "comment_url": reply.comment_url,
        "posted_at": iso(reply.posted_at),
        "last_checked_at": iso(reply.last_checked_at),
        "score": reply.score,
        "child_count": reply.child_count,
        "deleted": reply.deleted,
        "last_error": reply.last_error,
        "unseen": [
            {"id": event.id, "kind": event.kind, "detail": event.detail, "created_at": iso(event.created_at)}
            for event in sorted(unseen, key=lambda item: item.created_at, reverse=True)
        ],
    }


@router.get("/settings/ai")
def ai_settings_view(session: Session = Depends(get_session)) -> dict:
    return _ai_view(session)


@router.put("/settings/ai")
def ai_settings_save(payload: AiSelectionIn, session: Session = Depends(get_session)) -> dict:
    source = _source_or_404(session, payload.source_id)
    model = payload.model.strip()
    if not model:
        raise HTTPException(400, "先填模型")
    allowed = set(_model_names(source.models_json))
    active_id, active_model = _active_choice(session)
    if active_id == source.id and active_model:
        allowed.add(active_model)
    if model not in allowed:
        raise HTTPException(400, "先获取这个来源的模型")
    _save_setting(session, "ai_source_id", str(source.id))
    _save_setting(session, "ai_model", model)
    session.commit()
    return _ai_view(session)


@router.post("/settings/ai/sources", status_code=201)
def create_ai_source(payload: AiSourceIn, session: Session = Depends(get_session)) -> dict:
    base = _normalize_base(payload.base_url)
    if not base:
        raise HTTPException(400, "先填模型地址")
    key = payload.api_key.strip()
    if not key:
        raise HTTPException(400, "先填密钥")
    if _source_by_base(session, base) is not None:
        raise HTTPException(400, "这个地址已经有了")
    source = AiSource(
        name=(payload.name.strip() or source_label(base)),
        base_url=base,
        api_key=key,
        models_json="[]",
    )
    session.add(source)
    session.commit()
    return _ai_view(session)


@router.patch("/settings/ai/sources/{source_id}")
def update_ai_source(source_id: int, payload: AiSourcePatch, session: Session = Depends(get_session)) -> dict:
    source = _source_or_404(session, source_id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, "先写来源名称")
        source.name = name
    if payload.base_url is not None:
        base = _normalize_base(payload.base_url)
        if not base:
            raise HTTPException(400, "先填模型地址")
        other = _source_by_base(session, base)
        if other is not None and other.id != source.id:
            raise HTTPException(400, "这个地址已经有了")
        if base != source.base_url:
            source.base_url = base
            source.models_json = "[]"
            active_id, _active_model = _active_choice(session)
            if active_id == source.id:
                _save_setting(session, "ai_model", "")
    if payload.api_key is not None and payload.api_key.strip():
        source.api_key = payload.api_key.strip()
    session.commit()
    return _ai_view(session)


@router.delete("/settings/ai/sources/{source_id}")
def delete_ai_source(source_id: int, session: Session = Depends(get_session)) -> dict:
    source = _source_or_404(session, source_id)
    active_id, _active_model = _active_choice(session)
    session.delete(source)
    if active_id == source.id:
        _save_setting(session, "ai_source_id", "")
        _save_setting(session, "ai_model", "")
    session.commit()
    return _ai_view(session)


@router.post("/settings/ai/sources/{source_id}/models")
def ai_source_models(source_id: int, session: Session = Depends(get_session)) -> dict:
    source = _source_or_404(session, source_id)
    _require_source_credentials(source)
    try:
        names = list_models(source.base_url, source.api_key)
    except AiError as exc:
        raise HTTPException(502, str(exc)) from exc
    source.models_json = json.dumps(names, ensure_ascii=False)
    session.commit()
    return {"models": names}


@router.post("/settings/ai/sources/{source_id}/test")
def ai_source_test(source_id: int, payload: AiTestIn, session: Session = Depends(get_session)) -> dict:
    source = _source_or_404(session, source_id)
    _require_source_credentials(source)
    model = _model_for_test(session, source, payload.model)
    try:
        reply = probe(source.base_url, source.api_key, model)
    except AiError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "model": model, "reply": reply[:200]}


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)) -> list[dict]:
    current = active_project(session)
    rows = session.scalars(select(Project).order_by(Project.id)).all()
    return [_project_json(row, current.id) for row in rows]


@router.post("/projects", status_code=201)
def create_project(payload: ProjectIn, session: Session = Depends(get_session)) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "先写项目名称")
    project = Project(
        slug=_unique_slug(session, name),
        name=name,
        background=payload.background.strip(),
        followup_zh=payload.followup_zh.strip(),
        followup_en=payload.followup_en.strip(),
    )
    session.add(project)
    session.flush()
    _save_setting(session, "active_project_id", str(project.id))
    session.commit()
    return _project_json(project, project.id)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectPatch, session: Session = Depends(get_session)) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "没有这个项目")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, "先写项目名称")
        project.name = name
    if payload.background is not None:
        project.background = payload.background.strip()
    if payload.followup_zh is not None:
        project.followup_zh = payload.followup_zh.strip()
    if payload.followup_en is not None:
        project.followup_en = payload.followup_en.strip()
    session.commit()
    current = active_project(session)
    return _project_json(project, current.id)


@router.post("/projects/{project_id}/activate")
def activate_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "没有这个项目")
    _save_setting(session, "active_project_id", str(project.id))
    session.commit()
    return _project_json(project, project.id)


@router.get("/platforms")
def platforms(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(Platform).order_by(Platform.id)).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "can_search": row.can_search,
            "can_watch": row.can_watch,
            "can_refresh_reply": row.can_refresh_reply,
        }
        for row in rows
    ]


@router.get("/today")
def today(session: Session = Depends(get_session)) -> dict:
    project = active_project(session)
    leads = session.scalars(
        _lead_query()
        .options(selectinload(Lead.replies).selectinload(MyReply.events))
        .where(Lead.project_id == project.id, Lead.status != "skipped")
    ).unique().all()
    needs = [lead for lead in leads if _needs_reply(lead)]
    followups = [lead for lead in leads if _is_followup(lead)]
    needs.sort(key=_needs_order)
    followups.sort(key=_follow_order)
    return {
        "needs_reply": [_queue_json(lead) for lead in needs],
        "followups": [_queue_json(lead) for lead in followups],
    }


def _needs_order(lead: Lead) -> tuple:
    rank = 0 if lead.status == "drafted" else 1
    stamp = lead.discovered_at.timestamp() if lead.discovered_at else 0
    return (rank, -stamp)


def _follow_order(lead: Lead) -> tuple:
    unseen = any(not event.seen for reply in lead.replies for event in reply.events)
    moments = [reply.posted_at for reply in lead.replies if reply.posted_at]
    latest = max(moments) if moments else lead.discovered_at
    stamp = latest.timestamp() if latest else 0
    return (0 if unseen else 1, 0 if lead.replies else 1, -stamp)


@router.post("/refresh")
def refresh_now(session: Session = Depends(get_session)) -> dict:
    monitors = run_monitors(session)
    replies = refresh_replies(session)
    return {**monitors, **replies}


@router.get("/leads")
def list_leads(
    status: str | None = None,
    platform: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    project = active_project(session)
    query = _lead_query().where(Lead.project_id == project.id).order_by(Lead.discovered_at.desc())
    if status:
        query = query.where(Lead.status == status)
    if platform:
        query = query.where(Lead.platform_id == platform)
    return [_lead_json(lead) for lead in session.scalars(query).unique().all()]


@router.get("/leads/match")
def match_lead(url: str, session: Session = Depends(get_session)) -> dict:
    cleaned = url.strip()
    if not cleaned:
        raise HTTPException(400, "缺少链接")
    parsed = parse_link(cleaned)
    lead = session.scalar(
        _lead_query().where(Lead.platform_id == parsed.platform_id, Lead.external_id == parsed.external_id)
    )
    on_comment = bool(parsed.comment_id)
    return {
        "lead": _lead_json(lead) if lead else None,
        "on_comment": on_comment,
        "comment_url": cleaned if on_comment else "",
    }


@router.post("/leads", status_code=201)
def create_lead(payload: LeadIn, session: Session = Depends(get_session)) -> dict:
    project = active_project(session)
    parsed = parse_link(payload.url)
    platform_id = payload.platform_id or parsed.platform_id
    external_id = parsed.external_id
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(404, "没有这个平台")
    if session.scalar(select(Lead).where(Lead.platform_id == platform_id, Lead.external_id == external_id)):
        raise HTTPException(409, "这条链接已经在线索里")
    lead = Lead(
        project_id=project.id,
        platform_id=platform_id,
        external_id=external_id,
        url=payload.url.strip(),
        title=payload.title.strip(),
        excerpt=payload.excerpt.strip(),
        author=payload.author.strip(),
        discovered_at=utcnow().replace(tzinfo=None),
        status="unread",
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    lead = session.scalar(_lead_query().where(Lead.id == lead.id))
    return _lead_json(lead)


@router.get("/leads/{lead_id}/source")
def lead_source(lead_id: int, session: Session = Depends(get_session)) -> dict:
    lead = session.scalar(_lead_query().where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    title = lead.title
    author = lead.author
    body = lead.excerpt
    live = False
    note = ""
    if lead.platform_id == "reddit" and lead.external_id:
        try:
            post = reddit.read_submission(lead.external_id)
            title = post["title"] or title
            author = post["author"] or author
            if post["body"]:
                body = post["body"]
                live = True
            else:
                note = "这篇帖子正文是空的，先显示记下的原话。"
        except Exception:
            note = "暂时拉不到整帖，先显示记下的原话。"
    return {
        "title": title,
        "author": author,
        "body": body,
        "embed": lead.platform_id not in FRAME_BLOCKED,
        "live": live,
        "note": note,
    }


@router.delete("/leads/{lead_id}", status_code=204)
def remove_lead(lead_id: int, session: Session = Depends(get_session)) -> None:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    delete_lead(session, lead)
    session.commit()


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: int, payload: StatusIn, session: Session = Depends(get_session)) -> dict:
    if payload.status not in STATUSES:
        raise HTTPException(400, "状态不对")
    lead = session.scalar(_lead_query().where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    lead.status = payload.status
    session.commit()
    return _lead_json(lead)


@router.put("/leads/{lead_id}/draft")
def save_draft(lead_id: int, payload: DraftIn, session: Session = Depends(get_session)) -> dict:
    lead = session.scalar(_lead_query().where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    return _store_draft(session, lead, payload.body)


@router.get("/leads/{lead_id}/messages")
def list_messages(lead_id: int, session: Session = Depends(get_session)) -> list[dict]:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    rows = session.scalars(
        select(DraftMessage).where(DraftMessage.lead_id == lead.id).order_by(DraftMessage.id)
    ).all()
    return [_message_json(row) for row in rows]


@router.post("/leads/{lead_id}/chat")
def chat_lead(lead_id: int, payload: ChatIn, session: Session = Depends(get_session)) -> dict:
    lead, text, base, model, key, summary, until_id, messages = _prepare_chat(session, lead_id, payload)
    try:
        answer, reasoning = complete_parts(base, key, model, messages)
    except AiError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not answer.strip() and not reasoning.strip():
        raise HTTPException(502, "模型没有返回内容")
    return {"messages": _store_exchange(session, lead, text, answer, reasoning, summary, until_id)}


@router.post("/leads/{lead_id}/chat/stream")
def chat_lead_stream(lead_id: int, payload: ChatIn, session: Session = Depends(get_session)) -> StreamingResponse:
    lead, text, base, model, key, summary, until_id, messages = _prepare_chat(session, lead_id, payload)

    def events():
        answer_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            for kind, delta in iter_parts(base, key, model, messages):
                if kind == "reasoning":
                    reasoning_parts.append(delta)
                    yield _sse({"reasoning": delta})
                else:
                    answer_parts.append(delta)
                    yield _sse({"delta": delta})
        except AiError as exc:
            yield _sse({"error": str(exc)})
            return
        answer = "".join(answer_parts)
        reasoning = "".join(reasoning_parts)
        if not answer.strip() and not reasoning.strip():
            yield _sse({"error": "模型没有返回内容"})
            return
        rows = _store_exchange(session, lead, text, answer, reasoning, summary, until_id)
        yield _sse({"done": True, "messages": rows})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/leads/{lead_id}/draft/adopt")
def adopt_draft(lead_id: int, payload: AdoptIn, session: Session = Depends(get_session)) -> dict:
    lead = session.scalar(_lead_query().where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    if lead.project is None:
        raise HTTPException(400, "这条线索还没有项目")
    body = apply_adopted(lead.project, payload.body)
    if not body:
        raise HTTPException(400, "没有可保存的稿子")
    return _store_draft(session, lead, body)


@router.post("/leads/{lead_id}/replies", status_code=201)
def add_reply(lead_id: int, payload: ReplyIn, session: Session = Depends(get_session)) -> dict:
    lead = session.scalar(_lead_query().where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    parsed = parse_link(payload.comment_url)
    comment_id = parsed.comment_id if parsed.platform_id == lead.platform_id else ""
    now = utcnow().replace(tzinfo=None)
    reply = MyReply(
        lead_id=lead.id,
        body=payload.body,
        comment_url=payload.comment_url.strip(),
        external_comment_id=comment_id,
        posted_at=now,
    )
    lead.status = "replied"
    session.add(reply)
    session.commit()
    reply = session.scalar(
        select(MyReply)
        .options(joinedload(MyReply.lead).joinedload(Lead.platform), selectinload(MyReply.events))
        .where(MyReply.id == reply.id)
    )
    return _reply_json(reply)


@router.get("/replies")
def list_replies(session: Session = Depends(get_session)) -> list[dict]:
    project = active_project(session)
    replies = session.scalars(
        select(MyReply)
        .join(MyReply.lead)
        .options(joinedload(MyReply.lead).joinedload(Lead.platform), selectinload(MyReply.events))
        .where(Lead.project_id == project.id)
        .order_by(MyReply.posted_at.desc())
    ).unique().all()
    replies = sorted(
        replies,
        key=lambda item: (0 if any(not event.seen for event in item.events) else 1, -item.posted_at.timestamp()),
    )
    return [_reply_json(reply) for reply in replies]


@router.post("/replies/{reply_id}/seen")
def mark_seen(reply_id: int, session: Session = Depends(get_session)) -> dict:
    reply = session.scalar(
        select(MyReply)
        .options(joinedload(MyReply.lead).joinedload(Lead.platform), selectinload(MyReply.events))
        .where(MyReply.id == reply_id)
    )
    if reply is None:
        raise HTTPException(404, "没有这条回复")
    for event in reply.events:
        event.seen = True
    session.commit()
    return _reply_json(reply)


@router.get("/monitors")
def list_monitors(session: Session = Depends(get_session)) -> list[dict]:
    project = active_project(session)
    rows = session.scalars(
        select(Monitor)
        .options(joinedload(Monitor.platform))
        .where(Monitor.project_id == project.id)
        .order_by(Monitor.id)
    ).unique().all()
    return [_monitor_json(row) for row in rows]


@router.post("/monitors", status_code=201)
def create_monitor(payload: MonitorIn, session: Session = Depends(get_session)) -> dict:
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "先填内容")
    project = active_project(session)
    if payload.kind == "url":
        parsed = parse_link(content)
        platform = session.get(Platform, parsed.platform_id)
        if platform is None:
            raise HTTPException(404, "没有这个平台")
        row = Monitor(
            project_id=project.id,
            platform_id=platform.id,
            kind="url",
            content=content,
            enabled=payload.enabled,
        )
        session.add(row)
        session.flush()
        track_url(session, project.id, parsed)
        session.commit()
        row = session.scalar(select(Monitor).options(joinedload(Monitor.platform)).where(Monitor.id == row.id))
        return _monitor_json(row)
    if payload.kind != "keyword":
        raise HTTPException(400, "监控类型只能是关键词或链接")
    if not payload.platform_id:
        raise HTTPException(400, "先选平台")
    platform = session.get(Platform, payload.platform_id)
    if platform is None:
        raise HTTPException(404, "没有这个平台")
    if not platform.can_search:
        raise HTTPException(400, f"{platform.name} 还不能按关键词搜索")
    row = Monitor(
        project_id=project.id,
        platform_id=platform.id,
        kind="keyword",
        content=content,
        enabled=payload.enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    row = session.scalar(select(Monitor).options(joinedload(Monitor.platform)).where(Monitor.id == row.id))
    return _monitor_json(row)


@router.patch("/monitors/{monitor_id}")
def update_monitor(monitor_id: int, payload: MonitorPatch, session: Session = Depends(get_session)) -> dict:
    row = session.scalar(select(Monitor).options(joinedload(Monitor.platform)).where(Monitor.id == monitor_id))
    if row is None:
        raise HTTPException(404, "没有这条监控")
    if payload.content is not None:
        row.content = payload.content.strip()
    if payload.enabled is not None:
        row.enabled = payload.enabled
    session.commit()
    return _monitor_json(row)


@router.delete("/monitors/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, session: Session = Depends(get_session)) -> None:
    row = session.get(Monitor, monitor_id)
    if row is None:
        raise HTTPException(404, "没有这条监控")
    session.delete(row)
    session.commit()


def _store_draft(session: Session, lead: Lead, body: str) -> dict:
    now = utcnow().replace(tzinfo=None)
    if lead.draft is None:
        session.add(Draft(lead_id=lead.id, body=body, updated_at=now))
    else:
        lead.draft.body = body
        lead.draft.updated_at = now
    if lead.status == "unread":
        lead.status = "drafted"
    session.commit()
    session.expire(lead)
    stored = session.scalar(_lead_query().where(Lead.id == lead.id))
    return _lead_json(stored)


def _prepare_chat(session: Session, lead_id: int, payload: ChatIn):
    text = payload.message.strip()
    if not text:
        raise HTTPException(400, "先写一句")
    if len(text) > 8000:
        raise HTTPException(400, "这句话太长了")
    lead = session.scalar(
        _lead_query().options(selectinload(Lead.messages)).where(Lead.id == lead_id)
    )
    if lead is None:
        raise HTTPException(404, "没有这条线索")
    base, model, key = _active_ai(session)
    stored = [
        Turn(id=item.id, role=item.role, body=item.body, reasoning=item.reasoning or "")
        for item in sorted(lead.messages, key=lambda item: item.id)
    ]
    summary, until_id, recent = slide_window(
        lead.chat_summary or "",
        lead.chat_summary_until_id or 0,
        stored + [Turn(id=None, role="user", body=text)],
    )
    messages = build_model_messages(
        background=lead.project.background if lead.project else "",
        post=post_block(lead),
        draft=payload.draft,
        summary=summary,
        recent=[(item.role, item.body, item.reasoning) for item in recent],
    )
    return lead, text, base, model, key, summary, until_id, messages


def _store_exchange(
    session: Session,
    lead: Lead,
    text: str,
    answer: str,
    reasoning: str,
    summary: str,
    until_id: int,
) -> list[dict]:
    now = utcnow().replace(tzinfo=None)
    session.add(DraftMessage(lead_id=lead.id, role="user", body=text, created_at=now))
    session.add(
        DraftMessage(lead_id=lead.id, role="assistant", body=answer, reasoning=reasoning, created_at=now)
    )
    session.flush()
    rows = session.scalars(
        select(DraftMessage).where(DraftMessage.lead_id == lead.id).order_by(DraftMessage.id)
    ).all()
    if len(rows) > MAX_STORED:
        extra = rows[:-MAX_STORED]
        pending = [
            Turn(id=item.id, role=item.role, body=item.body, reasoning=item.reasoning or "")
            for item in extra
            if item.id > until_id
        ]
        if pending:
            summary = fold_summary(summary, pending)
            until_id = pending[-1].id or until_id
        for item in extra:
            session.delete(item)
        rows = rows[-MAX_STORED:]
    lead.chat_summary = summary
    lead.chat_summary_until_id = until_id
    session.commit()
    return [_message_json(row) for row in rows]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _message_json(row: DraftMessage) -> dict:
    return {
        "id": row.id,
        "role": row.role,
        "body": row.body,
        "reasoning": row.reasoning or "",
        "created_at": iso(row.created_at),
    }


def _save_setting(session: Session, key: str, value: str) -> None:
    session.merge(Setting(key=key, value=value))


def _setting(session: Session, key: str) -> str:
    row = session.get(Setting, key)
    return row.value if row is not None else ""


def _normalize_base(raw: str) -> str:
    base = raw.strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        raise HTTPException(400, "地址要以 http:// 或 https:// 开头")
    return base


def _model_names(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _source_or_404(session: Session, source_id: int) -> AiSource:
    source = session.get(AiSource, source_id)
    if source is None:
        raise HTTPException(404, "没有这个来源")
    return source


def _source_by_base(session: Session, base: str) -> AiSource | None:
    return session.scalar(select(AiSource).where(AiSource.base_url == base))


def _require_source_credentials(source: AiSource) -> None:
    if not source.base_url.strip():
        raise HTTPException(400, "先填模型地址")
    if not source.api_key.strip():
        raise HTTPException(400, "先填密钥")


def _active_choice(session: Session) -> tuple[int | None, str]:
    raw = _setting(session, "ai_source_id").strip()
    model = _setting(session, "ai_model").strip()
    if not raw:
        return None, model
    try:
        return int(raw), model
    except ValueError:
        return None, model


def _source_json(source: AiSource) -> dict:
    key = source.api_key.strip()
    return {
        "id": source.id,
        "name": source.name,
        "base_url": source.base_url,
        "models": _model_names(source.models_json),
        "configured": bool(source.base_url.strip() and key),
        "key_hint": key[-4:] if len(key) >= 4 else "",
    }


def _ai_view(session: Session) -> dict:
    sources = session.scalars(select(AiSource).order_by(AiSource.id)).all()
    source_id, model = _active_choice(session)
    active = next((item for item in sources if item.id == source_id), None)
    if active is None:
        source_id = None
        model = ""
    configured = bool(active and active.base_url.strip() and active.api_key.strip() and model)
    return {
        "sources": [_source_json(item) for item in sources],
        "source_id": source_id,
        "model": model,
        "configured": configured,
    }


def _active_ai(session: Session) -> tuple[str, str, str]:
    source_id, model = _active_choice(session)
    source = session.get(AiSource, source_id) if source_id is not None else None
    if source is None or not source.base_url.strip() or not model or not source.api_key.strip():
        raise HTTPException(400, "先在设置里填上模型地址、模型和密钥")
    return source.base_url.strip(), model, source.api_key.strip()


def _model_for_test(session: Session, source: AiSource, requested: str) -> str:
    model = requested.strip()
    if model:
        return model
    source_id, active_model = _active_choice(session)
    if source_id == source.id and active_model:
        return active_model
    names = _model_names(source.models_json)
    if names:
        return names[0]
    raise HTTPException(400, "先获取模型")


def _project_json(project: Project, active_id: int) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "background": project.background,
        "followup_zh": project.followup_zh,
        "followup_en": project.followup_en,
        "active": project.id == active_id,
    }


def _unique_slug(session: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    candidate = base
    number = 2
    while session.scalar(select(Project).where(Project.slug == candidate)):
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def _monitor_json(row: Monitor) -> dict:
    return {
        "id": row.id,
        "platform_id": row.platform_id,
        "platform_name": row.platform.name,
        "kind": row.kind,
        "content": row.content,
        "enabled": row.enabled,
        "last_run_at": iso(row.last_run_at),
        "last_error": row.last_error,
    }
