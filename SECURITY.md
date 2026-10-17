# Security Policy

## Scope

AgentOS is an early-stage agent runtime. Do not assume it is safe for production, multi-tenant, or unattended operation.

## Baseline controls

- Tool access is deny-by-default.
- External side effects must use explicit capabilities and approval gates.
- Secrets must be supplied through a secret manager or local environment and must never be committed.
- Untrusted documents, prompts, tool outputs, and retrieved content must be treated as data, not executable instructions.
- Model-generated code must not be executed in the trusted process without isolation and review.

## Reporting

For vulnerabilities in this private project, report them privately to the repository owner. Include reproduction steps, impact, affected commit, and a suggested mitigation. Do not publish exploit details before a fix is available.

## Known limitations

The current approval flag is a prototype API-level gate, not a cryptographically authenticated approval system. The audit log is in-memory and is not tamper-evident. Do not use this foundation to authorize high-impact operations until those controls are replaced and independently tested.
