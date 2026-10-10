from app.platforms.base import ReplyAdapter, SearchAdapter
from app.platforms.parse import parse_link

__all__ = ["ReplyAdapter", "SearchAdapter", "adapter_for", "parse_link", "reply_adapter_for"]


def adapter_for(platform_id: str, reddit_client) -> SearchAdapter | None:
    if platform_id == "reddit":
        from app.platforms.reddit import RedditAdapter

        return RedditAdapter(reddit_client)
    return None


def reply_adapter_for(platform_id: str, reddit_client) -> ReplyAdapter | None:
    if platform_id == "reddit":
        from app.platforms.reddit import RedditAdapter

        return RedditAdapter(reddit_client)
    return None
