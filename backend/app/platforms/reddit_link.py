import re
from urllib.parse import urlparse

from app.platforms.base import ParsedLink

_COMMENT = re.compile(
    r"/comments/(?P<post>[a-z0-9]+)(?:/[^/?#]+)?(?:/(?P<comment>[a-z0-9]+))?",
    re.IGNORECASE,
)


def parse_url(url: str) -> ParsedLink | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host != "reddit.com" and not host.endswith(".reddit.com"):
        return None
    match = _COMMENT.search(parsed.path or "")
    if not match:
        return None
    post = match.group("post")
    comment = match.group("comment") or ""
    post_url = f"https://www.reddit.com/comments/{post}/"
    canonical = f"https://www.reddit.com/comments/{post}/_/{comment}/" if comment else post_url
    return ParsedLink("reddit", post, comment, canonical, post_url)
