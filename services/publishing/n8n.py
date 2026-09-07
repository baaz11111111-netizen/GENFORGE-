"""n8n integration (§23) — secrets never leave the process.

Hard rules:

* Payloads sent to n8n are scrubbed: token/password/secret/credential keys
  are removed recursively before serialization.
* Webhook URLs are validated before any request is made.
* A successful webhook delivery is a DELIVERY confirmation, never a
  PUBLICATION confirmation (§23). The response says so explicitly.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlparse

_SECRET_KEY_MARKERS = ("token", "secret", "password", "credential", "authorization", "api_key", "apikey")


def validate_webhook_url(url: str) -> list[str]:
    """Return problems; empty list means the URL is safe to call."""
    problems: list[str] = []
    if not url or not url.strip():
        return ["Webhook URL is required."]
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        problems.append(f"Webhook URL scheme {parsed.scheme or '(none)'} must be http or https.")
    if not parsed.netloc:
        problems.append("Webhook URL has no host.")
    if parsed.username or parsed.password:
        problems.append("Webhook URL must not embed credentials.")
    return problems


def scrub_secrets(payload) -> dict:
    """Recursively drop anything that looks like a secret (§23/§24)."""
    if not isinstance(payload, dict):
        return {"value": payload}
    clean: dict = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            clean[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            clean[key] = scrub_secrets(value)
        elif isinstance(value, list):
            clean[key] = [scrub_secrets(item) if isinstance(item, dict) else item for item in value]
        else:
            clean[key] = value
    return clean


def build_n8n_payload(job, extra: dict | None = None) -> dict:
    """Publication facts only: ids, urls, statuses. Never credentials."""
    payload = {
        "event": "publication_result",
        "job_id": job.job_id,
        "project_id": job.project_id,
        "version_id": job.version_id,
        "platform": job.platform,
        "status": job.status,
        "external_post_id": job.external_post_id,
        "external_url": job.external_url,
        "scheduled_at": job.scheduled_at,
        "retry_count": job.retry_count,
        "note": "Webhook delivery is NOT publication confirmation.",
    }
    if extra:
        payload.update(extra)
    return scrub_secrets(payload)


def notify_n8n(webhook_url: str, payload: dict, transport=None, timeout: float = 10.0) -> dict:
    """POST the scrubbed payload. Returns an honest delivery report."""
    problems = validate_webhook_url(webhook_url)
    if problems:
        return {"delivered": False, "http_status": None, "problems": problems,
                "note": "Webhook URL rejected; nothing was sent."}
    body = json.dumps(scrub_secrets(payload)).encode("utf-8")

    def _default_transport(url: str, data: bytes) -> int:
        request = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status

    send = transport or _default_transport
    try:
        status = send(webhook_url.strip(), body)
    except (OSError, ValueError) as exc:
        return {"delivered": False, "http_status": None, "error": str(exc),
                "note": "Webhook delivery failed; publication status is unchanged."}
    delivered = status in (200, 201, 202, 204)
    return {"delivered": delivered, "http_status": status,
            "note": ("Webhook delivered. This is NOT publication confirmation — "
                     "only the platform can confirm publication.")
            if delivered else f"Webhook returned HTTP {status}."}


__all__ = ["validate_webhook_url", "scrub_secrets", "build_n8n_payload", "notify_n8n"]
