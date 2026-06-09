"""LLM backend abstraction for the POI pipeline.

Usage:
    from pipeline.llm_client import get_backend
    backend = get_backend("anthropic", "claude-haiku-4-5-20251001")  # POI classification
    text, in_tok, out_tok = await backend.complete(system, user)

    # Onboarding with web search
    backend = get_backend("anthropic", "claude-sonnet-4-6", tool_use=True)
    text, in_tok, out_tok = await backend.complete(system, user)

Models:
    Anthropic:
        claude-haiku-4-5-20251001   $0.80/M input   — fast, cheap (POI classifier)
        claude-sonnet-4-6           $3/M input      — balanced (onboarding with tool use)
        claude-opus-4-6             $15/M input     — max quality
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class LLMBackend(Protocol):
    """Minimal interface expected by the classifier."""

    model: str

    async def complete(self, system: str, user: str) -> tuple[str, int, int]:
        """Call the LLM and return (response_text, input_tokens, output_tokens)."""
        ...


# ──────────────────────────────────────────────────────────────
# Anthropic
# ──────────────────────────────────────────────────────────────

class AnthropicBackend:
    def __init__(self, api_key: str, model: str, tool_use: bool = False) -> None:
        from anthropic import AsyncAnthropic
        self.model = model
        self.tool_use = tool_use
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str) -> tuple[str, int, int]:
        """Call Claude with optional built-in web search (tool_use=True)."""
        messages = [{"role": "user", "content": user}]
        kwargs: dict = dict(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        if self.tool_use:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        total_in = 0
        total_out = 0

        # Agentic loop: keep going until end_turn (Claude may call web_search multiple times)
        for _ in range(10):
            response = await self._client.messages.create(**kwargs)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "".join(text_parts).strip(), total_in, total_out

            if response.stop_reason == "tool_use":
                # Append assistant turn and tool results for next iteration
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        # web_search_20250305 results are returned by Anthropic server-side
                        # but we still need to send back a tool_result placeholder
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "",
                        })
                messages.append({"role": "user", "content": tool_results})
                kwargs["messages"] = messages
                continue

            # Unexpected stop reason
            break

        # Fallback: return whatever text we have
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        return "".join(text_parts).strip(), total_in, total_out


# ──────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────

# Default model per Anthropic
_DEFAULT_MODEL: str = "claude-haiku-4-5-20251001"


def get_backend(backend_name: str, model: str | None = None, tool_use: bool = False) -> LLMBackend:
    """Return an Anthropic backend instance.

    Args:
        backend_name: must be "anthropic"
        model: nome del modello da usare. Se None usa claude-haiku-4-5-20251001.
        tool_use: se True, abilita tool use (web_search).
    """
    if backend_name != "anthropic":
        raise ValueError("Only 'anthropic' backend is supported")

    from app.config import settings

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY non configurata")

    resolved_model = model or _DEFAULT_MODEL
    return AnthropicBackend(api_key=settings.anthropic_api_key, model=resolved_model, tool_use=tool_use)
