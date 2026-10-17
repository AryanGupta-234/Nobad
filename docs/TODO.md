# AgentOS Engineering TODO

Last reviewed: 2026-10-17

This file is the short operational queue. The [roadmap](ROADMAP.md) is the complete milestone map.

## Current sprint — Core runtime hardening
- [ ] Install package in a clean Python 3.11+ environment and run tests.
- [ ] Add CI workflow for Windows and Ubuntu.
- [ ] Add typed request/result contracts.
- [ ] Add JSON configuration and validation.
- [ ] Replace in-memory audit list with a persistence interface.
- [ ] Add execution timeout and cancellation.
- [ ] Add structured error types and redaction rules.

## Backlog
- [ ] Memory interfaces and local SQLite implementation.
- [ ] Tool schemas, scopes, and risk classification.
- [ ] Planner and bounded task graph executor.
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
