# CLAUDE.md

Guidance for AI agents working in this repository.

## Layout

This is a monorepo split into `backend/` (Python service) and `frontend/`
(React/Vite web UI) — see `docs/ARCHITECTURE.md`. Stay within the side you're
working on; don't read or edit files in the other one unless the task
actually requires it.

## Required reading

Read `docs/ARCHITECTURE.md` before working on the codebase — it is the
single source of truth for the system's principles, namespaces, module map,
flow, roadmap status and open decisions. Use it to orient yourself instead of
re-deriving the design from the source.

## Keeping the architecture doc accurate

`docs/ARCHITECTURE.md` must reflect the current state of the code. When a
change you make alters any of the following, update the doc in the same change:

- namespaces or their status
- the module map (new/renamed/removed modules)
- the stack or principles (models, orchestration, retrieval, storage)
- the flow or citation model
- roadmap status or open decisions

## Conventions

- Code, identifiers, comments, log messages and docs are in English.
- Specs and plans under `docs/superpowers/` are always written in English,
  regardless of the language used in the conversation.
- Follow clean code: small single-purpose functions, no duplication.
- Comments explain _why_, not _what_.
- Never commit on `main` or push to GitHub unless the user explicitly asks
  for it; routine work goes to a separate branch.
