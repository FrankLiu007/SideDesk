import json
from urllib.parse import urlparse

import httpx

DEEPSEEK_HOST = "api.deepseek.com"


class AiError(Exception):
    pass


def list_models(base_url: str, api_key: str) -> list[str]:
    url = base_url.rstrip("/") + "/models"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AiError("连不上模型接口，或返回不是模型列表") from exc
    except ImportError as exc:
        raise AiError(_import_message(exc)) from exc
    names = _model_names(payload)
    if not names:
        raise AiError("接口没有返回模型")
    return names


def probe(base_url: str, api_key: str, model: str) -> str:
    return complete(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": "Reply with the single word ok."}],
    )


def complete(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    content, reasoning = complete_parts(base_url, api_key, model, messages)
    text = content.strip() or reasoning.strip()
    if not text:
        raise AiError("模型没有返回内容")
    return text


def complete_parts(base_url: str, api_key: str, model: str, messages: list[dict]) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/chat/completions"
    body = _request_body(base_url, model, messages, stream=False)
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc) from exc
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise AiError("连不上模型接口，或返回里没有回复") from exc
    except ImportError as exc:
        raise AiError(_import_message(exc)) from exc
    if not isinstance(message, dict):
        raise AiError("连不上模型接口，或返回里没有回复")
    return _content_text(message.get("content")), _reasoning_text(message)


def iter_parts(base_url: str, api_key: str, model: str, messages: list[dict]):
    url = base_url.rstrip("/") + "/chat/completions"
    body = _request_body(base_url, model, messages, stream=True)
    try:
        with httpx.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=120,
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise _status_error(
                    httpx.HTTPStatusError(
                        f"模型接口返回 {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                )
            for line in response.iter_lines():
                for kind, text in _stream_line(line):
                    yield kind, text
    except AiError:
        raise
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AiError("连不上模型接口，或返回里没有回复") from exc
    except ImportError as exc:
        raise AiError(_import_message(exc)) from exc


def _request_body(base_url: str, model: str, messages: list[dict], *, stream: bool) -> dict:
    body: dict = {"model": model, "messages": messages}
    if stream:
        body["stream"] = True
    if _is_deepseek(base_url):
        # 思考开着。助手消息要带回 reasoning_content，否则下一轮会 400。
        body["thinking"] = {"type": "enabled"}
    return body


def _is_deepseek(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "").lower() == DEEPSEEK_HOST


def source_label(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if host == DEEPSEEK_HOST:
        return "DeepSeek"
    return host or "模型来源"


def _reasoning_text(message: dict) -> str:
    raw = message.get("reasoning_content")
    if raw is None:
        raw = message.get("reasoning")
    return _raw_text(raw)


def _stream_line(line: str):
    text = line.strip()
    if not text.startswith("data:"):
        return
    data = text[5:].strip()
    if not data or data == "[DONE]":
        return
    try:
        payload = json.loads(data)
    except ValueError:
        return
    if isinstance(payload, dict) and payload.get("error"):
        detail = _error_text_from_payload(payload)
        raise AiError(detail or "模型接口返回错误")
    if not isinstance(payload, dict):
        return
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return
    reasoning = _reasoning_text(delta)
    if reasoning:
        yield "reasoning", reasoning
    content = _raw_text(delta.get("content"))
    if content:
        yield "content", content


def _error_text_from_payload(payload: dict) -> str:
    error = payload.get("error")
    message = ""
    if isinstance(error, dict):
        raw = error.get("message") or ""
        if isinstance(raw, str):
            message = raw
    elif isinstance(error, str):
        message = error
    return " ".join(message.split())[:240]


def _content_text(content: object) -> str:
    return _raw_text(content).strip()


def _raw_text(content: object) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    if not isinstance(content, str):
        return ""
    return content


def _status_error(exc: httpx.HTTPStatusError) -> AiError:
    detail = _error_text(exc.response)
    if detail:
        return AiError(f"模型接口返回 {exc.response.status_code}：{detail}")
    return AiError(f"模型接口返回 {exc.response.status_code}")


def _error_text(response: httpx.Response) -> str:
    payload: object = None
    try:
        payload = response.json()
    except ValueError:
        text = (response.text or "").lstrip()
        if text.startswith("{"):
            try:
                payload, _end = json.JSONDecoder().raw_decode(text)
            except ValueError:
                payload = None
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            raw = error.get("message") or ""
            if isinstance(raw, str):
                message = raw
        elif isinstance(error, str):
            message = error
    message = " ".join(message.split())
    return message[:240]


def _import_message(exc: ImportError) -> str:
    if "socks" in str(exc).lower():
        return "系统走了 SOCKS 代理，但当前环境没装 socks 支持"
    return "连不上模型接口"


def _model_names(payload: object) -> list[str]:
    items: list[object] = []
    if isinstance(payload, dict):
        raw = payload.get("data")
        if not isinstance(raw, list):
            raw = payload.get("models")
        if isinstance(raw, list):
            items = raw
    elif isinstance(payload, list):
        items = payload
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = ""
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw_name = item.get("id") or item.get("name") or ""
            if isinstance(raw_name, str):
                name = raw_name.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names
