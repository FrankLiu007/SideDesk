import hashlib

from app.platforms.base import ParsedLink
from app.platforms.bilibili import parse_url as parse_bilibili
from app.platforms.reddit_link import parse_url as parse_reddit
from app.platforms.v2ex import parse_url as parse_v2ex
from app.platforms.youtube import parse_url as parse_youtube
from app.platforms.zhihu import parse_url as parse_zhihu

_PARSERS = (parse_reddit, parse_youtube, parse_bilibili, parse_v2ex, parse_zhihu)


def parse_link(url: str) -> ParsedLink:
    cleaned = url.strip()
    for parser in _PARSERS:
        found = parser(cleaned)
        if found is not None:
            return found
    digest = hashlib.sha1(cleaned.encode()).hexdigest()[:16]
    return ParsedLink("other", digest, "", cleaned, cleaned)
