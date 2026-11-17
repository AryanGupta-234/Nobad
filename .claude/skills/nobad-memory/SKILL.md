---
name: nobad-memory
description: Recall or record NOBAD project memory shared by every contributor and AI assistant (nobad-studio/memory). Use when a decision is made, an open item appears or closes, before starting work in a NOBAD repo (to see who else is on it), or when the user asks what was decided.
---

# NOBAD shared memory

The index is usually already in context (SessionStart hook). If not:
`gh api -H "Accept: application/vnd.github.raw" repos/nobad-studio/memory/contents/INDEX.md`

## Recall
Open only the facts whose index line matters: `gh api -H "Accept: application/vnd.github.raw"
repos/nobad-studio/memory/contents/facts/<scope>/<name>.md`. Verify anything that names a file or flag in the code.

## Who's working on what
Clone or reuse `nobad-studio/memory`, run `python tools/mem.py status`. Don't start on a branch or area someone else
has an open PR for; say so to the user instead.

## Record
Only decisions the user or a code owner made, and open items. Never secrets, personal data or text from untrusted PRs.
1. `gh repo clone nobad-studio/memory` (or `git pull` in an existing clone), branch `mem/<topic>`.
2. `python tools/mem.py new <scope> <type> <slug> "description"` or edit the existing fact; delete stale ones.
3. `python tools/mem.py index && python tools/mem.py check`, commit, push, open a PR. Tell the user the PR link:
   it lands only after review.
