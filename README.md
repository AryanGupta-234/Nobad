# AgentOS

AgentOS is a modular, local-first agent runtime designed to grow toward increasingly capable, supervised autonomous workflows.

> **Project status:** foundation phase. This repository is the canonical home for the AgentOS architecture, implementation, tests, and roadmap. It is not a claim of artificial general intelligence.

## Design principles

- **Modular cognition:** planning, memory, tools, evaluation, and orchestration remain independently testable.
- **Bounded autonomy:** agents receive explicit capabilities; sensitive actions require approval.
- **Inspectable execution:** plans, tool calls, policy decisions, and outcomes are auditable.
- **Local-first:** core runtime works without a hosted control plane; integrations are optional adapters.
- **Incremental learning:** knowledge and preferences can be updated through versioned, evaluated processes—not silent self-rewriting.
- **Portable engineering:** Python package targeting Windows 11 and Linux.

## Repository map

```text
src/agentos/
  core/       Runtime policy and execution primitives
  memory/     (planned) Working, episodic, and semantic memory
  planning/   (planned) Task decomposition and plan validation
  tools/      (planned) Capability-scoped tool adapters
  learning/   (planned) Evaluation and controlled knowledge updates
  agents/     (planned) Agent roles and orchestration
tests/
docs/
```

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
agentos --help
```

## Safety model

The initial runtime uses deny-by-default tool permissions. A tool must be registered and explicitly allowed by policy. Actions marked as requiring approval are blocked unless an approval decision is supplied. Do not connect unrestricted shell, filesystem, browser, cloud, or credential access to an autonomous agent.

## Development tracking

See [ROADMAP.md](docs/ROADMAP.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), and [TODO.md](docs/TODO.md).

## License

No license has been selected yet. All rights reserved by default until one is added.
