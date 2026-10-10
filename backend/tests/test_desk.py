import json

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai import AiError, complete
from app.config import settings
from app.database import SessionLocal, _migrate_ai_sources
from app.diff import ReplySnapshot, diff_reply
from app.drafts import sanitize_draft
from app.identity import reddit_ids
from app.main import app
from app.models import AiSource, Draft, DraftMessage, Lead, MyReply, Project, ReplyEvent, Setting
from app.reddit import parse_submission
from app.seed_parse import parse_seed_markdown


def test_sanitize_strips_site_and_adds_store_phrase():
    english = sanitize_draft("Paste with ThinkNote. https://thinknote.pro/word")
    chinese = sanitize_draft("用 ThinkNote 粘贴。说明在 thinknote.pro/word")
    assert "thinknote.pro" not in english
    assert "thinknote.pro" not in chinese
    assert "Search ThinkNote in the Chrome Web Store." in english
    assert "Chrome 网上应用店搜索 ThinkNote。" in chinese


def test_seed_file_has_thirty_drafts_without_site_url():
    leads = parse_seed_markdown(open(settings.seed_path, encoding="utf-8").read())
    assert len(leads) == 30
    assert {item.platform_id for item in leads} >= {"reddit", "bilibili", "youtube", "v2ex"}
    for item in leads:
        assert "thinknote.pro" not in item.draft
        assert "ThinkNote" in item.draft


def test_reddit_comment_url():
    post, comment = reddit_ids(
        "https://www.reddit.com/r/ChatGPT/comments/1j43zuh/title/abc123/"
    )
    assert post == "1j43zuh"
    assert comment == "abc123"
    post, comment = reddit_ids("https://www.reddit.com/r/ChatGPT/comments/1j43zuh/title/")
    assert post == "1j43zuh"
    assert comment == ""


def test_parse_submission_reads_post_body():
    payload = [
        {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {"title": "公式没了", "author": "ada", "selftext": "整段复制进 Word 就消失。"},
                    }
                ]
            }
        }
    ]
    assert parse_submission(payload) == {
        "title": "公式没了",
        "author": "ada",
        "body": "整段复制进 Word 就消失。",
    }


def test_match_lead_ignores_reddit_host_and_query():
    with TestClient(app) as client:
        leads = client.get("/api/leads").json()
        reddit = next(lead for lead in leads if lead["platform_id"] == "reddit")
        varied = reddit["url"].replace("www.reddit.com", "old.reddit.com") + "?utm_source=desk"
        matched = client.get("/api/leads/match", params={"url": varied}).json()
        assert matched["lead"]["id"] == reddit["id"]
        assert matched["on_comment"] is False
        assert matched["comment_url"] == ""
        missing = client.get(
            "/api/leads/match",
            params={"url": "https://www.reddit.com/r/ChatGPT/comments/zzzzzzz/no_such_post/"},
        ).json()
        assert missing["lead"] is None
        assert missing["on_comment"] is False
        assert missing["comment_url"] == ""


def test_lead_source_uses_saved_excerpt_unless_the_site_can_be_embedded():
    created_id = None
    try:
        with TestClient(app) as client:
            leads = client.get("/api/leads").json()
            social = next(lead for lead in leads if lead["platform_id"] == "bilibili")
            source = client.get(f"/api/leads/{social['id']}/source").json()
            assert source["embed"] is False
            assert source["body"] == social["excerpt"]
            created = client.post(
                "/api/leads",
                json={"url": "https://example.com/posts/word-math", "title": "外站", "excerpt": "对方说打不开"},
            )
            assert created.status_code == 201
            created_id = created.json()["id"]
            other = client.get(f"/api/leads/{created_id}/source").json()
            assert other["embed"] is True
            assert other["body"] == "对方说打不开"
    finally:
        if created_id is not None:
            with SessionLocal() as session:
                row = session.get(Lead, created_id)
                if row is not None:
                    session.delete(row)
                    session.commit()


def test_diff_reply_baseline_then_new_child():
    snap = ReplySnapshot(score=2, child_ids=["a"], snippets={"a": "hi"}, deleted=False)
    assert diff_reply(has_baseline=False, old_score=None, old_child_ids=[], old_deleted=False, snap=snap) == []
    events = diff_reply(has_baseline=True, old_score=2, old_child_ids=[], old_deleted=False, snap=snap)
    assert events[0][0] == "new_child"
    later = ReplySnapshot(score=1, child_ids=["a"], snippets={}, deleted=True)
    kinds = [
        kind
        for kind, _detail in diff_reply(
            has_baseline=True, old_score=2, old_child_ids=["a"], old_deleted=False, snap=later
        )
    ]
    assert kinds == ["deleted"]


def test_api_seeds_leads_and_skips_unrefreshable_platforms():
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        leads = client.get("/api/leads").json()
        assert len(leads) == 30
        assert all("thinknote.pro" not in lead["draft"] for lead in leads)
        projects = client.get("/api/projects").json()
        thinknote = next(item for item in projects if item["name"] == "ThinkNote")
        assert thinknote["active"] is True
        assert "thinknote.pro/word" in thinknote["followup_zh"]
        duplicate = client.post(
            "/api/leads",
            json={"url": "https://www.v2ex.com/t/1190583", "title": "已存在"},
        )
        assert duplicate.status_code == 409
        created = client.post(
            "/api/leads",
            json={"url": "https://www.bilibili.com/video/BV1testVideo", "title": "视频"},
        )
        assert created.status_code == 201
        client.post(
            f"/api/leads/{created.json()['id']}/replies",
            json={"comment_url": "https://www.bilibili.com/video/BV1testVideo", "body": "已回"},
        )
        refreshed = client.post("/api/refresh").json()
        assert refreshed["replies_checked"] == 1
        assert refreshed["new_events"] == 0
        replies = client.get("/api/replies").json()
        assert replies[0]["last_error"] == "这个平台还不能自动看追问"


def _delete_lead(lead_id: int) -> None:
    with SessionLocal() as session:
        lead = session.get(Lead, lead_id)
        if lead is None:
            return
        draft = session.scalar(select(Draft).where(Draft.lead_id == lead.id))
        if draft is not None:
            session.delete(draft)
        for message in session.scalars(select(DraftMessage).where(DraftMessage.lead_id == lead.id)).all():
            session.delete(message)
        for reply in session.scalars(select(MyReply).where(MyReply.lead_id == lead.id)).all():
            for event in session.scalars(select(ReplyEvent).where(ReplyEvent.reply_id == reply.id)).all():
                session.delete(event)
            session.delete(reply)
        session.delete(lead)
        session.commit()


def test_delete_lead_removes_draft_and_reply():
    lead_id = None
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/leads",
                json={
                    "url": "https://www.reddit.com/r/ChatGPT/comments/deskdel1/title/",
                    "title": "要删",
                },
            )
            assert created.status_code == 201
            lead_id = created.json()["id"]
            assert client.put(f"/api/leads/{lead_id}/draft", json={"body": "稿子"}).status_code == 200
            replied = client.post(
                f"/api/leads/{lead_id}/replies",
                json={
                    "comment_url": "https://www.reddit.com/r/ChatGPT/comments/deskdel1/title/cmt1/",
                    "body": "已回",
                },
            )
            assert replied.status_code == 201
            removed = client.delete(f"/api/leads/{lead_id}")
            assert removed.status_code == 204
            assert client.get(f"/api/leads/{lead_id}/source").status_code == 404
            assert all(item["id"] != lead_id for item in client.get("/api/leads").json())
            with SessionLocal() as session:
                assert session.get(Lead, lead_id) is None
                assert session.scalar(select(Draft).where(Draft.lead_id == lead_id)) is None
                assert session.scalar(select(MyReply).where(MyReply.lead_id == lead_id)) is None
            again = client.post(
                "/api/leads",
                json={
                    "url": "https://www.reddit.com/r/ChatGPT/comments/deskdel1/title/",
                    "title": "重新加入",
                },
            )
            assert again.status_code == 201
            lead_id = again.json()["id"]
            assert client.delete("/api/leads/99999999").status_code == 404
    finally:
        if lead_id is not None:
            _delete_lead(lead_id)


def test_today_lists_drafted_before_unread():
    unread_id = None
    drafted_id = None
    try:
        with TestClient(app) as client:
            unread = client.post(
                "/api/leads",
                json={
                    "url": "https://www.reddit.com/r/ChatGPT/comments/deskunread/title/",
                    "title": "还没写",
                },
            )
            drafted = client.post(
                "/api/leads",
                json={
                    "url": "https://www.reddit.com/r/ChatGPT/comments/deskdraft/title/",
                    "title": "写了一半",
                },
            )
            assert unread.status_code == 201
            assert drafted.status_code == 201
            unread_id = unread.json()["id"]
            drafted_id = drafted.json()["id"]
            saved = client.put(f"/api/leads/{drafted_id}/draft", json={"body": "先写着"})
            assert saved.json()["status"] == "drafted"
            today = client.get("/api/today").json()
            assert all(item["status"] in {"unread", "drafted"} for item in today["needs_reply"])
            order = [item["id"] for item in today["needs_reply"]]
            assert drafted_id in order
            assert unread_id in order
            assert order.index(drafted_id) < order.index(unread_id)
    finally:
        if unread_id is not None:
            _delete_lead(unread_id)
        if drafted_id is not None:
            _delete_lead(drafted_id)


def test_match_reddit_comment_sets_on_comment():
    created_id = None
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/leads",
                json={
                    "url": "https://www.reddit.com/r/ChatGPT/comments/deskcmt1/title/",
                    "title": "等评论",
                },
            )
            assert created.status_code == 201
            created_id = created.json()["id"]
            comment = "https://www.reddit.com/r/ChatGPT/comments/deskcmt1/title/cmt123/"
            matched = client.get("/api/leads/match", params={"url": comment}).json()
            assert matched["lead"]["id"] == created_id
            assert matched["on_comment"] is True
            assert matched["comment_url"] == comment
            post = client.get("/api/leads/match", params={"url": created.json()["url"]}).json()
            assert post["on_comment"] is False
            assert post["comment_url"] == ""
    finally:
        if created_id is not None:
            _delete_lead(created_id)


def _clear_ai() -> None:
    with SessionLocal() as session:
        for source in session.scalars(select(AiSource)).all():
            session.delete(source)
        for key in (
            "ai_base_url",
            "ai_model",
            "ai_api_key",
            "ai_model_list",
            "ai_model_list_base",
            "ai_source_id",
        ):
            row = session.get(Setting, key)
            if row is not None:
                session.delete(row)
        session.commit()


def _configure_ai(client: TestClient, base: str, model: str, key: str, name: str = "示例") -> dict:
    created = client.post(
        "/api/settings/ai/sources",
        json={"name": name, "base_url": base, "api_key": key},
    )
    assert created.status_code == 201, created.text
    normalized = base.strip().rstrip("/")
    source = next(item for item in created.json()["sources"] if item["base_url"] == normalized)
    with SessionLocal() as session:
        row = session.get(AiSource, source["id"])
        assert row is not None
        row.models_json = json.dumps([model])
        session.commit()
    selected = client.put("/api/settings/ai", json={"source_id": source["id"], "model": model})
    assert selected.status_code == 200, selected.text
    return selected.json()


def _thinknote_id(client: TestClient) -> int:
    projects = client.get("/api/projects").json()
    return next(item["id"] for item in projects if item["name"] == "ThinkNote")


def _delete_project(project_id: int) -> None:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None or project.slug == "thinknote":
            return
        session.delete(project)
        session.commit()


def _listed(client: TestClient, lead_id: int) -> dict:
    return next(item for item in client.get("/api/leads").json() if item["id"] == lead_id)


class _Reply:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def test_ai_settings_hide_the_key_and_projects_stay_separate(monkeypatch):
    lead_id = None
    other_lead_id = None
    other_project_id = None
    captured: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "headers": headers, "json": json})
        return _Reply("先问一句。\n```reply\n候选稿\n```")

    monkeypatch.setattr("app.ai.httpx.post", fake_post)
    try:
        with TestClient(app) as client:
            _clear_ai()
            created = client.post(
                "/api/leads",
                json={"url": "https://example.com/desk-chat-a", "title": "线索甲", "excerpt": "原文甲"},
            )
            assert created.status_code == 201
            lead_id = created.json()["id"]
            blocked = client.post(f"/api/leads/{lead_id}/chat", json={"message": "写一条", "draft": "手改稿KEEP"})
            assert blocked.status_code == 400

            secret = "sk-test-secret-9f3a"
            view = _configure_ai(client, "https://example.com/v1/", "demo-model", secret)
            assert view["model"] == "demo-model"
            assert view["configured"] is True
            source = view["sources"][0]
            assert source["base_url"] == "https://example.com/v1"
            assert source["key_hint"] == "9f3a"
            assert "sk-test-secret" not in json.dumps(view)
            kept_key = client.patch(f"/api/settings/ai/sources/{source['id']}", json={"api_key": ""})
            assert kept_key.json()["sources"][0]["key_hint"] == "9f3a"

            talked = client.post(
                f"/api/leads/{lead_id}/chat",
                json={"message": "先别出稿", "draft": "手改稿KEEP"},
            )
            assert talked.status_code == 200
            assert talked.json()["messages"][-1]["body"].startswith("先问一句")
            assert _listed(client, lead_id)["draft"] == ""
            system = captured[-1]["json"]["messages"][0]["content"]
            assert "手改稿KEEP" in system
            assert "原文甲" in system
            assert "Word 加载项商店还在审核" in system
            assert captured[-1]["headers"]["Authorization"] == f"Bearer {secret}"
            assert captured[-1]["url"] == "https://example.com/v1/chat/completions"
            assert "先别出稿" in captured[-1]["json"]["messages"][-1]["content"]

            adopted = client.post(
                f"/api/leads/{lead_id}/draft/adopt",
                json={"body": "用 ThinkNote。 https://thinknote.pro/word"},
            )
            assert adopted.status_code == 200
            assert "thinknote.pro" not in adopted.json()["draft"]
            assert "Chrome 网上应用店搜索 ThinkNote。" in adopted.json()["draft"]

            other = client.post(
                "/api/projects",
                json={"name": "OtherProduct", "background": "BETA_BACKGROUND_ONLY"},
            )
            assert other.status_code == 201
            other_project_id = other.json()["id"]
            other_lead = client.post(
                "/api/leads",
                json={"url": "https://example.com/desk-chat-b", "title": "线索乙", "excerpt": "原文乙"},
            )
            assert other_lead.status_code == 201
            other_lead_id = other_lead.json()["id"]
            visible = client.get("/api/leads").json()
            assert all(item["id"] != lead_id for item in visible)
            assert any(item["id"] == other_lead_id for item in visible)

            client.post(f"/api/leads/{other_lead_id}/chat", json={"message": "写一条", "draft": ""})
            other_system = captured[-1]["json"]["messages"][0]["content"]
            assert "BETA_BACKGROUND_ONLY" in other_system
            assert "Word 加载项商店还在审核" not in other_system
            assert "原文乙" in other_system
            assert "原文甲" not in other_system
            assert "线索甲" not in other_system

            kept = client.post(
                f"/api/leads/{other_lead_id}/draft/adopt",
                json={"body": "文档在 https://example.com/docs"},
            )
            assert "https://example.com/docs" in kept.json()["draft"]
            assert "Chrome 网上应用店" not in kept.json()["draft"]
            client.post(f"/api/projects/{_thinknote_id(client)}/activate")
    finally:
        if lead_id is not None:
            _delete_lead(lead_id)
        if other_lead_id is not None:
            _delete_lead(other_lead_id)
        if other_project_id is not None:
            _delete_project(other_project_id)
        with TestClient(app) as client:
            client.post(f"/api/projects/{_thinknote_id(client)}/activate")
        _clear_ai()


def test_long_chat_keeps_recent_turns_and_drops_failed_messages(monkeypatch):
    lead_id = None
    captured: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json)
        content = "ASSISTANT_FULL_" + ("w" * 400) if len(captured) == 1 else "好，继续。"
        return _Reply(content)

    monkeypatch.setattr("app.ai.httpx.post", fake_post)
    try:
        with TestClient(app) as client:
            _clear_ai()
            _configure_ai(client, "https://example.com/v1", "demo-model", "sk-window-key-1234")
            created = client.post(
                "/api/leads",
                json={"url": "https://example.com/desk-window", "title": "长对话", "excerpt": "帖子正文"},
            )
            assert created.status_code == 201
            lead_id = created.json()["id"]
            for index in range(10):
                message = ("LONGFORM-" + ("q" * 400)) if index == 0 else f"再改{index}"
                response = client.post(
                    f"/api/leads/{lead_id}/chat",
                    json={"message": message, "draft": "当前稿KEEP"},
                )
                assert response.status_code == 200, response.text
            text = json.dumps(captured[-1], ensure_ascii=False)
            assert "q" * 400 not in text
            assert "w" * 400 not in text
            assert "LONGFORM-" in text
            assert "ASSISTANT_FULL_" in text
            assert "再改9" in text
            assert "好，继续。" in text
            assert "当前稿KEEP" in text
            recent = [item for item in captured[-1]["messages"] if item["role"] != "system"]
            assert len(recent) == 16

            def fail_post(*_args, **_kwargs):
                raise httpx.ConnectError("down")

            monkeypatch.setattr("app.ai.httpx.post", fail_post)
            before = client.get(f"/api/leads/{lead_id}/messages").json()
            failed = client.post(
                f"/api/leads/{lead_id}/chat",
                json={"message": "这句不该留下", "draft": "当前稿KEEP"},
            )
            assert failed.status_code == 502
            after = client.get(f"/api/leads/{lead_id}/messages").json()
            assert len(after) == len(before)
            assert all(item["body"] != "这句不该留下" for item in after)
            assert _listed(client, lead_id)["draft"] == ""
    finally:
        if lead_id is not None:
            _delete_lead(lead_id)
            with TestClient(app) as client:
                client.post(f"/api/projects/{_thinknote_id(client)}/activate")
        _clear_ai()


class _NamedModels:
    def __init__(self, names: list[str]):
        self._names = names

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [{"id": name} for name in self._names]}


def test_sources_keep_separate_keys_and_aggregate(monkeypatch):
    captured: list[dict] = []
    lead_id = None

    def fake_get(url, headers=None, timeout=None):
        captured.append({"url": url, "headers": headers})
        if "other.example" in url:
            return _NamedModels(["other-a"])
        return _NamedModels(["demo-b", "demo-a", "demo-a"])

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "headers": headers, "json": json})
        return _Reply("ok")

    monkeypatch.setattr("app.ai.httpx.get", fake_get)
    monkeypatch.setattr("app.ai.httpx.post", fake_post)
    try:
        with TestClient(app) as client:
            _clear_ai()
            missing = client.post("/api/settings/ai/sources/1/models")
            assert missing.status_code == 404

            first = client.post(
                "/api/settings/ai/sources",
                json={"name": "甲", "base_url": "https://example.com/v1/", "api_key": "sk-saved-key-0000"},
            )
            assert first.status_code == 201
            alpha = next(item for item in first.json()["sources"] if item["base_url"] == "https://example.com/v1")
            assert alpha["key_hint"] == "0000"
            assert "sk-saved-key" not in json.dumps(first.json())

            duplicate = client.post(
                "/api/settings/ai/sources",
                json={"name": "重复", "base_url": "https://example.com/v1", "api_key": "sk-dup-key-1111"},
            )
            assert duplicate.status_code == 400

            second = client.post(
                "/api/settings/ai/sources",
                json={"name": "乙", "base_url": "https://other.example/v1", "api_key": "sk-other-key-77ab"},
            )
            assert second.status_code == 201
            beta = next(item for item in second.json()["sources"] if item["name"] == "乙")

            listed = client.post(f"/api/settings/ai/sources/{alpha['id']}/models")
            assert listed.status_code == 200
            assert listed.json()["models"] == ["demo-b", "demo-a"]
            assert captured[-1]["url"] == "https://example.com/v1/models"
            assert captured[-1]["headers"]["Authorization"] == "Bearer sk-saved-key-0000"

            other_listed = client.post(f"/api/settings/ai/sources/{beta['id']}/models")
            assert other_listed.json()["models"] == ["other-a"]
            assert captured[-1]["headers"]["Authorization"] == "Bearer sk-other-key-77ab"

            stored = client.get("/api/settings/ai").json()
            by_id = {item["id"]: item for item in stored["sources"]}
            assert by_id[alpha["id"]]["models"] == ["demo-b", "demo-a"]
            assert by_id[beta["id"]]["models"] == ["other-a"]
            assert "sk-saved-key" not in json.dumps(stored)
            assert "sk-other-key" not in json.dumps(stored)

            kept = client.patch(f"/api/settings/ai/sources/{alpha['id']}", json={"api_key": ""})
            kept_alpha = next(item for item in kept.json()["sources"] if item["id"] == alpha["id"])
            assert kept_alpha["key_hint"] == "0000"
            assert kept_alpha["models"] == ["demo-b", "demo-a"]

            moved = client.patch(
                f"/api/settings/ai/sources/{alpha['id']}",
                json={"base_url": "https://third.example/v1"},
            )
            moved_alpha = next(item for item in moved.json()["sources"] if item["id"] == alpha["id"])
            assert moved_alpha["base_url"] == "https://third.example/v1"
            assert moved_alpha["models"] == []
            assert moved_alpha["key_hint"] == "0000"

            client.patch(f"/api/settings/ai/sources/{alpha['id']}", json={"base_url": "https://example.com/v1"})
            client.post(f"/api/settings/ai/sources/{alpha['id']}/models")
            rejected = client.put("/api/settings/ai", json={"source_id": alpha["id"], "model": "missing-model"})
            assert rejected.status_code == 400

            selected = client.put("/api/settings/ai", json={"source_id": alpha["id"], "model": "demo-a"})
            assert selected.json()["source_id"] == alpha["id"]
            assert selected.json()["model"] == "demo-a"
            assert selected.json()["configured"] is True

            probed = client.post(f"/api/settings/ai/sources/{alpha['id']}/test", json={"model": ""})
            assert probed.status_code == 200
            assert probed.json()["model"] == "demo-a"
            assert probed.json()["reply"] == "ok"
            assert captured[-1]["url"] == "https://example.com/v1/chat/completions"
            assert captured[-1]["headers"]["Authorization"] == "Bearer sk-saved-key-0000"
            assert captured[-1]["json"]["model"] == "demo-a"

            created = client.post(
                "/api/leads",
                json={"url": "https://example.com/desk-sources", "title": "来源", "excerpt": "原文"},
            )
            assert created.status_code == 201
            lead_id = created.json()["id"]
            talked = client.post(f"/api/leads/{lead_id}/chat", json={"message": "写一条", "draft": ""})
            assert talked.status_code == 200, talked.text
            assert captured[-1]["headers"]["Authorization"] == "Bearer sk-saved-key-0000"
            assert captured[-1]["url"] == "https://example.com/v1/chat/completions"

            client.put("/api/settings/ai", json={"source_id": beta["id"], "model": "other-a"})
            other_probe = client.post(f"/api/settings/ai/sources/{beta['id']}/test", json={})
            assert other_probe.status_code == 200
            assert other_probe.json()["model"] == "other-a"
            assert captured[-1]["headers"]["Authorization"] == "Bearer sk-other-key-77ab"
            assert captured[-1]["url"] == "https://other.example/v1/chat/completions"
    finally:
        if lead_id is not None:
            _delete_lead(lead_id)
        _clear_ai()


def test_deepseek_official_enables_thinking(monkeypatch):
    captured: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "json": json})
        return _Reply("ok")

    monkeypatch.setattr("app.ai.httpx.post", fake_post)
    assert complete("https://api.deepseek.com", "sk-ds", "deepseek-flash", [{"role": "user", "content": "hi"}]) == "ok"
    body = captured[-1]["json"]
    assert captured[-1]["url"] == "https://api.deepseek.com/chat/completions"
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in body

    complete("https://api.deepseek.com/v1/", "sk-ds", "deepseek-v4-pro", [{"role": "user", "content": "hi"}])
    assert captured[-1]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured[-1]["json"]["thinking"]["type"] == "enabled"

    complete("https://example.com/v1", "sk", "demo", [{"role": "user", "content": "hi"}])
    assert "thinking" not in captured[-1]["json"]
    assert "reasoning_effort" not in captured[-1]["json"]


def test_deepseek_uses_reasoning_when_content_is_empty(monkeypatch):
    class _Thinking:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": None, "reasoning_content": "  想好了  "}}]}

    monkeypatch.setattr("app.ai.httpx.post", lambda *args, **kwargs: _Thinking())
    assert complete("https://api.deepseek.com", "sk-ds", "deepseek-flash", [{"role": "user", "content": "hi"}]) == "想好了"


def test_chat_error_keeps_upstream_message(monkeypatch):
    body = (
        '{"error":{"message":"This account only allows Codex official clients","type":"forbidden_error"}}'
        'event: error\ndata: {"error":{"message":"Upstream request failed"}}\n'
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(403, text=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.ai.httpx.post", fake_post)
    try:
        complete("https://example.com/v1", "sk-test", "demo", [{"role": "user", "content": "ok"}])
    except AiError as exc:
        assert "403" in str(exc)
        assert "Codex official clients" in str(exc)
    else:
        raise AssertionError("expected AiError")


class _EventStream:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.status_code = 200
        self.request = httpx.Request("POST", "https://example.com/v1/chat/completions")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self):
        yield from self._lines


def test_chat_stream_shows_reasoning_then_drops_failed_turn(monkeypatch):
    lead_id = None
    captured: list[dict] = []

    def fake_stream(method, url, headers=None, timeout=None, **kwargs):
        captured.append({"url": url, "json": kwargs.get("json")})
        if len(captured) == 1:
            return _EventStream(
                [
                    "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "先想"}}]}),
                    "data: " + json.dumps({"choices": [{"delta": {"content": "正文甲"}}]}),
                    "data: " + json.dumps({"choices": [{"delta": {"content": "正文乙"}}]}),
                    "data: [DONE]",
                ]
            )
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.ai.httpx.stream", fake_stream)
    try:
        with TestClient(app) as client:
            _clear_ai()
            _configure_ai(client, "https://example.com/v1", "demo-model", "sk-stream-key-1234")
            created = client.post(
                "/api/leads",
                json={"url": "https://example.com/desk-stream", "title": "流式", "excerpt": "帖子"},
            )
            assert created.status_code == 201
            lead_id = created.json()["id"]
            streamed = client.post(
                f"/api/leads/{lead_id}/chat/stream",
                json={"message": "接着改", "draft": "当前稿"},
            )
            assert streamed.status_code == 200, streamed.text
            assert '"reasoning": "先想"' in streamed.text
            assert '"delta": "正文甲"' in streamed.text
            assert '"delta": "正文乙"' in streamed.text
            assert '"done": true' in streamed.text
            assert captured[0]["json"]["stream"] is True
            stored = client.get(f"/api/leads/{lead_id}/messages").json()
            assert stored[-2]["body"] == "接着改"
            assert stored[-1]["body"] == "正文甲正文乙"
            assert stored[-1]["reasoning"] == "先想"

            failed = client.post(
                f"/api/leads/{lead_id}/chat/stream",
                json={"message": "这句不该留下", "draft": "当前稿"},
            )
            assert failed.status_code == 200
            assert "连不上模型接口" in failed.text
            assistant = [item for item in captured[1]["json"]["messages"] if item["role"] == "assistant"]
            assert assistant[-1]["content"] == "正文甲正文乙"
            assert assistant[-1]["reasoning_content"] == "先想"
            after = client.get(f"/api/leads/{lead_id}/messages").json()
            assert len(after) == len(stored)
            assert all(item["body"] != "这句不该留下" for item in after)
    finally:
        if lead_id is not None:
            _delete_lead(lead_id)
        _clear_ai()


def test_legacy_ai_settings_become_a_source():
    _clear_ai()
    with SessionLocal() as session:
        session.merge(Setting(key="ai_base_url", value="https://api.deepseek.com/"))
        session.merge(Setting(key="ai_model", value="deepseek-chat"))
        session.merge(Setting(key="ai_api_key", value="sk-legacy-key-abcd"))
        session.merge(Setting(key="ai_model_list", value='["deepseek-chat","deepseek-reasoner"]'))
        session.merge(Setting(key="ai_model_list_base", value="https://api.deepseek.com"))
        session.commit()
    try:
        with TestClient(app) as client:
            view = client.get("/api/settings/ai").json()
        assert view["configured"] is True
        assert view["model"] == "deepseek-chat"
        assert len(view["sources"]) == 1
        source = view["sources"][0]
        assert source["name"] == "DeepSeek"
        assert source["base_url"] == "https://api.deepseek.com"
        assert source["models"] == ["deepseek-chat", "deepseek-reasoner"]
        assert source["key_hint"] == "abcd"
        assert "sk-legacy-key" not in json.dumps(view)
        with SessionLocal() as session:
            assert session.get(Setting, "ai_base_url") is None
            assert session.get(Setting, "ai_api_key") is None
        _migrate_ai_sources()
        with SessionLocal() as session:
            assert len(session.scalars(select(AiSource)).all()) == 1
    finally:
        _clear_ai()


def _purge_tracked(lead_id: int | None, monitor_id: int | None = None) -> None:
    from app.models import Monitor, MyReply, ReplyEvent

    with SessionLocal() as session:
        if monitor_id is not None:
            row = session.get(Monitor, monitor_id)
            if row is not None:
                session.delete(row)
        if lead_id is not None:
            for reply in session.scalars(select(MyReply).where(MyReply.lead_id == lead_id)).all():
                for event in session.scalars(select(ReplyEvent).where(ReplyEvent.reply_id == reply.id)).all():
                    session.delete(event)
                session.delete(reply)
        session.commit()
    if lead_id is not None:
        _delete_lead(lead_id)


def test_url_monitor_routes_post_and_comment():
    post_lead = None
    comment_lead = None
    post_monitor = None
    comment_monitor = None
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/monitors",
                json={"kind": "url", "content": "https://www.youtube.com/watch?v=trackvid1"},
            )
            assert created.status_code == 201
            assert created.json()["platform_id"] == "youtube"
            post_monitor = created.json()["id"]
            matched = client.get(
                "/api/leads/match",
                params={"url": "https://www.youtube.com/watch?v=trackvid1"},
            ).json()
            assert matched["lead"]["status"] == "unread"
            assert matched["on_comment"] is False
            post_lead = matched["lead"]["id"]

            noted = client.post(
                "/api/monitors",
                json={
                    "kind": "url",
                    "content": "https://www.reddit.com/r/ChatGPT/comments/trackcmt1/title/cmt999/",
                },
            )
            assert noted.status_code == 201
            assert noted.json()["platform_id"] == "reddit"
            comment_monitor = noted.json()["id"]
            matched = client.get(
                "/api/leads/match",
                params={"url": "https://www.reddit.com/r/ChatGPT/comments/trackcmt1/title/cmt999/"},
            ).json()
            assert matched["on_comment"] is True
            assert matched["lead"]["status"] == "replied"
            assert matched["lead"]["reply_count"] == 1
            comment_lead = matched["lead"]["id"]
            today = client.get("/api/today").json()
            assert post_lead in [item["id"] for item in today["needs_reply"]]
            assert comment_lead in [item["id"] for item in today["followups"]]
    finally:
        _purge_tracked(post_lead, post_monitor)
        _purge_tracked(comment_lead, comment_monitor)


def test_followups_put_unseen_first():
    from app.models import ReplyEvent
    from app.timeutil import utcnow

    quiet_id = None
    loud_id = None
    try:
        with TestClient(app) as client:
            quiet = client.post(
                "/api/leads",
                json={"url": "https://www.reddit.com/r/a/comments/quietpost/t/", "title": "安静"},
            )
            loud = client.post(
                "/api/leads",
                json={"url": "https://www.reddit.com/r/a/comments/loudpost/t/", "title": "有追问"},
            )
            assert quiet.status_code == 201
            assert loud.status_code == 201
            quiet_id = quiet.json()["id"]
            loud_id = loud.json()["id"]
            assert (
                client.post(
                    f"/api/leads/{quiet_id}/replies",
                    json={"comment_url": "https://www.reddit.com/r/a/comments/quietpost/t/qc1/", "body": "回了"},
                ).status_code
                == 201
            )
            loud_reply = client.post(
                f"/api/leads/{loud_id}/replies",
                json={"comment_url": "https://www.reddit.com/r/a/comments/loudpost/t/lc1/", "body": "回了"},
            )
            assert loud_reply.status_code == 201
            reply_id = loud_reply.json()["id"]
        with SessionLocal() as session:
            session.add(
                ReplyEvent(
                    reply_id=reply_id,
                    kind="new_child",
                    detail="有人接话",
                    created_at=utcnow().replace(tzinfo=None),
                )
            )
            session.commit()
        with TestClient(app) as client:
            today = client.get("/api/today").json()
            follow_ids = [item["id"] for item in today["followups"]]
            assert follow_ids.index(loud_id) < follow_ids.index(quiet_id)
            loud_item = next(item for item in today["followups"] if item["id"] == loud_id)
            assert loud_item["unseen"][0]["kind"] == "new_child"
            assert loud_item["comment_urls"]
    finally:
        _purge_tracked(quiet_id)
        _purge_tracked(loud_id)
