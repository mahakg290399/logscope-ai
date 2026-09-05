"""OpenAI-compatible LLM client factory for LogScope AI providers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from openai import AsyncOpenAI

from logscope.config import Settings

logger = logging.getLogger(__name__)

# Default Omniroute local gateway (OpenAI-compatible).
DEFAULT_OMNIROUTE_BASE_URL = "http://127.0.0.1:20128/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


@dataclass(frozen=True)
class LLMClientHandle:
    """A configured chat client plus metadata for logging/telemetry."""

    name: str
    client: AsyncOpenAI
    model: str
    embedding_model: str
    base_url: Optional[str] = None


def _normalize_base_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return url.rstrip("/") + ("/" if url.endswith("/") else "")


def build_llm_clients(settings: Settings) -> List[LLMClientHandle]:
    """
    Build ordered LLM clients based on LOGSCOPE_AI_PROVIDER.

    Priority by provider mode:
    - nvidia: NVIDIA NIM only (uses NVIDIA_API_KEY + NVIDIA_BASE_URL)
    - omniroute: Omniroute only (uses OPENAI_API_KEY + LOGSCOPE_AI_BASE_URL)
    - gemini: Gemini AI Studio only
    - openai: Direct OpenAI only
    - auto: NVIDIA (if key), then Omniroute (if key), then Gemini (if key), then OpenAI
    """
    provider = settings.resolved_ai_provider()
    clients: List[LLMClientHandle] = []

    omni_key = settings.openai_api_key
    omni_base = settings.ai_base_url or DEFAULT_OMNIROUTE_BASE_URL
    gemini_key = settings.gemini_api_key or (
        settings.openai_api_key if provider == "gemini" else None
    )

    def add_nvidia() -> None:
        key = settings.nvidia_api_key or (settings.openai_api_key if provider == "nvidia" else None)
        if not key:
            return
        base = settings.nvidia_base_url or DEFAULT_NVIDIA_BASE_URL
        clients.append(
            LLMClientHandle(
                name="nvidia",
                client=AsyncOpenAI(api_key=key, base_url=base),
                model=settings.provider_chat_model("nvidia"),
                embedding_model=settings.provider_embedding_model("nvidia"),
                base_url=base,
            )
        )

    def add_omniroute() -> None:
        if not omni_key:
            return
        clients.append(
            LLMClientHandle(
                name="omniroute",
                client=AsyncOpenAI(api_key=omni_key, base_url=omni_base),
                model=settings.provider_chat_model("omniroute"),
                embedding_model=settings.provider_embedding_model("omniroute"),
                base_url=omni_base,
            )
        )

    def add_gemini() -> None:
        key = settings.gemini_api_key or settings.openai_api_key
        if not key:
            return
        base = settings.gemini_base_url or DEFAULT_GEMINI_BASE_URL
        clients.append(
            LLMClientHandle(
                name="gemini",
                client=AsyncOpenAI(api_key=key, base_url=base),
                model=settings.provider_chat_model("gemini"),
                embedding_model=settings.provider_embedding_model("gemini"),
                base_url=base,
            )
        )

    def add_openai() -> None:
        if not settings.openai_api_key:
            return
        clients.append(
            LLMClientHandle(
                name="openai",
                client=AsyncOpenAI(api_key=settings.openai_api_key),
                model=settings.provider_chat_model("openai"),
                embedding_model=settings.provider_embedding_model("openai"),
                base_url=None,
            )
        )

    if provider == "nvidia":
        add_nvidia()
    elif provider == "omniroute":
        add_omniroute()
    elif provider == "gemini":
        add_gemini()
    elif provider == "openai":
        add_openai()
    elif provider == "auto":
        add_nvidia()
        add_omniroute()
        add_gemini()
        # Only add direct OpenAI if base_url is unset/default OpenAI path and key present.
        # Keep last so local gateways are preferred.
        if settings.openai_api_key and not settings.ai_base_url:
            add_openai()
        elif settings.openai_api_key and settings.ai_base_url and not any(
            c.name == "omniroute" for c in clients
        ):
            add_omniroute()
    else:
        # Unknown provider: treat as custom OpenAI-compatible base URL.
        if settings.openai_api_key:
            base = settings.ai_base_url or DEFAULT_OMNIROUTE_BASE_URL
            clients.append(
                LLMClientHandle(
                    name=provider,
                    client=AsyncOpenAI(api_key=settings.openai_api_key, base_url=base),
                    model=settings.openai_model,
                    embedding_model=settings.openai_embedding_model,
                    base_url=base,
                )
            )

    if clients:
        logger.info(
            "Configured AI providers (order): %s",
            ", ".join(f"{c.name}:{c.model}" for c in clients),
        )
    else:
        logger.warning(
            "No AI provider credentials configured; heuristic triage will be used."
        )

    return clients


def primary_client(
    settings: Settings,
) -> Tuple[Optional[AsyncOpenAI], Optional[str], Optional[str]]:
    """Convenience: first client, its model name, and provider name."""
    handles = build_llm_clients(settings)
    if not handles:
        return None, None, None
    h = handles[0]
    return h.client, h.model, h.name
