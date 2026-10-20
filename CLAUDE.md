# Xraylarch-web agent guide

Read `AGENTS.md` for API operation, scientific conventions, and project-specific
working rules. For code changes, also read `README.md` and `CONTEXT.md`.

## Local checkout policy

This checkout does not require `memoryctl` for reading, editing, testing, or
completing project work. This local policy overrides the shared-memory bootstrap
and transaction requirements in `AGENTS.md`. Proceed using the repository's
instructions, documentation, and current source without asking for a memoryctl
exception on each task.

Keep this `CLAUDE.md` customization local: do not stage, commit, or push it.
Do not create a substitute `memoryctl` or directly edit canonical shared-memory
files. Install or enable the shared-memory bridge only when the user requests it.

The optional bridge's project ID is `xraylarch-web`; its canonical memory directory
is `~/.local/share/claude-project-memory/xraylarch-web/memory/`, and its operator
guide is `~/claude-tools/docs/shared-memory-bridge.md`. These paths refer to a
separately installed bridge and are not prerequisites for this checkout.

This project has no daily, weekly, or monthly report policy.
Shared project skills live in `.claude/skills`; `.agents/skills` links there.
