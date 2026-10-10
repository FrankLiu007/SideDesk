from app.platforms.parse import parse_link
from app.platforms.reddit_link import parse_url as parse_reddit


def platform_and_external_id(url: str) -> tuple[str, str]:
    parsed = parse_link(url)
    return parsed.platform_id, parsed.external_id


def reddit_ids(url: str) -> tuple[str, str]:
    parsed = parse_reddit(url)
    if parsed is None:
        return "", ""
    return parsed.external_id, parsed.comment_id
