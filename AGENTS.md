# AGENTS.md

This file defines the rules that future AI Agents / Codex / Hermes must follow when working on this project.

This file only contains long-term working rules. It must not contain detailed development progress, phase-specific tasks, vendor implementation details, or long command lists.
Current progress, task order, unfinished items, and phase records must be maintained in `PLAN.md`.

## 1. Core Principles

* Before making any change, the Agent must read:

  * `AGENTS.md`
  * `PLAN.md`
  * `README.md`
* `PLAN.md` is the main source for the current execution plan, progress status, and next tasks.
* `README.md` is the user-facing project status summary.
* Actual completion status must be verified through code, tests, migrations, frontend entry points, and runtime behavior.
* The Agent must not assume that a feature is complete based only on documentation.
* If documentation, plan, and code conflict with each other, the Agent must report the conflict first and must not assume that one side is correct.
* The Agent must not mark a partially completed task as completed just to make progress look better.

## 2. Interrupted-Work Recovery Rules

This project has gone through multiple interrupted development sessions. Before continuing development, the Agent must perform a minimal state check:

* Check the current worktree state.
* Compare the current task against `PLAN.md`.
* Inspect the source code, tests, migrations, frontend entry points, and documentation related to the current task.
* During startup checks, broad searches, and whole-project file enumeration, default to excluding `.git`, `.venv`, `node_modules`, `.uv-cache`, `.pytest_cache`, `.ruff_cache`, `data`, `__pycache__`, and lock files.
* Prefer `rg --files` and `rg` with explicit exclusions for broad inspection. Avoid unbounded recursive enumeration, whole-repository file dumps, and large unfiltered command output.
* These exclusions do not forbid targeted inspection of an excluded path when the current task specifically requires it, such as checking Git metadata, lock files, dependency caches, or runtime data.
* Classify relevant items into the following states:

  * Completed
  * Partially completed
  * Claimed as completed in documentation but lacking code evidence
  * Implemented in code but not synchronized in documentation
  * Not completed
  * Requires user confirmation

Before completing this state check, the Agent must not perform large-scale refactoring, file cleanup, or plan-status updates.

## 3. Plan Synchronization Rules

* `PLAN.md` is the single source of truth for project progress and next tasks.
* After completing any task that affects project progress, the Agent must check whether `PLAN.md` needs to be updated.
* If the task corresponds to an existing checklist item, phase goal, or TODO item in `PLAN.md`, its status must be updated in the same work session.
* The Agent must not complete code changes while forgetting to synchronize the plan.
* The Agent must not update `PLAN.md` without supporting evidence from code, tests, documentation, or runtime behavior.
* If a feature has already been completed but is not recorded in `PLAN.md`, the Agent should add it as completed and describe the evidence.
* If a feature is only partially completed, it must not be marked as completed. It should be marked as partially completed or kept as unfinished.
* If the current task does not require a `PLAN.md` update, the final response must explain why no plan update was needed.
* Before sending the final response, the Agent must perform a plan synchronization check:

  * Did this session complete a planned task?
  * Does `PLAN.md` need a checked item, a new item, or a status update?
  * Were there code changes without a matching plan update?
  * Are there checked plan items that lack enough evidence?
* The Agent must not claim that a task is complete before finishing the plan synchronization check.

## 4. Worktree Safety

Without explicit user approval, the Agent must not run or perform:

* `git reset`
* `git clean`
* `git restore`
* Forced file overwrites
* Deletion of unknown files or directories
* commit
* push
* pull
* rebase
* merge
* branch switching

The Agent must protect existing user changes.
If there are many uncommitted or untracked files, the Agent should explain the risk before continuing.

## 5. Security and Credentials

* The Agent must not read, print, copy, summarize, or commit real secrets from `.env`.
* The Agent must not commit databases, logs, uploaded files, generated media, caches, virtual environments, or runtime artifacts.
* Before any commit or push, the Agent must run a secret scan.
* If a secret may have entered Git history, the Agent must stop immediately and report it. The Agent must not rewrite history without user approval.
* Any operation involving real paid APIs, real upstream generation, credentials, data deletion, database migrations, or irreversible changes requires explicit user confirmation first.

## 6. Development Rules

* Behavior changes should be covered by new or updated tests whenever practical.
* After making changes, the Agent must run validation that matches the scope of the change.
* The Agent must not weaken real business constraints just to make tests pass.
* The Agent must not introduce large new frameworks, architecture rewrites, or unplanned technical directions without approval.
* The Agent must not expand the project scope without approval.
* Temporary validation code, debugging scripts, and one-off experiments must not be mixed into the formal implementation.
* Before finishing a session, remove temporary validation scripts, one-off probes, temporary test output, temporary reports, and temporary directories created during that session after their useful results have been read.
* Safe cleanup may include `__pycache__`, `.pytest_cache`, `.ruff_cache`, and temporary directories created in the current session when they are confirmed to be reproducible.
* Do not automatically delete formal regression tests, especially files under `tests/` that cover product behavior, bug fixes, or future regressions.
* If a file under `tests/` is only a temporary experiment, it must be clearly identifiable from its name, location, or the current session record before removal.
* Do not clean `.env`, databases, logs, uploads, generated media, migration reports, user data, lock files, dependency caches, or files whose ownership or purpose is uncertain.

## 7. Project Boundaries

* This project targets a Windows local single-user scenario.
* Web services should bind to a local loopback address.
* The frontend should continue using plain HTML / CSS / JavaScript.
* The backend should continue using the existing Python / FastAPI / SQLite / Worker architecture.
* The Agent must not add unplanned goals such as remote access, multi-user support, cross-platform adaptation, GitHub Actions, audio generation, or true video models.
* Specific feature boundaries, vendor restrictions, unfinished items, and phase tasks are defined in `PLAN.md`.
* Vendor integration details, model-calling rules, cost rules, and retry strategies must not be written in this file. They should be maintained in `PLAN.md` or `docs/`.

## 8. Documentation Rules

* User-facing documentation and UI text should be written in Chinese.
* Behavior changes must update related documentation when needed, unless the user explicitly asks not to update documentation.
* `README.md` should remain the project status summary.
* `PLAN.md` should remain the execution plan, progress record, and next-step reference.
* Detailed development commands, architecture explanations, and vendor integration details must not be written in this file. They should be maintained in `docs/` or `PLAN.md`.
* If documentation is outdated but the code behavior is correct, the Agent should update the documentation.
* If code behavior conflicts with the planned target, the Agent must report it and wait for user confirmation before changing the target.

## 9. Final Response Rules

After completing development, fixes, audits, or documentation updates, the final response must include:

* What was actually completed in this session.
* Which key files were changed.
* Which validations were run.
* Whether `PLAN.md` was synchronized.
* Whether any conflicts were found between documentation, plan, and code.
* Whether there are remaining items that are unfinished or require user confirmation.

The Agent must not reply only with “done” or “fixed”.

## 10. Completion Standard

A task can be marked as completed only when all applicable conditions are met:

* The related implementation exists.
* Key behavior has been tested or locally validated.
* Related documentation has been synchronized when needed.
* `PLAN.md` has been checked and updated when needed.
* No secrets, databases, logs, generated files, or runtime artifacts are included in the commit scope.
* The final response explains what was completed, how it was validated, and whether `PLAN.md` was synchronized.

If `PLAN.md` has not been synchronized, or if the Agent cannot confirm whether synchronization is needed, the Agent must not claim that the task is complete.
