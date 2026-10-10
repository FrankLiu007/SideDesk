from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.jobs import purge_unanswerable, run_monitors
from app.main import app
from app.models import Draft, DraftMessage, Lead, Monitor, Project
from app.platforms.base import LeadHit, SearchBatch
from app.platforms.reddit import RedditAdapter
from app.reddit import RedditClient, archived_ids_from_listing


def test_listing_archived_ids_reads_only_archived_posts():
    payload = {
        "data": {
            "children": [
                {"kind": "t3", "data": {"id": "open1", "archived": False}},
                {"kind": "t3", "data": {"id": "old1", "archived": True}},
                {"kind": "t3", "data": {"id": "", "archived": True}},
            ]
        }
    }
    assert archived_ids_from_listing(payload) == {"old1"}


def test_reddit_adapter_skips_archived_and_keeps_newest_time(monkeypatch):
    client = RedditClient()
    monkeypatch.setattr(client, "configured", lambda: True)
    monkeypatch.setattr(client, "_token_value", lambda: "token")

    def fake_get(path, params):
        assert path == "/search"
        return {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "old",
                            "created_utc": 100,
                            "permalink": "/r/a/comments/old/t/",
                            "title": "已归档",
                            "archived": True,
                            "author": "a",
                            "selftext": "旧帖",
                        },
                    },
                    {
                        "kind": "t3",
                        "data": {
                            "id": "new",
                            "created_utc": 200,
                            "permalink": "/r/a/comments/new/t/",
                            "title": "还能回",
                            "archived": False,
                            "author": "b",
                            "selftext": "新帖",
                        },
                    },
                ]
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    batch = RedditAdapter(client).search("formula", None)
    assert [hit.external_id for hit in batch.hits] == ["new"]
    assert batch.hits[0].title == "还能回"
    assert batch.newest == datetime.fromtimestamp(200, tz=timezone.utc).replace(tzinfo=None)


class _FakeSearch:
    platform_id = "reddit"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def configured(self) -> bool:
        return True

    def unanswerable_ids(self, external_ids: list[str]) -> set[str]:
        return {"archpost"}

    def search(self, query: str, since: datetime | None) -> SearchBatch:
        self.queries.append(query)
        return SearchBatch(
            hits=[
                LeadHit(
                    external_id="livepost",
                    url="https://www.reddit.com/r/a/comments/livepost/t/",
                    title="还能回",
                    excerpt="正文",
                    author="bee",
                    created_at=datetime(2026, 10, 1, 8, 0, 0),
                )
            ],
            newest=datetime(2026, 10, 2, 8, 0, 0),
        )


def test_refresh_deletes_open_archived_leads_and_skips_them_on_search(monkeypatch):
    created: list[int] = []
    monitor_id = None
    fake = _FakeSearch()
    monkeypatch.setattr("app.jobs.adapter_for", lambda platform_id, client: fake if platform_id == "reddit" else None)
    try:
        with TestClient(app):
            with SessionLocal() as session:
                project = session.scalar(select(Project).where(Project.slug == "default"))
                assert project is not None
                monitor = Monitor(
                    project_id=project.id,
                    platform_id="reddit",
                    kind="keyword",
                    content="paste tables",
                    enabled=True,
                )
                session.add(monitor)
                session.flush()
                monitor_id = monitor.id
                archived = Lead(
                    project_id=project.id,
                    platform_id="reddit",
                    external_id="archpost",
                    url="https://www.reddit.com/r/a/comments/archpost/t/",
                    title="已归档",
                    excerpt="不能回了",
                    author="ada",
                    discovered_at=datetime(2026, 9, 1, 8, 0, 0),
                    status="drafted",
                )
                kept = Lead(
                    project_id=project.id,
                    platform_id="reddit",
                    external_id="keptreply",
                    url="https://www.reddit.com/r/a/comments/keptreply/t/",
                    title="已经回过",
                    status="replied",
                    discovered_at=datetime(2026, 9, 1, 8, 0, 0),
                )
                session.add(archived)
                session.add(kept)
                session.flush()
                session.add(Draft(lead_id=archived.id, body="还没发出去的稿"))
                session.add(DraftMessage(lead_id=archived.id, role="user", body="写短一点"))
                session.commit()
                created.extend([archived.id, kept.id])

            with SessionLocal() as session:
                result = run_monitors(session)
                assert result["leads_removed"] == 1
                assert result["leads_found"] == 1
                assert result["monitor_errors"] == []
                assert session.get(Lead, created[0]) is None
                assert session.scalar(select(Draft).where(Draft.lead_id == created[0])) is None
                assert session.scalar(select(DraftMessage).where(DraftMessage.lead_id == created[0])) is None
                assert session.get(Lead, created[1]) is not None
                live = session.scalar(select(Lead).where(Lead.external_id == "livepost"))
                assert live is not None
                created.append(live.id)
                monitors = session.scalars(select(Monitor).where(Monitor.platform_id == "reddit")).all()
                assert len(monitors) == 1
                assert monitors[0].cursor_at == datetime(2026, 10, 2, 8, 0, 0)
            assert fake.queries == ["paste tables"]
    finally:
        with SessionLocal() as session:
            for lead_id in created:
                lead = session.get(Lead, lead_id)
                if lead is None:
                    continue
                draft = session.scalar(select(Draft).where(Draft.lead_id == lead.id))
                if draft is not None:
                    session.delete(draft)
                for message in session.scalars(select(DraftMessage).where(DraftMessage.lead_id == lead.id)).all():
                    session.delete(message)
                session.delete(lead)
            if monitor_id is not None:
                row = session.get(Monitor, monitor_id)
                if row is not None:
                    session.delete(row)
            session.commit()


def test_parse_link_uses_each_platform_format():
    from app.platforms.parse import parse_link

    reddit = parse_link("https://www.reddit.com/r/ChatGPT/comments/1j43zuh/title/abc123/")
    assert (reddit.platform_id, reddit.external_id, reddit.comment_id) == ("reddit", "1j43zuh", "abc123")
    post = parse_link("https://old.reddit.com/r/ChatGPT/comments/1j43zuh/title/")
    assert post.comment_id == ""
    assert post.external_id == "1j43zuh"
    youtube = parse_link("https://youtu.be/dQw4w9WgXcQ?lc=UgxAbc")
    assert (youtube.platform_id, youtube.external_id, youtube.comment_id) == ("youtube", "dQw4w9WgXcQ", "UgxAbc")
    watch = parse_link("https://www.youtube.com/watch?v=abcdefghijk")
    assert watch.comment_id == ""
    assert watch.post_url == "https://www.youtube.com/watch?v=abcdefghijk"
    bili = parse_link("https://www.bilibili.com/video/BV1xx411c7mD")
    assert (bili.platform_id, bili.external_id, bili.comment_id) == ("bilibili", "BV1xx411c7mD", "")
    v2 = parse_link("https://www.v2ex.com/t/1190583#reply_42")
    assert (v2.platform_id, v2.external_id, v2.comment_id) == ("v2ex", "1190583", "42")
    question = parse_link("https://www.zhihu.com/question/12345")
    assert (question.platform_id, question.external_id, question.comment_id) == ("zhihu", "q12345", "")
    answer = parse_link("https://www.zhihu.com/question/12345/answer/678")
    assert answer.external_id == "a678"
    assert answer.comment_id == ""
    other = parse_link("https://example.com/posts/1")
    assert other.platform_id == "other"
    assert other.comment_id == ""
