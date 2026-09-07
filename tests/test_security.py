import pytest

import campaign_agent
from campaign_agent import trigger_n8n_webhook
from image_agent import parse_color_to_rgba


def test_webhook_requires_http_scheme():
    with pytest.raises(ValueError):
        trigger_n8n_webhook("file:///secret", {})


def test_webhook_rejects_loopback_target():
    with pytest.raises(ValueError):
        trigger_n8n_webhook("http://127.0.0.1:5678/webhook", {})


def test_webhook_does_not_follow_redirects(monkeypatch):
    class RedirectingOpener:
        def open(self, request, timeout):
            raise campaign_agent.urllib.error.HTTPError(
                request.full_url, 302, "redirect", {}, None
            )

    monkeypatch.setattr(
        campaign_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        campaign_agent.urllib.request,
        "build_opener",
        lambda *handlers: RedirectingOpener(),
    )

    assert trigger_n8n_webhook("https://public.example/webhook", {}) is False


def test_invalid_color_is_rejected():
    with pytest.raises(ValueError):
        parse_color_to_rgba("not-a-color")
