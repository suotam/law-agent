"""Tests for the shared embeddings client."""

from __future__ import annotations

from law_agent.core.embeddings import get_embeddings


def test_get_embeddings_is_a_singleton() -> None:
    """A fresh instance per call means a fresh, empty rate limiter per call --
    the very thing that lets a bulk import blow through the intended request
    budget across documents."""
    assert get_embeddings() is get_embeddings()


def test_provider_preferences_reach_every_embedding_request(monkeypatch) -> None:
    """The routing constraint is the privacy guarantee for chunk text, so it
    must ride on the request itself, not only on the account."""
    from types import SimpleNamespace

    from law_agent.core import embeddings as module

    calls: list[dict] = []

    class FakeEmbeddings:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0]) for _ in kwargs["input"]])

    monkeypatch.setattr(module.settings, "openrouter_provider", {"zdr": True})
    client = module.OpenRouterEmbeddings()
    client._client = SimpleNamespace(embeddings=FakeEmbeddings())

    assert client.embed_documents(["a", "b"]) == [[0.0], [0.0]]
    assert calls[0]["provider"].model_dump(exclude_unset=True) == {"zdr": True}


def test_empty_provider_preferences_are_not_sent(monkeypatch) -> None:
    from types import SimpleNamespace

    from law_agent.core import embeddings as module

    calls: list[dict] = []

    class FakeEmbeddings:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0])])

    monkeypatch.setattr(module.settings, "openrouter_provider", {})
    client = module.OpenRouterEmbeddings()
    client._client = SimpleNamespace(embeddings=FakeEmbeddings())

    client.embed_query("a")
    assert calls[0]["provider"] is module.UNSET


def test_embedding_client_retries_a_429(monkeypatch) -> None:
    """A provider answering 429 while overloaded must not abort a bulk import;
    the SDK's default retry list covers only 5xx, so the override is what this
    checks."""
    import httpx
    from openrouter import OpenRouter

    from law_agent.core import embeddings as module

    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"message": "overloaded"}})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "model": "m",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    monkeypatch.setattr(module.settings, "openrouter_provider", {})
    client = module.OpenRouterEmbeddings()
    client._client = OpenRouter(
        api_key="k",
        retry_config=module._RETRIES,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.embed_query("a") == [0.1, 0.2]
    assert len(calls) == 3
