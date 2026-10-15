from langchain_openrouter import ChatOpenRouter

from law_agent.config import settings


def get_llm() -> ChatOpenRouter:
    return ChatOpenRouter(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        # Routing constraints ride on every request rather than living in the
        # account settings, so a fresh key or a second deployment cannot quietly
        # fall back to providers that retain data.
        openrouter_provider=settings.openrouter_provider or None,
    )
