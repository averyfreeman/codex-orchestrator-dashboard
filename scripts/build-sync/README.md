# Build folder maintenance

Keep editable projects in `~/build/projects/<owner>/<repo>`, upstream build-only clones in `~/build/vendor/<owner>/<repo>`, and branch variants in `~/build/worktrees/<owner>/<repo>/`. Existing folders can remain behind relative aliases.

Python 3.9+, Git, and rsync 3+ are required. No Python packages are needed.

## Git synchronization

Keep a private JSON manifest listing repository URLs, canonical relative paths, and optional existing candidate paths by machine name. See `manifest.example.json`.

```sh
python3 build_sync.py --manifest /path/to/manifest.json --host machine-name
python3 build_sync.py --manifest /path/to/manifest.json --host machine-name --apply
```

Inspection is the default. Applying creates missing clones or aliases only clean matching checkouts. Existing repositories update only by fast-forward on their default branch. Dirty checkouts, diverged branches, foreign directories, and paths escaping the build root are preserved and reported. Ignored local files cannot be overwritten by a merge. No automatic commit, push, force push, deletion, or reset occurs. Owned project clones fetch all branch tips; vendor clones fetch the default branch. Historical objects can be fetched later from the remote.

The manifest is local configuration: do not publish private project mappings or credentials with this tool. Commit and push work before changing machines; use a separate branch to preserve incompatible work. Initialize project submodules explicitly when needed.

## Private source snapshots

```sh
python3 snapshot_sources.py --destination /private/snapshot/path
python3 snapshot_sources.py --destination /private/snapshot/path --apply
```

A destination may also be an rsync SSH destination; pass `--ssh-command` to select an existing trusted SSH route. Inspection is the default. Applied transfers use checksums, private permissions, and no deletion. Replaced files are retained in `.snapshot-versions/<timestamp>/` at the destination. Authored `public/` assets are included; common generated outputs, Git metadata, credential files, package caches, model downloads, and canonical workspace roots are excluded. Review `EXCLUDES` for project-specific inputs. Snapshots are source preservation, not transactional backups of live application databases.

## Verification

```sh
python3 -m unittest discover -s . -v
```

Tests use isolated local Git remotes and scratch directories. They cover dry-run behavior, cloning, exact aliases, safe fast-forwards, dirty/diverged/foreign checkouts, path escape guards, ignored-file preservation, website assets, and versioned snapshot replacements.
