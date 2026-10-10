from datetime import datetime

from app.platforms.base import LeadHit, SearchBatch
from app.reddit import RedditClient


class RedditAdapter:
    """Reddit search. Archived threads cannot take a new comment, so they are not leads."""

    platform_id = "reddit"

    def __init__(self, client: RedditClient) -> None:
        self.client = client

    def configured(self) -> bool:
        return self.client.configured()

    def search(self, query: str, since: datetime | None) -> SearchBatch:
        raw = self.client.search(query, since)
        newest: datetime | None = None
        hits: list[LeadHit] = []
        for item in raw:
            created = item["created_at"]
            if newest is None or created > newest:
                newest = created
            if item.get("archived"):
                continue
            hits.append(
                LeadHit(
                    external_id=item["external_id"],
                    url=item["url"],
                    title=item["title"],
                    excerpt=item["excerpt"],
                    author=item["author"],
                    created_at=created,
                )
            )
        return SearchBatch(hits=hits, newest=newest)

    def unanswerable_ids(self, external_ids: list[str]) -> set[str]:
        if not external_ids:
            return set()
        return self.client.archived_ids(external_ids)

    def refresh_reply(self, comment_url: str):
        return self.client.refresh_reply(comment_url)
