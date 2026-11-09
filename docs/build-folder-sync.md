# Build folder synchronization

The standalone helpers in `scripts/build-sync/` maintain a canonical workspace without changing the dashboard's host-control APIs or Codex configuration synchronization.

Use `projects/<owner>/<repo>` for owned repositories, `vendor/<owner>/<repo>` for build-only upstream clones, and `worktrees/<owner>/<repo>` for branch variants. Keep machine-specific manifests private. A canonical path may be a relative alias to an existing clean checkout, preserving configured legacy paths.

Run `build_sync.py` without `--apply` to inspect. Apply only clones missing projects, creates exact clean aliases, or fast-forwards a clean default branch. It never resets, commits, pushes, deletes, merges diverged histories, or overwrites ignored local files. Snapshot transfers also default to inspection; checksum-based applied transfers retain replaced versions and private permissions.

The build audit showed why folder names and modification times are insufficient: multiple copies shared origins but held different branches, some copied Git directories had no source files, and moved worktrees had stale administrative pointers. Preserve dirty state and unpublished history before reorganizing. Treat mass deletions in incomplete checkouts as recovery data rather than publishing them to a default branch. GitHub privacy protections should be handled with noreply commit metadata, never by disabling account protections. Keep financial journals, browser history exports, career records, credentials, and host runtime state out of public source repositories.

Future dashboard integration should follow ADR 0006: create an explicit read-only plan, classify safe and blocked changes, recheck source and target before applying, and report outcomes per repository. Keep source contents and raw diffs out of telemetry. A successful source snapshot does not certify that an application builds on both operating systems.

Validation:

```sh
python3 -m unittest discover -s scripts/build-sync -v
```

See the helper README for CLI usage and exclusions.
