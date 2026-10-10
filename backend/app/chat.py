from dataclasses import dataclass

from app.models import Lead, Project

WINDOW = 16
MAX_STORED = 80
SUMMARY_LIMIT = 2000
POST_LIMIT = 6000

_SYSTEM = (
    "你在帮用户起草公开评论，用户会自己去贴。"
    "先跟着项目背景说话。用户没要成稿时可以只讨论。"
    "要出可粘贴的回复时，把正文放进 ```reply 围栏，围栏外可以解释。"
    "语言跟原帖，除非用户在对话里另作要求。"
    "当前回复稿以文本框里的内容为准，不要悄悄换回旧稿。"
)


@dataclass
class Turn:
    id: int | None
    role: str
    body: str
    reasoning: str = ""


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def fold_summary(previous: str, turns: list[Turn]) -> str:
    lines = [previous.strip()] if previous.strip() else []
    for turn in turns:
        if turn.role == "user":
            lines.append("用户：" + _clip(turn.body, 180))
        elif "```reply" in turn.body.lower():
            lines.append("模型提出过一版回复。")
        else:
            lines.append("模型：" + _clip(turn.body, 120))
    text = "\n".join(line for line in lines if line)
    if len(text) > SUMMARY_LIMIT:
        text = text[-SUMMARY_LIMIT:]
    return text


def slide_window(summary: str, until_id: int, history: list[Turn]) -> tuple[str, int, list[Turn]]:
    if len(history) <= WINDOW:
        return summary, until_id, history
    older = history[:-WINDOW]
    recent = history[-WINDOW:]
    pending = [turn for turn in older if turn.id is not None and turn.id > until_id]
    if pending:
        summary = fold_summary(summary, pending)
        until_id = pending[-1].id or until_id
    return summary, until_id, recent


def build_model_messages(
    *,
    background: str,
    post: str,
    draft: str,
    summary: str,
    recent: list[tuple[str, str, str]],
) -> list[dict]:
    draft_text = draft.strip() or "还没有"
    summary_text = summary.strip() or "无"
    system = (
        f"{_SYSTEM}\n\n"
        f"项目背景：\n{background.strip() or '（还没有写背景）'}\n\n"
        f"原帖：\n{post.strip() or '（没有原文）'}\n\n"
        f"当前回复稿：\n{draft_text}\n\n"
        f"更早的对话摘要：\n{summary_text}"
    )
    messages = [{"role": "system", "content": system}]
    for role, body, reasoning in recent:
        item = {"role": role, "content": body}
        if role == "assistant" and reasoning.strip():
            item["reasoning_content"] = reasoning
        messages.append(item)
    return messages


def post_block(lead: Lead) -> str:
    title = lead.title or ""
    author = lead.author or ""
    body = lead.excerpt or ""
    if lead.platform_id == "reddit" and lead.external_id:
        try:
            from app.jobs import reddit

            fetched = reddit.read_submission(lead.external_id)
            title = fetched.get("title") or title
            author = fetched.get("author") or author
            if fetched.get("body"):
                body = fetched["body"]
        except Exception:
            pass
    if len(body) > POST_LIMIT:
        body = body[:POST_LIMIT] + "…"
    platform_name = lead.platform.name if lead.platform else lead.platform_id
    lines = [f"平台：{platform_name}", f"标题：{title or '（无标题）'}"]
    if author:
        lines.append(f"作者：{author}")
    lines.append(f"正文：{body or '（没有留下原文）'}")
    return "\n".join(lines)


def apply_adopted(_project: Project, body: str) -> str:
    return body.strip()
