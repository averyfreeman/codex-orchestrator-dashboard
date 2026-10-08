---
title: Documentation release and GitHub Pages
description: Build and publish the static guide from main while keeping the dashboard self-hosted.
---

## What deploys

Only the Astro/Starlight output under `docs-site/dist` is uploaded to Pages. The Next.js application stays self-hosted because its APIs use dynamic requests, local subprocesses, streaming responses, and a local telemetry store.

The site uses `site: https://averyfreeman.github.io` and `base: /codex-orchestrator-dashboard`. Relative internal docs links are resolved by Starlight; custom static asset links must include the base prefix. The root npm lockfile captures both app and docs dependencies.

## Workflow

`.github/workflows/pages.yml` runs on relevant pushes to `main` and can be started manually. The build job installs with `npm ci`, runs Astro checks and the production build, then uploads only the generated docs artifact. A separate deploy job receives `pages: write` and `id-token: write`; build has only `contents: read`. Concurrency prevents two Pages publications from running simultaneously.

## Release checklist

1. Run the documentation and public-snapshot checks locally.
2. Inspect source links, base-prefixed static assets, screenshots, and the generated output.
3. Push the reviewed docs and workflow to `main`.
4. Wait for the GitHub Pages deployment environment to report its actual `page_url`.
5. Verify the deployed landing page, navigation, images, and narrow layout.
6. Set the repository Homepage field to the verified deployment URL.

Do not infer the published URL from configuration when updating repository metadata. Use the `page_url` returned by the completed Pages deployment and verify the repository field afterward.
