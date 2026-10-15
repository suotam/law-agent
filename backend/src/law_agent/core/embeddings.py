from functools import lru_cache

from langchain_core.embeddings import Embeddings
from openrouter import OpenRouter
from openrouter.components import ProviderPreferences
from openrouter.types import UNSET
from openrouter.utils import BackoffStrategy, RetryConfig

from law_agent.config import settings
from law_agent.utils import RateLimiter

# The SDK's default retries cover only 5xx. Embedding hosts also answer 429 when
# overloaded (not just when *we* exceed a quota), and a bulk law import must
# survive that rather than abort halfway through — the local RateLimiter keeps
# our own request rate honest, this covers the provider's side. The SDK honours
# ``Retry-After`` when present; otherwise backoff runs 1 s → 30 s for at most
# five minutes per call before the error propagates.
_RETRIES = RetryConfig(
    "backoff",
    BackoffStrategy(
        initial_interval=1_000, max_interval=30_000, exponent=1.5, max_elapsed_time=300_000
    ),
    retry_connection_errors=True,
    status_codes_override=["429", "5XX"],
)


class OpenRouterEmbeddings(Embeddings):
    def __init__(self) -> None:
        self._client = OpenRouter(
            api_key=settings.openrouter_api_key.get_secret_value(), retry_config=_RETRIES
        )
        self._model = settings.openrouter_embedding_model
        # Same routing constraints as the chat model: chunk text is the
        # document itself, so it must not reach a host that retains inputs.
        # Validated up front so a typo in the setting fails at startup, not on
        # the first upload.
        self._provider = (
            ProviderPreferences.model_validate(settings.openrouter_provider)
            if settings.openrouter_provider
            else UNSET
        )
        self._rate_limiter = RateLimiter()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._rate_limiter.wait()
        response = self._client.embeddings.generate(
            input=texts, model=self._model, provider=self._provider
        )
        if isinstance(response, str):
            msg = "Unexpected streaming response from embeddings endpoint"
            raise TypeError(msg)

        embeddings: list[list[float]] = []
        for d in response.data:
            if isinstance(d.embedding, str):
                msg = "Unexpected base64-encoded embedding"
                raise TypeError(msg)
            embeddings.append(d.embedding)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def get_embeddings() -> OpenRouterEmbeddings:
    return OpenRouterEmbeddings()
