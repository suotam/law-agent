# Law Agent

Agentic RAG system for a law firm. It ingests legal documents (Czech laws,
internal org files, user-uploaded files), chunks and indexes them into
Qdrant with hybrid (dense + sparse) vectors, and answers queries via
retrieval-augmented generation over an OpenRouter-hosted LLM. A React web
UI lives in `frontend/`; the FastAPI backend in `backend/`.

## Layout

- `backend/` — FastAPI app, ingestion scripts, Alembic migrations (Python 3.13, uv)
- `frontend/` — React (Vite) web UI, served by nginx in production
- `docs/` — architecture guide (`ARCHITECTURE.md`) and design docs
- `docker-compose.yml` — development services (Qdrant, Postgres, pgweb, docling)
- `docker-compose.prod.yml` — production stack (adds `api` and `frontend`)
- `deploy/` — VM provisioning guide and script

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node 22 (frontend)
- Docker

## Setup

```bash
# development
cd backend
uv sync
cp .env.example .env

cd ..
cd frontend
cp .env.example .env
npm ci

# production
cd ..
cp backend/.env.example .env.prod

```

## Model and data privacy

The LLM and the embedding model are both reached through OpenRouter, so pick
them in `.env`:

- `OPENROUTER_MODEL` — an open-weight model that supports tool calling, e.g.
  `qwen/qwen3-235b-a22b-2507` (default choice, strong Czech) or
  `openai/gpt-oss-120b` (cheaper, faster).
- `OPENROUTER_EMBEDDING_MODEL` — must produce 1024-dimensional vectors to match
  the Qdrant collection (`baai/bge-m3`).
- `OPENROUTER_PROVIDER` — routing constraints sent with every request. The
  default `{"zdr": true, "data_collection": "deny"}` restricts routing to
  zero-data-retention endpoints of providers that do not store or train on
  inputs. To pin specific hosts (e.g. EU only), add `"only": ["Nebius"]`; see
  <https://openrouter.ai/docs/features/provider-routing>. Note that even an
  open-weight model is still executed by a third-party host — only
  self-hosting keeps the data entirely in-house.

## Running

Start the local services

```bash
docker compose up -d
```

- Qdrant dashboard: <http://localhost:6333/dashboard>
- pgweb: <http://localhost:8081> — browses the Postgres with simple UI with no auth
- docling-serve UI: <http://localhost:5001/ui>

## Running the API

All backend commands assume the `backend/` directory as the working directory
(the `.env` file and the `data/` runtime directory live next to `pyproject.toml`).

```bash
cd backend
uv run uvicorn law_agent.api.app:app --reload
```

- OpenAPI docs: <http://localhost:8000/docs>

Generate `JWT_SECRET`

```bash
openssl rand -hex 64
```

## Running the frontend

```bash
cd frontend
npm run dev
```

Vite serves the UI on its dev port; it talks to the backend API directly (`VITE_BACKEND_API_URL`).

## Creating a user

Accounts are normally provisioned through `POST /admin/users`, which requires
an existing admin's token. To create the first admin (or add one when the API
is unreachable), use the script instead:

```bash
uv run scripts/create_user.py admin@firma.cz --role admin
```

It prompts for the password (hidden input) if `--password` is not given, so
it never lands in shell history. In production, run it inside the `api`
container the same way as `ingest_law_url.py` below:

```bash
docker compose -f docker-compose.prod.yml exec api uv run scripts/create_user.py admin@firma.cz --role admin
```

## Ingesting laws

Laws follow a separate path: fetch a law straight from the ceskezakony.cz API
by URL, chunk it by structure (§ and paragraphs) and index it into the `laws`
namespace, all in one step. The URL follows the schema
`https://ceskezakony.cz/api/v1/laws/{number}/{year}/fragments`. Requires
`CESKEZAKONY_API_TOKEN` in `backend/.env` (or `backend/.env.prod`).

Development — run directly on the host (from `backend/`):

```bash
uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/106/1999/fragments
```

Production — `qdrant` and the other services sit on an internal Docker
network with no host-published ports, so the script has to run inside the
`api` container instead:

```bash
docker compose -f docker-compose.prod.yml exec api uv run scripts/ingest_law_url.py https://ceskezakony.cz/api/v1/laws/106/1999/fragments
```

Run it once per law you need — a fresh deploy starts with an empty `laws`
namespace, so this is also how you populate it after migrations. Re-running
is safe and cheap, e.g. after a law is amended. Useful flags:

- `--dry-run` — fetch, chunk and validate only, no Qdrant, no embedding API
- `--dump` — write a readable chunk listing to `data/law_chunks/`, for
  eyeballing chunk boundaries before indexing
- `--save-json` — also save the fetched fragments to `data/laws/`

`--help` lists the remaining flags (repealed fragments, chunker token budget,
skipping orphan pruning).

## Production

The production stack is described by `docker-compose.prod.yml` and reads its
secrets from `.env.prod` at the repository root (at minimum
`POSTGRES_PASSWORD`, `JWT_SECRET` and the OpenRouter keys). The frontend
build takes `VITE_BACKEND_API_URL` from `.env` at the repository root —
compose interpolates it into the image build (`deploy/setup-oracle-vm.sh`
writes both files):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The `api` (`8000:8000`) and `frontend` (`80:80`) services publish host ports;
`qdrant`, `postgres` and `docling` stay on the internal network with no host
access. The UI is reachable at `http://<host>` and the API at
`http://<host>:8000` — OpenAPI docs at `/docs` are disabled in production
(only served when `ENVIRONMENT=development`).

The API container does not run database migrations on startup. Apply them
after every deploy that changes the schema — and always on the first deploy,
or the API starts against an empty database:

```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Migrations create the schema but not the Qdrant collection's content — see
"Ingesting laws" above for how to populate an empty `laws` namespace.

## Database migrations

The API does not run migrations on startup. After pulling code that changes
the schema, apply migrations before starting the API:

```bash
cd backend
uv run alembic upgrade head
```

See "Production" above for applying migrations on a deployed environment.

## Tests

```bash
cd backend && uv run pytest   # backend
cd frontend && npm test       # frontend (vitest)
```

## Linting & formatting

```bash
uv run ruff check .      # backend lint
uv run ruff format .     # backend format
cd frontend && npm run lint   # frontend
```

## Type checking

```bash
cd backend && uv run pyright   # backend
cd frontend && npm run typecheck   # frontend
```
