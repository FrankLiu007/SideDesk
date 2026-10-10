import re
from dataclasses import dataclass

from app.drafts import sanitize_draft
from app.platforms.parse import parse_link

_HEADING = re.compile(r"^###\s+(.+)$", re.MULTILINE)
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


@dataclass
class SeedLead:
    platform_id: str
    external_id: str
    url: str
    title: str
    excerpt: str
    draft: str
    done: bool


def parse_seed_markdown(text: str) -> list[SeedLead]:
    chunks = re.split(r"\n(?=### )", text)
    leads: list[SeedLead] = []
    for chunk in chunks:
        heading = _HEADING.search(chunk)
        if not heading:
            continue
        title = re.sub(r"^\d+\.\s*", "", heading.group(1).strip())
        url_match = re.search(r"https?://\S+", chunk)
        if not url_match:
            continue
        url = url_match.group(0).rstrip(")")
        parsed = parse_link(url)
        platform_id, external_id = parsed.platform_id, parsed.external_id
        excerpt = ""
        for label in ("原话：", "标题："):
            found = re.search(rf"{label}(.+)", chunk)
            if found:
                excerpt = found.group(1).strip()
                break
        fence = _FENCE.search(chunk)
        draft = sanitize_draft(fence.group(1)) if fence else ""
        done = "- [x]" in chunk.lower() or "- [X]" in chunk
        leads.append(
            SeedLead(
                platform_id=platform_id,
                external_id=external_id,
                url=url,
                title=title,
                excerpt=excerpt,
                draft=draft,
                done=done,
            )
        )
    return leads
