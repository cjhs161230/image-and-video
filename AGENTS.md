# Agent Instructions

## Source of truth

- Read `PLAN.md` before making changes.
- Execute only when its status is `Active`.
- Mark existing checklist items complete immediately after verification.
- Do not alter plan scope, priorities, validation, risks, or next actions without explicit user approval.

## Repository rules

- Application code belongs under `src/image_video/`.
- Browser assets belong under `frontend/`.
- Tests mirror responsibilities under `tests/unit`, `tests/integration`, and `tests/e2e`.
- Operational scripts belong under `scripts/`.
- Runtime databases, logs, uploads, generated media, PIDs, and imported legacy data belong under `data/` and must remain untracked.
- Keep the repository root limited to project metadata, entry documentation, and startup files.

## Development workflow

- Use test-driven development for behavior changes: failing test, minimal implementation, passing test, refactor.
- Run focused tests after each change and the full relevant suite before marking a plan step complete.
- Use `uv run ruff check .`, `uv run pyright`, and `uv run pytest`.
- Use `npm run lint` and `npm run format:check` for frontend code.
- Preserve unrelated user changes.

## Security

- Never copy credentials from the legacy project.
- Secrets are loaded only from `.env`; settings APIs must reject secret fields.
- Never log authorization headers, API keys, App Secrets, full upstream payloads containing secrets, or sensitive local paths.
- Run `python scripts/security/scan_secrets.py .` before every commit and push.
- Do not push until the user confirms legacy credentials have been rotated.

## Platform and product constraints

- Windows only; bind Web services to `127.0.0.1`.
- The Web process and Worker are separate local processes sharing SQLite.
- Do not add commercial Matsca mode, audio generation, true video models, remote access, multi-user support, or legacy API compatibility.
- User-facing documentation and UI are Chinese. Agent-facing instruction files may be English.

