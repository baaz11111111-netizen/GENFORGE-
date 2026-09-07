"""Common foundation for REAL platform adapters (§3, §46).

Adapters resolve tokens through the TokenStore (references only — the UI
never hands raw secrets to provider code), use the injectable transport, and
convert every platform answer into an honest ProviderResponse.
"""

from __future__ import annotations

from services.publishing.accounts import TokenStore
from services.publishing.base import BaseProvider, ProviderResponse
from services.publishing.http_client import (HttpResponse, TransportError, UrllibTransport,
                                             classify_http_error, classify_transport_error)


class RealProviderBase(BaseProvider):
    """Token handling + transport plumbing shared by all real adapters."""

    provider_name = "real"

    def __init__(self, token_reference: str = "", token_store: TokenStore | None = None,
                 transport=None, external_account_id: str = ""):
        self.token_reference = token_reference
        self.tokens = token_store or TokenStore()
        self.transport = transport or UrllibTransport()
        self.external_account_id = external_account_id

    # ------------------------------------------------------------- tokens
    def _token(self) -> str:
        return self.tokens.resolve(self.token_reference)

    def _missing_token(self) -> ProviderResponse:
        return ProviderResponse(provider_status="FAILED", error_kind="invalid_credentials",
                                message="No resolvable token for this account.")

    def _auth_headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        headers.update(extra or {})
        return headers

    def authenticate(self) -> bool:
        """True only when a token resolves AND the platform accepts it."""
        if not self._token():
            return False
        return self._ping()

    def _ping(self) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------- helpers
    def _request(self, method: str, url: str, headers: dict | None = None,
                 json_body: dict | None = None, data: bytes | None = None,
                 context: str = "upload") -> HttpResponse | ProviderResponse:
        """HttpResponse on any HTTP answer; ProviderResponse on network faults."""
        try:
            response = self.transport.request(method, url, headers=headers or self._auth_headers(),
                                              json_body=json_body, data=data)
        except TransportError as exc:
            kind, message = classify_transport_error(exc)
            return ProviderResponse(provider_status="FAILED", error_kind=kind, message=message)
        if response.ok:
            return response
        kind, message = classify_http_error(response.status, response.body, context=context)
        retry_after = None
        raw = response.headers.get("Retry-After") if response.headers else None
        if raw and raw.isdigit():
            retry_after = float(raw)
        return ProviderResponse(provider_status="FAILED", error_kind=kind, message=message,
                                retry_after_seconds=retry_after)

    @staticmethod
    def _asset_bytes(job) -> bytes:
        with open(job.asset_path, "rb") as handle:
            return handle.read()


__all__ = ["RealProviderBase"]
