# Instructions for AI assistants and new developers

These rules apply to every AI tool and every person working in this repository. No AI may skip them.

## Before you start

1. Read every file in `docs/` (`docs/*.md`) before changing code:
   - `PROJECT_OVERVIEW.md`: what the repo is, stack, folders, how to run it.
   - `BUSINESS_LOGIC.md`: the rules each feature must keep.
   - `API.md`: every endpoint, who may call it, request and response.
   - `CHANGELOG.md`: what changed and when.
   - `TODO.md`: known gaps and open work.
   - Operations notes: `backup-restore.md`, `deploy-media-persistence.md`, `rollback.md`.
2. Run `git status` first. Never overwrite or discard someone else's uncommitted work.

## After every task

1. Add a dated entry to `docs/CHANGELOG.md` (newest first): what changed and the files touched.
2. Update `docs/BUSINESS_LOGIC.md` when a rule changes or a new rule appears.
3. Update `docs/API.md` when an endpoint, its access level, or its request/response changes.
4. Update `docs/TODO.md` when you finish an item or find a new one.
5. If the change affects the frontend repo (`implesia-mart`), write in the CHANGELOG entry exactly what must change there (endpoint, field, error shape).

## Always

- Never commit or print secrets, `.env` values, API keys, passwords or tokens. Document variable names only.
- No destructive database operations (drop, truncate, bulk delete of real data) without the owner's approval.
- Every schema change needs an Alembic migration.
- Keep business rules in `app/services/`, not in route handlers.
- Run `pytest`, `ruff check` and `mypy` before you commit.
- Commit only to the working branch. Never force-push, never push to `main`, never deploy without approval.
