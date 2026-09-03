"""Credential Manager storage with environment fallback."""

from __future__ import annotations

import os


class CredentialStore:
    service_name = "FolioCross"

    def get(self, profile_id: str, env_name: str | None = None) -> str | None:
        if env_name:
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
        try:
            import keyring

            value = keyring.get_password(self.service_name, profile_id)
            return value.strip() if value else None
        except Exception:
            return None

    def set(self, profile_id: str, value: str) -> None:
        if not value.strip():
            raise ValueError("API Key 不能为空")
        import keyring

        keyring.set_password(self.service_name, profile_id, value.strip())
