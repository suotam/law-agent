from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gates the OpenAPI docs (see api/app.py): only "development" serves them,
    # so a deployment must opt in to localhost's default rather than opt out
    # of a production one.
    environment: Literal["development", "production"] = "development"

    openrouter_api_key: SecretStr
    openrouter_model: str
    openrouter_embedding_model: str

    # OpenRouter routing preferences, sent verbatim as the ``provider`` field of
    # every chat and embedding request (see
    # https://openrouter.ai/docs/features/provider-routing). The default keeps
    # user documents and questions off any host that would keep or train on
    # them: ``zdr`` limits routing to zero-data-retention endpoints and
    # ``data_collection: deny`` excludes providers whose policy allows storing
    # inputs. Narrow it further with ``only``/``ignore`` (provider names) when
    # the firm requires specific jurisdictions, e.g.
    # ``OPENROUTER_PROVIDER={"zdr": true, "only": ["Nebius"]}``. Set to ``{}``
    # to let OpenRouter route freely.
    openrouter_provider: dict[str, Any] = {"zdr": True, "data_collection": "deny"}

    qdrant_url: str
    qdrant_collection: str

    # Defaulted, unlike the settings above: a local docker compose stack always
    # exposes these here, so they need no entry in .env.
    docling_url: str = "http://localhost:5001"
    database_url: str = "postgresql+psycopg://law_agent:law_agent@localhost:5432/law_agent"

    # Original uploads, content-addressed. Moves outside the repo tree only once
    # the application itself runs in a container with a volume mounted here.
    blob_root: Path = Path("data/blobs")

    # Signs the API's own access tokens. A real deployment sets it to a long
    # random string; there is no default, because a defaulted signing key is a
    # forged token waiting to happen.
    jwt_secret: SecretStr
    jwt_expiry_days: int = 7

    # The FE is a separate deployment, so the browser needs these origins
    # allowed explicitly.
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()  # type: ignore[call-arg]
