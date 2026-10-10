from datetime import datetime, timezone

import httpx

from app.config import settings
from app.diff import ReplySnapshot
from app.identity import reddit_ids
from app.timeutil import as_utc

USER_AGENT_APP = "SideDesk:followup:1.0"


class RedditNotConfigured(RuntimeError):
    pass


class RedditError(RuntimeError):
    pass


def archived_ids_from_listing(payload: object) -> set[str]:
    children = payload.get("data", {}).get("children", []) if isinstance(payload, dict) else []
    found: set[str] = set()
    for child in children:
        data = child.get("data") or {}
        post_id = data.get("id") or ""
        if post_id and data.get("archived"):
            found.add(post_id)
    return found


def parse_submission(payload: object) -> dict:
    if not isinstance(payload, list) or not payload:
        raise RedditError("Reddit 没有返回这篇帖子")
    children = payload[0].get("data", {}).get("children", []) if isinstance(payload[0], dict) else []
    data = next((item.get("data") or {} for item in children if item.get("kind") == "t3"), None)
    if not data:
        raise RedditError("Reddit 没有返回这篇帖子")
    return {
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "body": data.get("selftext") or "",
    }


# These sites send X-Frame-Options or CSP frame-ancestors, so an iframe stays blank.
FRAME_BLOCKED = {"reddit", "youtube", "bilibili", "v2ex", "zhihu"}


class RedditClient:
    """Application-only OAuth, same shape as Harken: basic client credentials, no password."""

    def __init__(self) -> None:
        self._token = ""

    def configured(self) -> bool:
        return bool(settings.reddit_client_id and settings.reddit_client_secret and settings.reddit_username)

    def _user_agent(self) -> str:
        return f"{USER_AGENT_APP} (by /u/{settings.reddit_username})"

    def _token_value(self) -> str:
        if self._token:
            return self._token
        if not self.configured():
            raise RedditNotConfigured("还没有配置 Reddit 密钥")
        response = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self._user_agent()},
            timeout=20,
        )
        if response.status_code >= 400:
            raise RedditError(f"Reddit 登录失败：{response.status_code}")
        self._token = response.json().get("access_token") or ""
        if not self._token:
            raise RedditError("Reddit 没有返回 access_token")
        return self._token

    def _get(self, path: str, params: dict) -> dict | list:
        response = httpx.get(
            f"https://oauth.reddit.com{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {self._token_value()}",
                "User-Agent": self._user_agent(),
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise RedditError(f"Reddit 请求失败：{response.status_code}")
        return response.json()

    def search(self, query: str, since: datetime | None, limit: int = 15) -> list[dict]:
        payload = self._get(
            "/search",
            {"q": query, "sort": "new", "type": "link", "limit": str(max(limit, 25)), "t": "month"},
        )
        children = payload.get("data", {}).get("children", []) if isinstance(payload, dict) else []
        found: list[dict] = []
        since_utc = as_utc(since) if since else None
        for child in children:
            data = child.get("data") or {}
            created = datetime.fromtimestamp(float(data.get("created_utc") or 0), tz=timezone.utc)
            if since_utc and created <= since_utc:
                continue
            post_id = data.get("id") or ""
            if not post_id:
                continue
            permalink = data.get("permalink") or ""
            found.append(
                {
                    "external_id": post_id,
                    "url": f"https://www.reddit.com{permalink}",
                    "title": data.get("title") or "",
                    "excerpt": (data.get("selftext") or "")[:500],
                    "author": data.get("author") or "",
                    "created_at": created.replace(tzinfo=None),
                    "created_utc": created,
                    "archived": bool(data.get("archived")),
                }
            )
            if len(found) >= limit:
                break
        return found

    def read_submission(self, post_id: str) -> dict:
        if self.configured():
            payload = self._get(f"/comments/{post_id}", {"limit": "1", "depth": "0", "raw_json": "1"})
        else:
            response = httpx.get(
                f"https://www.reddit.com/comments/{post_id}.json",
                params={"limit": "1", "raw_json": "1"},
                headers={"User-Agent": f"{USER_AGENT_APP} (local preview)"},
                timeout=8,
                follow_redirects=True,
                transport=httpx.HTTPTransport(local_address="0.0.0.0"),
            )
            if response.status_code >= 400:
                raise RedditError(f"Reddit 请求失败：{response.status_code}")
            payload = response.json()
        return parse_submission(payload)

    def archived_ids(self, post_ids: list[str]) -> set[str]:
        ids = [post_id for post_id in post_ids if post_id]
        if not ids:
            return set()
        if not self.configured():
            raise RedditNotConfigured("还没有配置 Reddit 密钥")
        found: set[str] = set()
        for start in range(0, len(ids), 100):
            chunk = ids[start : start + 100]
            payload = self._get("/api/info", {"id": ",".join(f"t3_{post_id}" for post_id in chunk)})
            found.update(archived_ids_from_listing(payload))
        return found

    def refresh_reply(self, comment_url: str) -> ReplySnapshot:
        post_id, comment_id = reddit_ids(comment_url)
        if not post_id or not comment_id:
            raise RedditError("这是帖子链接，不是评论链接，没法看谁接了你的话")
        payload = self._get(f"/comments/{post_id}", {"comment": comment_id, "depth": "2", "limit": "100"})
        if not isinstance(payload, list) or len(payload) < 2:
            raise RedditError("Reddit 没有返回这条评论")
        children = payload[1].get("data", {}).get("children", [])
        comment = next((item.get("data") or {} for item in children if item.get("kind") == "t1"), None)
        if not comment:
            return ReplySnapshot(score=None, child_ids=[], snippets={}, deleted=True)
        body = comment.get("body") or ""
        author = comment.get("author") or ""
        deleted = body in {"[deleted]", "[removed]"} or author == "[deleted]"
        replies = comment.get("replies")
        child_ids: list[str] = []
        snippets: dict[str, str] = {}
        if isinstance(replies, dict):
            for item in replies.get("data", {}).get("children", []):
                if item.get("kind") != "t1":
                    continue
                data = item.get("data") or {}
                cid = data.get("id") or ""
                if not cid:
                    continue
                child_ids.append(cid)
                snippet = (data.get("body") or "").strip().replace("\n", " ")
                author_name = data.get("author") or ""
                snippets[cid] = f"{author_name}: {snippet}"[:400]
        return ReplySnapshot(
            score=comment.get("score"),
            child_ids=child_ids,
            snippets=snippets,
            deleted=deleted,
        )
