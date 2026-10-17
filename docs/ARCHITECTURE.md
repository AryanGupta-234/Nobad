# AgentOS Architecture

## Target architecture

AgentOS is a supervised, modular agent platform. Components communicate through typed contracts and explicit capability boundaries.

| Layer | Responsibility | Status |
|---|---|---|
| Interface | CLI, API, future desktop interface | CLI foundation |
| Orchestration | Agent lifecycle, delegation, scheduling | Planned |
| Cognition | Task interpretation, planning, reflection | Task/plan schemas and DAG validation |
| Memory | Working context, episodic history, semantic knowledge | SQLite store with provenance and TTL; semantic retrieval planned |
| Skills/tools | Capability-scoped adapters | Minimal runtime |
| Learning | Evaluation, feedback, versioned knowledge updates | Planned |
| Governance | Policy, approvals, audit, budgets | Initial policy/runtime |
| Infrastructure | Config, persistence, telemetry, deployment | Planned |

## Execution lifecycle

1. Receive a task and normalize it into a typed request.
2. Build a bounded plan with explicit preconditions and expected outputs.
3. Validate requested capabilities against policy.
4. Request approval for sensitive or externally consequential actions.
5. Execute through registered adapters only.
6. Record inputs metadata, decisions, outputs metadata, errors, and timing.
7. Evaluate the result and update memory only through controlled write paths.

## Autonomy boundaries

- No arbitrary code execution by default.
- No unrestricted shell, filesystem, browser, network, or cloud credentials.
- Tool allowlisting and approval checks are separate controls.
- Resource budgets, timeouts, and cancellation are required before long-running agents.
- Memory writes must be attributable, reviewable, and deletable.
- Model-generated code must pass tests and review before entering the trusted runtime.
- Self-modification of policies, credentials, safety controls, or deployment configuration is prohibited.

## Memory model

The initial SQLite store supports episodic and task-scoped working records, source attribution, confidence, metadata, expiry, search, and deletion. It is a foundation—not yet a semantic/vector retrieval system.

### Planned extensions

- **Working memory:** bounded task-local state with explicit lifetime.
- **Episodic memory:** append-oriented records of task events and outcomes.
- **Semantic memory:** normalized facts and documents with provenance, confidence, and timestamps.
- **Procedural memory:** versioned skills and workflows, evaluated before activation.

Memory retrieval must preserve provenance and distinguish observed facts from model inferences.

## Learning loop (planned)

Collect -> evaluate -> propose update -> validate -> approve -> version -> deploy -> monitor -> rollback.

Learning must not silently promote low-confidence observations into durable facts. Regression suites and immutable audit records are required.

## Deployment strategy

Start with a single-process local runtime on Python 3.11+, compatible with Windows 11 and Linux. Introduce async workers, a database, and remote services only when measured requirements justify them.
