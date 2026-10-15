"""The HTTP application: a thin adapter over the ``law_agent`` library.

Nested inside the package rather than sitting beside ``ui/`` because this is a
single deployment, not a redistributable library -- ``uvicorn law_agent.api.app:app``
then needs no packaging ceremony. No business logic lives here or in any router;
they call the services and translate the result into status codes and JSON.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from law_agent.api.routers import (
    acl,
    attachments,
    auth,
    conversations,
    groups,
    me_org_files,
    org_files,
    roles,
    users,
)
from law_agent.config import settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """A factory rather than a module-level app alone: every test gets a clean
    instance, and one can be built with extra routes for testing the shell."""
    docs_enabled = settings.environment == "development"
    app = FastAPI(
        title="Law agent API",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(Exception, _unhandled_error)

    app.include_router(auth.router)
    app.include_router(auth.me_router)
    app.include_router(users.router)
    app.include_router(users.list_users_router)
    app.include_router(roles.router)
    app.include_router(groups.router)
    app.include_router(groups.user_groups_router)
    app.include_router(acl.router)
    app.include_router(acl.user_acl_router)
    app.include_router(conversations.router)
    app.include_router(attachments.router)
    app.include_router(org_files.router)
    app.include_router(me_org_files.router)
    return app


async def _unhandled_error(request: Request, exception: Exception) -> JSONResponse:
    """Anything the routers did not anticipate. The traceback goes to the log;
    the client gets a sentence, because a stack trace is a map of the server."""
    logger.exception(
        "unhandled error on %s %s", request.method, request.url.path, exc_info=exception
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app = create_app()
