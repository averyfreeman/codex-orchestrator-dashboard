# Telemetry stays bounded and content-free

## Context

The dashboard needs useful capacity, health, activity, and cost signals without duplicating conversations or collecting terminal contents. Polling too often adds remote process overhead and produces little value once native event streams are available.

## Decision

Collect host status, load/memory/disk, process CPU/RSS, versions, aggregate counts, Codex turn state and token-usage totals, Herdr event metadata, and worktree metadata. Use a 30-second host-health poll and event streams for interactive status, with a bounded snapshot after reconnect. Start with 30-day aggregate metadata and 7-day bounded operational logs. Exclude prompts, transcripts, terminal output, secrets, and process environments.

## Consequences

Observation itself makes no model calls. Agent execution remains the token and compute cost center. The collector must cap time and output and be benchmarked on the gateway and slowest host. The dashboard can show usage and activity without retaining conversation content.
