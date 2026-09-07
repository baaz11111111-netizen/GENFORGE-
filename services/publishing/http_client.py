"""Shared HTTP plumbing + error classification for real provider adapters.

The transport is injectable so the automated suite can script platform
responses without touching the network (§37). Production uses UrllibTransport.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class TransportError(Exception):
    """Network-level failure (timeout, DNS, reset). Never a platform answer."""


@dataclass
class HttpResponse:
    status: int
    body: dict | list | str = ""
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class UrllibTransport:
    """Minimal dependency-free HTTP client."""

    def request(self, method: str, url: str, headers: dict | None = None,
                json_body: dict | None = None, data: bytes | None = None,
                timeout: float = 30.0) -> HttpResponse:
        all_headers = dict(headers or {})
        payload = data
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            all_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=payload, method=method, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return self._wrap(response.status, response.read(), dict(response.headers))
        except urllib.error.HTTPError as exc:  # an HTTP answer (4xx/5xx) — not a network fault
            return self._wrap(exc.code, exc.read(), dict(exc.headers))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc

    @staticmethod
    def _wrap(status: int, raw: bytes, headers: dict) -> HttpResponse:
        text = raw.decode("utf-8", errors="replace") if raw else ""
        try:
            body = json.loads(text) if text else ""
        except json.JSONDecodeError:
            body = text
        return HttpResponse(status=status, body=body, headers=headers)


def classify_http_error(status: int, body, context: str = "upload") -> tuple[str, str]:
    """Map platform HTTP errors onto the §16 error taxonomy. Returns (kind, message)."""
    message = body.get("error", {}).get("message", str(body)) if isinstance(body, dict) else str(body)
    message = message[:300]
    if status == 401:
        return "expired_token", message or "Platform rejected the token (401)."
    if status == 403:
        lowered = message.lower()
        if "quota" in lowered or "rate" in lowered:
            return "rate_limited", message
        return "permission_denied", message or "Platform denied the request (403)."
    if status == 429:
        return "rate_limited", message or "Platform rate limit hit (429)."
    if status == 404:
        return "invalid_media", message or "Platform rejected the resource (404)."
    if status == 400:
        kind = "invalid_metadata" if context in ("publish", "schedule", "metadata") else "invalid_media"
        return kind, message or "Platform rejected the request (400)."
    if 500 <= status < 600:
        return "server_error", message or f"Platform server error ({status})."
    return "server_error", message or f"Unexpected platform status {status}."


def classify_transport_error(exc: TransportError) -> tuple[str, str]:
    message = str(exc)
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout", message
    if "name resolution" in lowered or "getaddrinfo" in lowered or "dns" in lowered:
        return "dns_failure", message
    return "connection_reset", message


__all__ = ["TransportError", "HttpResponse", "UrllibTransport",
           "classify_http_error", "classify_transport_error"]
