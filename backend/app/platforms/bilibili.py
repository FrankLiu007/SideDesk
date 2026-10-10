import re
from urllib.parse import urlparse

from app.platforms.base import ParsedLink

_BV = re.compile(r"(BV[0-9A-Za-z]+)")


def parse_url(url: str) -> ParsedLink | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if "bilibili.com" not in host:
        return None
    match = _BV.search(parsed.path or "")
    if not match:
        return None
    bv = match.group(1)
    post_url = f"https://www.bilibili.com/video/{bv}"
    return ParsedLink("bilibili", bv, "", post_url, post_url)
