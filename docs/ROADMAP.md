# AgentOS Roadmap

This roadmap describes an engineering path toward increasingly general agent capabilities. Milestones indicate software scope, not a claim that AGI has been achieved.

## Phase 0 — Repository and safety foundation
- [x] Establish canonical AgentOS repository.
- [x] Define modular architecture and autonomy boundaries.
- [x] Add Python package metadata and CLI.
- [x] Implement deny-by-default tool policy.
- [x] Implement approval gate for sensitive tools.
- [x] Add an auditable tool execution primitive.
- [ ] Run CI and establish supported Python/platform matrix.

## Phase 1 — Reliable core runtime
- [x] Typed task and dependency-aware plan schemas.
- [x] Typed step execution result and task lifecycle contracts.
- [ ] Structured configuration with environment-specific profiles.
- [ ] Persistent audit log with rotation and integrity checks.
- [ ] Cancellation, timeout, retry, and resource-budget primitives.
- [ ] Structured logging, metrics, and tracing.
- [ ] Unit, integration, and property-based test suites.

## Phase 2 — Memory and retrieval
- [ ] Working-memory store with TTL and token/size budgets.
- [x] SQLite episodic memory with provenance, confidence, timestamps, metadata, and expiry.
- [ ] Semantic document store and hybrid retrieval.
- [ ] Confidence, source attribution, and contradiction handling.
- [x] Basic memory inspection, search, and deletion API.\n- [ ] Memory export and correction APIs.

## Phase 3 — Planning and tool use
- [x] Dependency-aware task graph validation and deterministic topological ordering.
- [ ] Model-assisted goal decomposition and bounded replanning.
- [ ] Tool registry with schemas, scopes, and risk levels.
- [ ] Sandboxed adapters for filesystem and read-only web operations.
- [ ] Human approval workflow for writes, external communication, and spend.
- [ ] Deterministic replay of tool traces.

## Phase 4 — Evaluation and controlled learning
- [ ] Task success metrics and evaluator interfaces.
- [ ] Regression benchmark harness.
- [ ] Feedback capture and failure taxonomy.
- [ ] Versioned skill proposals and offline validation.
- [ ] Rollback and model/prompt/config experiment tracking.

## Phase 5 — Multi-agent orchestration
- [ ] Role-based agents and typed message contracts.
- [ ] Supervisor, worker, critic, and verifier patterns.
- [ ] Shared task state with isolation boundaries.
- [ ] Delegation budgets, loop detection, and dead-letter handling.
- [ ] Cross-agent provenance and conflict resolution.

## Phase 6 — Adaptive, partially autonomous operation
- [ ] Scheduled workflows with explicit scopes.
- [ ] Policy-bounded background execution.
- [ ] Drift detection and health checks.
- [ ] Approval queues and operator dashboard.
- [ ] Capability graduation based on measured reliability.

## Phase 7 — Research track
- [ ] Long-horizon planning research.
- [ ] Continual learning and knowledge consolidation experiments.
- [ ] Multimodal perception adapters.
- [ ] World-model and simulation experiments.
- [ ] Generalization benchmarks and independent evaluation.

## Release gates

A phase is not complete merely because code exists. It requires tests, documentation, threat review, failure handling, and reproducible evidence. Autonomy is expanded only when the relevant capability passes its release gate.
