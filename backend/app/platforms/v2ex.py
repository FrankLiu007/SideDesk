import re
from urllib.parse import urlparse

from app.platforms.base import ParsedLink

_TOPIC = re.compile(r"/t/(\d+)")
_REPLY = re.compile(r"^reply_(\d+)$")


def parse_url(url: str) -> ParsedLink | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host != "v2ex.com" and not host.endswith(".v2ex.com"):
        return None
    match = _TOPIC.search(parsed.path or "")
    if not match:
        return None
    topic = match.group(1)
    reply = _REPLY.match(parsed.fragment or "")
    comment = reply.group(1) if reply else ""
    post_url = f"https://www.v2ex.com/t/{topic}"
    canonical = f"{post_url}#reply_{comment}" if comment else post_url
    return ParsedLink("v2ex", topic, comment, canonical, post_url)
