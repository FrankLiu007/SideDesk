from pydantic import BaseModel


class LeadIn(BaseModel):
    url: str
    title: str = ""
    excerpt: str = ""
    author: str = ""
    platform_id: str | None = None


class DraftIn(BaseModel):
    body: str = ""


class ReplyIn(BaseModel):
    comment_url: str
    body: str = ""


class StatusIn(BaseModel):
    status: str


class MonitorIn(BaseModel):
    platform_id: str | None = None
    kind: str
    content: str
    enabled: bool = True


class MonitorPatch(BaseModel):
    content: str | None = None
    enabled: bool | None = None


class AiSourceIn(BaseModel):
    name: str = ""
    base_url: str = ""
    api_key: str = ""


class AiSourcePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class AiSelectionIn(BaseModel):
    source_id: int
    model: str = ""


class AiTestIn(BaseModel):
    model: str = ""


class ProjectIn(BaseModel):
    name: str
    background: str = ""
    followup_zh: str = ""
    followup_en: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    background: str | None = None
    followup_zh: str | None = None
    followup_en: str | None = None


class ChatIn(BaseModel):
    message: str = ""
    draft: str = ""


class AdoptIn(BaseModel):
    body: str = ""


STATUSES = {"unread", "drafted", "replied", "skipped"}
MONITOR_KINDS = {"keyword", "url"}
