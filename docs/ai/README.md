# AI assistant setup

One set of instructions for every assistant, so any tool or session picks up the same rules and memory.

| File | Read by | What it is |
|---|---|---|
| [`AGENTS.md`](../../AGENTS.md) | Codex, Cursor, GitHub Copilot coding agent, Jules, Aider and most others | **The source of truth**: layout, commands, rules |
| [`memory.md`](memory.md) | everyone (AGENTS.md says to read it first) | Decisions and open items the code doesn't show |
| [`playbooks/`](playbooks/) | everyone | Step-by-step: release, UI preview, review |
| [`tools/`](tools/) | everyone | Helpers the playbooks use (the fake UI backend) |
| [`CLAUDE.md`](../../CLAUDE.md) | Claude Code | Imports AGENTS.md and memory.md |
| [`.claude/skills/`](../../.claude/skills/), [`.claude/agents/`](../../.claude/agents/) | Claude Code | Thin shortcuts that run the playbooks |
| [`GEMINI.md`](../../GEMINI.md) | Gemini CLI | Points to AGENTS.md |
| [`.github/copilot-instructions.md`](../../.github/copilot-instructions.md) | GitHub Copilot | Points to AGENTS.md |

Rules for keeping it useful:
- Edit the **source** files (AGENTS.md, memory.md, playbooks); the tool files only point at them.
- Keep AGENTS.md short (it's loaded on every request): link details instead of copying them.
- memory.md is public: decisions only, never secrets or personal data.
