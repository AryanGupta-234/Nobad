# GitHub Copilot

Follow [AGENTS.md](../AGENTS.md) at the repository root: it's the shared instruction file for every AI assistant.
Read [docs/ai/memory.md](../docs/ai/memory.md) for project decisions, and use the playbooks in
[docs/ai/playbooks/](../docs/ai/playbooks/) for releases, UI previews and reviews.

Short version: NOBAD VPN runs as administrator, so untrusted input must never reach shell/PowerShell strings,
`innerHTML` without `esc()`, or elevated writes through links. Tests (`python -m pytest -q`) and lint
(`python -m pyflakes nobadvpn tests`) in `apps/vpn` must pass. Never commit WireGuard configs or keys.
