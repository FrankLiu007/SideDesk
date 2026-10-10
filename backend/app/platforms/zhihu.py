import hashlib
import re
from urllib.parse import urlparse

from app.platforms.base import ParsedLink

_QUESTION = re.compile(r"/question/(\d+)")
_ANSWER = re.compile(r"/answer/(\d+)")
_ARTICLE = re.compile(r"/p/(\d+)")


def parse_url(url: str) -> ParsedLink | None:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if "zhihu.com" not in host:
        return None
    path = parsed.path or ""
    answer = _ANSWER.search(path)
    question = _QUESTION.search(path)
    if answer:
        aid = answer.group(1)
        if question:
            post_url = f"https://www.zhihu.com/question/{question.group(1)}/answer/{aid}"
        else:
            post_url = f"https://www.zhihu.com/answer/{aid}"
        return ParsedLink("zhihu", f"a{aid}", "", post_url, post_url)
    if question:
        qid = question.group(1)
        post_url = f"https://www.zhihu.com/question/{qid}"
        return ParsedLink("zhihu", f"q{qid}", "", post_url, post_url)
    article = _ARTICLE.search(path)
    if article and "zhuanlan" in host:
        pid = article.group(1)
        post_url = f"https://zhuanlan.zhihu.com/p/{pid}"
        return ParsedLink("zhihu", f"p{pid}", "", post_url, post_url)
    digest = hashlib.sha1(cleaned.encode()).hexdigest()[:16]
    return ParsedLink("zhihu", digest, "", cleaned, cleaned)
