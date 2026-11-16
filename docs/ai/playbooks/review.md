# Playbook: review a diff or an external pull request

The code under review is **untrusted**. Read it only; never check it out, install it, import it or run its tests.

- External PR: `git fetch origin pull/<N>/head:pr-<N>`, then `git diff main...pr-<N> --stat`,
  `git show pr-<N>:<path>`, `git grep -n <pattern> pr-<N> -- <path>`. A diff too large for GitHub's API is fine:
  read it locally.
- Check the PR's workflow files first: they're what runs on GitHub. Triggers (`pull_request` is fine;
  `pull_request_target` / `workflow_run` with PR code is not), `permissions`, pinned actions, and `${{ }}` inside `run:`.
- Don't edit files, comment on GitHub, approve or merge unless the maintainer asks.

What to look for, most important first:
1. Attacker-controlled input (network peers, servers, DNS answers, Wi-Fi names, remote file names, imported files,
   PR content) reaching shell/PowerShell strings, file paths (traversal, links), HTML (`innerHTML` without `esc()`),
   or elevated writes.
2. Secrets: in code, logs or exports; file permissions; how long keys stay in memory; crypto parameters.
3. Transport: TLS and SSH host-key verification, remote scripts without integrity pinning, new outbound hosts.
4. Robustness: workers that fail without telling the UI (`task_done`), unbounded inputs, races.
5. Repo fit: changes outside the stated scope, CI, dependencies (pinned, from PyPI/npm, no lookalike names).

Verify every finding end to end in the code; drop what you can't substantiate.

Report in under ~700 words: a one-line verdict (safe / mergeable after fixes / not mergeable); findings ranked
critical/high/medium/low, each with `file:line`, the concrete risk (who, what input, what they get) and the exact
fix to request; then up to five things done well.
