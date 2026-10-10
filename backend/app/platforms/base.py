from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class LeadHit:
    external_id: str
    url: str
    title: str
    excerpt: str
    author: str
    created_at: datetime


@dataclass(frozen=True)
class SearchBatch:
    """Answerable hits, plus the newest post time seen (including ones the adapter skipped)."""

    hits: list[LeadHit]
    newest: datetime | None


@dataclass(frozen=True)
class ParsedLink:
    """One tracked URL after a platform adapter has recognized it."""

    platform_id: str
    external_id: str
    comment_id: str
    canonical_url: str
    post_url: str


class SearchAdapter(Protocol):
    platform_id: str

    def configured(self) -> bool: ...

    def search(self, query: str, since: datetime | None) -> SearchBatch: ...

    def unanswerable_ids(self, external_ids: list[str]) -> set[str]: ...


class ReplyAdapter(Protocol):
    platform_id: str

    def configured(self) -> bool: ...

    def refresh_reply(self, comment_url: str): ...
