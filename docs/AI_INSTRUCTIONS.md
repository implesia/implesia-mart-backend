# Instructions for AI assistants and new developers

These rules apply to every AI tool and every person working in this repository. No AI may skip them.

## Before you start

1. Read `docs/PLANNING_POINTER.md`. Business, mission, roadmap, 30-day plan, and the working agreement live in the frontend repo (`implesia-mart`) under `docs/planning/`; production release facts live in that repo's `docs/ops/RELEASE_LOG.md`.
2. Then read the other files in `docs/` before changing code:
   - `PROJECT_OVERVIEW.md`: what the repo is, stack, folders, how to run it.
   - `BUSINESS_LOGIC.md`: the rules each feature must keep.
   - `API.md`: every endpoint, who may call it, request and response.
   - `CHANGELOG.md`: what changed and when.
   - `TODO.md`: known gaps and open work. Check the frontend `docs/ops/RELEASE_LOG.md` before treating an older "not live" note as still undeployed.
   - Operations notes: `backup-restore.md`, `deploy-media-persistence.md`, `rollback.md`. `backup-restore.md` still describes an older Render runbook; current Slasha / R2 backup practice is in the frontend release log.
3. Run `git status` first. Never overwrite or discard someone else's uncommitted work.

## After every task

1. Add a dated entry to `docs/CHANGELOG.md` (newest first): what changed and the files touched.
2. Update `docs/BUSINESS_LOGIC.md` when a rule changes or a new rule appears.
3. Update `docs/API.md` when an endpoint, its access level, or its request/response changes.
4. Update `docs/TODO.md` when you finish an item or find a new one.
5. If the change affects the frontend repo (`implesia-mart`), write in the CHANGELOG entry exactly what must change there (endpoint, field, error shape). Planning and release-log updates belong in that frontend repo.

## Always

- Never commit or print secrets, `.env` values, API keys, passwords or tokens. Document variable names only.
- No destructive database operations (drop, truncate, bulk delete of real data) without the owner's approval.
- Every schema change needs an Alembic migration.
- Keep business rules in `app/services/`, not in route handlers.
- Run `pytest`, `ruff check` and `mypy` before you commit.
- Commit only to the working branch. Never force-push, never push to `main`, never deploy without approval.
