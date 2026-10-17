# AgentOS Engineering TODO

Last reviewed: 2026-10-17

This file is the short operational queue. The [roadmap](ROADMAP.md) is the complete milestone map.

## Current sprint — Core runtime hardening
- [ ] Install package in a clean Python 3.11+ environment and run tests.
- [x] Add CI workflow for Windows and Ubuntu (Python 3.11–3.13).
- [x] Add typed task request and dependency-aware plan contracts.
- [x] Add typed step execution result and task lifecycle contracts.
- [ ] Add JSON configuration and validation.
- [ ] Replace in-memory audit list with a persistent audit interface.
- [ ] Add execution timeout and cancellation.
- [ ] Add structured error types and redaction rules.

## Backlog
- [x] Implement SQLite episodic/working memory with provenance, confidence, metadata, and TTL.
- [ ] Tool schemas, scopes, and risk classification.
- [ ] Model-assisted planner and bounded task graph executor.
- [ ] Plan-to-runtime integration with policy checks at every tool boundary.
- [ ] Evaluation harness and benchmark fixtures.
- [ ] Skill versioning and promotion workflow.
- [ ] Multi-agent supervisor/worker/critic orchestration.
- [ ] Operator UI and approval queue.

## Engineering rules
1. Every feature needs tests and documentation.
2. Keep the default policy deny-by-default.
3. Never commit secrets, API keys, tokens, or local environment files.
4. Do not enable unrestricted autonomous shell or cloud operations.
5. Update this file and ROADMAP.md in the same change as meaningful milestone work.
6. Mark work complete only after verification; record unverified work honestly.
