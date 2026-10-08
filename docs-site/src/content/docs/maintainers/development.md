---
title: Develop and validate
description: Run the dashboard and execute its TypeScript, Python, Ansible, and documentation checks.
---

## Local workflow

```sh
npm ci
npm run dev
```

The root npm workspace contains both the Next.js application and the Astro documentation site. Documentation commands are `npm run docs:dev`, `npm run docs:check`, and `npm run docs:build`.

## Validation set

Run the public snapshot check before committing. The complete local acceptance commands are:

```sh
npm test
npm run lint
npx tsc --noEmit
npm run build
npm run docs:check
npm run docs:build
python3 scripts/test_sync_codex_profile.py
python3 -m unittest scripts/test_codex_control.py scripts/test_codex_recovery.py scripts/test_herdr_sessions.py
python3 -m unittest scripts/test_macos_launchagents.py
python3 -m py_compile scripts/probe.py scripts/codex_control.py scripts/codex_recovery.py scripts/herdr_sessions.py scripts/sync_codex_profile.py ansible/inventory.py
python3 scripts/check_public_snapshot.py
cd ansible && ansible-playbook -i inventory.py --syntax-check playbooks/sync-linux-fleet.yml
```

The docs check compiles Astro/Starlight content; the docs build must be produced with the lockfile and emitted to `docs-site/dist`. Validate generated URLs include the configured repository base path and test the docs preview at desktop and narrow widths.

## Source documentation

The supported source languages are TypeScript and Python. Exported route, library, and UI symbols have JSDoc; stable Python helper APIs and CLI entrypoints use PEP 257 docstrings. Keep tests, generated/vendor files, and ordinary private helpers out of that scope. Prefer explaining behavioral constraints, trust boundaries, and data shape over repeating the function name.

For a source change, update the appropriate operator or maintainer guide and its API/script reference in the same change. Never copy private inventory data or machine-specific values into docs fixtures.
