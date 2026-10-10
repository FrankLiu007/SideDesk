from urllib.parse import parse_qs, urlparse

from app.platforms.base import ParsedLink

_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


def parse_url(url: str) -> ParsedLink | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    video = ""
    if host == "youtu.be":
        video = (parsed.path or "").strip("/").split("/")[0]
    elif host in _HOSTS and (parsed.path or "").rstrip("/") == "/watch":
        video = parse_qs(parsed.query).get("v", [""])[0]
    if not video:
        return None
    comment = parse_qs(parsed.query).get("lc", [""])[0]
    post_url = f"https://www.youtube.com/watch?v={video}"
    canonical = f"{post_url}&lc={comment}" if comment else post_url
    return ParsedLink("youtube", video, comment, canonical, post_url)
