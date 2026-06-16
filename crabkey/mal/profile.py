"""Provider profile — declarative configuration for every inference provider.

A ProviderProfile declares auth, endpoints, client quirks, and request-time
quirks in one place.  Transports read this instead of receiving many flags.

Profiles are DECLARATIVE — they describe the provider's behaviour.
They do NOT own client construction, credential rotation, or streaming.
Those stay on PluginModelProvider.

Ported from Hermes Agent's providers/base.py pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel for "omit temperature entirely" (some providers manage it server-side).
OMIT_TEMPERATURE = object()


@dataclass
class ProviderProfile:
    """Base provider profile — subclass or instantiate with overrides."""

    # ── Identity ────────────────────────────────────────────────
    name: str
    api_mode: str = "chat_completions"    # "chat_completions" | "anthropic_messages"
    aliases: tuple = ()

    # ── Human-readable metadata ──────────────────────────────────
    display_name: str = ""        # shown in picker/labels
    description: str = ""         # picker subtitle
    signup_url: str = ""          # shown during first-time setup

    # ── Auth & endpoints ─────────────────────────────────────────
    env_vars: tuple = ()          # env var names to check for the API key
    base_url: str = ""
    models_url: str = ""          # explicit models endpoint; falls back to {base_url}/models
    auth_type: str = "api_key"    # "api_key" | "oauth_device_code" | "oauth_external"
    supports_health_check: bool = True

    # ── Vision support ────────────────────────────────────────────
    supports_vision: bool = False
    supports_vision_tool_messages: bool = True

    # ── Model catalog ─────────────────────────────────────────────
    # Curated fallback list shown when live fetch fails.
    # Only agentic (tool-calling) models should appear here.
    fallback_models: tuple = ()

    # hostname for URL→provider reverse-mapping; derived from base_url when empty.
    hostname: str = ""

    # ── Client-level quirks ───────────────────────────────────────
    default_headers: dict[str, str] = field(default_factory=dict)

    # ── Request-level quirks ──────────────────────────────────────
    # None = use caller default, OMIT_TEMPERATURE = don't send the field
    fixed_temperature: Any = None
    default_max_tokens: int | None = None
    default_aux_model: str = ""   # cheap model for auxiliary tasks (reflection, etc.)

    # ── Hooks (override in subclass for complex providers) ────────

    def get_hostname(self) -> str:
        """Return base hostname for URL-based provider detection."""
        if self.hostname:
            return self.hostname
        if self.base_url:
            from urllib.parse import urlparse
            return urlparse(self.base_url).hostname or ""
        return ""

    def prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Provider-specific message preprocessing. Default: pass-through."""
        return messages

    def build_extra_body(
        self, *, session_id: str | None = None, **context: Any
    ) -> dict[str, Any]:
        """Provider-specific extra_body fields merged into the API call. Default: {}."""
        return {}

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Provider-specific kwargs split between extra_body and top-level api_kwargs.

        Returns (extra_body_additions, top_level_kwargs).
        """
        return {}, {}

    def get_max_tokens(self, model: str | None) -> int | None:
        """Return the default max_tokens cap for *model*. Override for per-model limits."""
        return self.default_max_tokens

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Fetch the live model list from the provider's models endpoint.

        Returns a list of model ID strings, or None if the fetch failed.
        Resolution order: self.models_url → self.base_url + "/models".
        """
        url = (self.models_url or "").strip()
        if not url:
            if not self.base_url:
                return None
            url = self.base_url.rstrip("/") + "/models"

        import json
        import urllib.request

        req = urllib.request.Request(url)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "crabkey")
        for k, v in self.default_headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            items = data if isinstance(data, list) else data.get("data", [])
            return [m["id"] for m in items if isinstance(m, dict) and "id" in m]
        except Exception as exc:
            logger.debug("fetch_models(%s): %s", self.name, exc)
            return None
