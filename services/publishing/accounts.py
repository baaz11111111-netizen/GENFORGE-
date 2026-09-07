"""Account management + token architecture (§6, §7, §24).

Security rules enforced here:

* Access/refresh tokens live ONLY in the environment or in the local secret
  store file (``publishing_state/secrets.json``) — never in project.json,
  campaign JSON, n8n exports, telemetry, logs, or UI state.
* Account records carry a token REFERENCE (e.g. ``"env:YOUTUBE_ACCESS_TOKEN"``
  or ``"store:youtube:main"``), never the secret itself.
* Tokens are masked everywhere a human could see them.
* Token expiry drives account state: connected / expired / needs_reauthorization.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from services.publishing.models import PublishingAccount

STATE_DIR = "publishing_state"
ACCOUNTS_FILE = os.path.join(STATE_DIR, "accounts.json")
SECRETS_FILE = os.path.join(STATE_DIR, "secrets.json")


def mask_token(token: str) -> str:
    """Never display a complete token (§6)."""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}…{token[-2:]} ({len(token)} chars)"


class TokenStore:
    """Resolve/store secrets from env vars first, then the local secret file.

    Resolution order for a reference:
      ``env:NAME``        → environment variable NAME
      ``store:key``       → publishing_state/secrets.json entry
      bare NAME           → env NAME, then store key (compatibility)
    """

    def __init__(self, secrets_path: str = SECRETS_FILE):
        self.secrets_path = secrets_path

    # ------------------------------------------------------- resolution
    def resolve(self, reference: str) -> str:
        """Return the secret for a reference, or '' when unavailable."""
        if not reference:
            return ""
        if reference.startswith("env:"):
            return os.environ.get(reference[4:], "")
        if reference.startswith("store:"):
            entry = self._read_file().get(reference[6:])
            if isinstance(entry, dict):
                return entry.get("token", "")
            return entry or ""
        if os.environ.get(reference, ""):
            return os.environ[reference]
        entry = self._read_file().get(reference)
        if isinstance(entry, dict):
            return entry.get("token", "")
        return entry or ""

    # -------------------------------------------------------- mutation
    def store(self, key: str, token: str, refresh_token: str = "",
              expires_at: str = "") -> str:
        """Persist a secret locally; returns the reference to keep on accounts."""
        if not key or not token:
            raise ValueError("Token key and value are required.")
        if "\n" in key or "\r" in key:
            raise ValueError("Token key must be a single-line identifier.")
        secrets = self._read_file()
        secrets[key] = {"token": token, "refresh_token": refresh_token,
                        "expires_at": expires_at,
                        "stored_at": datetime.now(timezone.utc).isoformat()}
        os.makedirs(os.path.dirname(self.secrets_path) or os.curdir, exist_ok=True)
        with open(self.secrets_path, "w", encoding="utf-8") as handle:
            json.dump(secrets, handle, indent=2)
        return f"store:{key}"

    def delete(self, key: str) -> bool:
        secrets = self._read_file()
        if key not in secrets:
            return False
        del secrets[key]
        with open(self.secrets_path, "w", encoding="utf-8") as handle:
            json.dump(secrets, handle, indent=2)
        return True

    def expiry(self, reference: str) -> datetime | None:
        """Stored expiry for a store: reference (env tokens carry no expiry here)."""
        if not reference.startswith("store:"):
            return None
        entry = self._read_file().get(reference[6:])
        if not isinstance(entry, dict) or not entry.get("expires_at"):
            return None
        try:
            return datetime.fromisoformat(entry["expires_at"])
        except ValueError:
            return None

    def _read_file(self) -> dict[str, Any]:
        if not os.path.isfile(self.secrets_path):
            return {}
        try:
            with open(self.secrets_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}


class AccountStore:
    """Connected platform accounts with honest lifecycle states."""

    def __init__(self, accounts_path: str = ACCOUNTS_FILE, token_store: TokenStore | None = None):
        self.accounts_path = accounts_path
        self.tokens = token_store or TokenStore()

    # ------------------------------------------------------- persistence
    def _load(self) -> dict[str, dict]:
        if not os.path.isfile(self.accounts_path):
            return {}
        try:
            with open(self.accounts_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, records: dict[str, dict]) -> None:
        os.makedirs(os.path.dirname(self.accounts_path) or os.curdir, exist_ok=True)
        with open(self.accounts_path, "w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=2)

    # --------------------------------------------------------- operations
    def connect(self, platform: str, display_name: str, token_reference: str = "",
                external_account_id: str = "", capabilities: dict | None = None) -> PublishingAccount:
        """Register an account. Requires a resolvable token reference (§6)."""
        if not platform or not display_name:
            raise ValueError("Platform and display name are required.")
        if token_reference and not self.tokens.resolve(token_reference):
            raise ValueError(
                f"Token reference {token_reference!r} does not resolve to a secret; "
                "refusing to connect an account without credentials."
            )
        account = PublishingAccount(
            platform=platform, display_name=display_name,
            external_account_id=external_account_id,
            token_reference=token_reference,
            capabilities=capabilities or {},
        )
        account.mark(self._derive_state(account))
        records = self._load()
        records[account.account_id] = account.model_dump()
        self._save(records)
        return account

    def disconnect(self, account_id: str) -> bool:
        records = self._load()
        account = records.get(account_id)
        if account is None:
            return False
        account["state"] = "disconnected"
        account["connected"] = False
        account["token_reference"] = ""
        account["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save(records)
        return True

    def get(self, account_id: str) -> PublishingAccount | None:
        record = self._load().get(account_id)
        if record is None:
            return None
        account = PublishingAccount(**record)
        account.mark(self._derive_state(account))
        return account

    def list(self, platform: str | None = None) -> list[PublishingAccount]:
        accounts = [PublishingAccount(**record) for record in self._load().values()]
        for account in accounts:
            account.mark(self._derive_state(account))
        if platform:
            accounts = [a for a in accounts if a.platform == platform]
        return sorted(accounts, key=lambda a: a.created_at)

    def _derive_state(self, account: PublishingAccount) -> str:
        """connected / expired / needs_reauthorization / disconnected (§7)."""
        if not account.token_reference:
            return "disconnected"
        if not self.tokens.resolve(account.token_reference):
            return "needs_reauthorization"
        expiry = self.tokens.expiry(account.token_reference)
        if expiry is not None:
            if expiry.tzinfo is None:  # treat naive stored expiry as UTC rather than crash
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                return "expired"
        return "connected"


__all__ = [
    "STATE_DIR", "ACCOUNTS_FILE", "SECRETS_FILE",
    "mask_token", "TokenStore", "AccountStore",
]
