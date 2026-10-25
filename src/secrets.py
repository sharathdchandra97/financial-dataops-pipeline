"""
Secrets management helper.

Priority:
  1. HashiCorp Vault (KV v2) – if VAULT_ADDR + VAULT_TOKEN are set
  2. Environment variables (fallback for local dev / CI)

Usage:
    from src.secrets import get_secret
    db_password = get_secret("database/password")
"""
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


class VaultClient:
    """Minimal Vault KV v2 client that avoids adding hvac as a hard dep."""

    def __init__(self, addr: str, token: str):
        self.addr = addr.rstrip("/")
        self.token = token

    def read(self, path: str) -> Optional[dict]:
        """Read a secret from Vault KV v2 at mount=secret, path=<path>."""
        import urllib.request
        import json
        url = f"{self.addr}/v1/secret/data/{path}"
        req = urllib.request.Request(url, headers={"X-Vault-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read())
                return payload["data"]["data"]
        except Exception as exc:
            logger.warning("Vault read failed for '%s': %s", path, exc)
            return None


@lru_cache(maxsize=128)
def get_secret(key: str, vault_path: Optional[str] = None) -> Optional[str]:
    """
    Return a secret value.

    Args:
        key:        Environment variable name OR Vault field name.
        vault_path: Vault KV path (e.g., 'dataops/prod'). If omitted,
                    falls back to env var lookup only.
    """
    vault_addr  = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")

    if vault_addr and vault_token and vault_path:
        client = VaultClient(vault_addr, vault_token)
        secrets = client.read(vault_path)
        if secrets and key in secrets:
            logger.info("Secret '%s' resolved from Vault path '%s'", key, vault_path)
            return secrets[key]

    # Fallback to environment variable
    value = os.getenv(key)
    if value:
        logger.info("Secret '%s' resolved from environment variable", key)
    else:
        logger.warning("Secret '%s' not found in Vault or environment", key)
    return value
