# Issue tracker: GitHub

Use GitHub Issues for this repository's tickets and specs. Run `gh` from the repo root to use the configured remote, or specify `-R averyfreeman/codex-orchestrator-dashboard` outside the clone.

## Operations

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <n> --json number,title,body,labels,comments`
- List open work: `gh issue list --state open`; add label filters where useful.
- Add or remove labels: `gh issue edit <n> --add-label "..."` / `--remove-label "..."`
- Comment or close: `gh issue comment <n> --body "..."`; `gh issue close <n> --comment "..."`
- Link child issues with GitHub sub-issues where supported. Otherwise, put `Part of #<parent>` in the child issue.
- Track blockers with native issue dependencies. If unavailable, record `Blocked by: #<n>` in the issue.

## Pull requests

External pull requests are not an intake source for triage; use issues to track work.

## Wayfinder

Use a map issue labeled `wayfinder:map` with child issues for tickets. Assign yourself to claim a ticket; when resolving one, comment, close it, and update the map's decision notes.
