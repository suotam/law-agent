"""The chat model must carry the same routing constraints as the embeddings."""

from __future__ import annotations

from law_agent.core import llm as module


def test_llm_carries_provider_preferences(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "openrouter_provider", {"zdr": True, "only": ["Nebius"]})
    chat = module.get_llm()
    assert chat.openrouter_provider == {"zdr": True, "only": ["Nebius"]}


def test_llm_omits_empty_provider_preferences(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "openrouter_provider", {})
    assert module.get_llm().openrouter_provider is None
