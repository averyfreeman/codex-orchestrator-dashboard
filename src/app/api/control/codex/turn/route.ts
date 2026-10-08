import { spawn } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import { NextResponse } from "next/server";
import { findHost } from "@/lib/collector";
import { isLocalDashboardRequest } from "@/lib/control-security";
import { readDashboardProfile } from "@/lib/dashboard-profile";
import { appendEvent } from "@/lib/logging";

function parseBody(value: unknown): { host: string; prompt: string; threadId?: string } | null {
  if (!value || typeof value !== "object") return null;
  const body = value as Record<string, unknown>;
  if (typeof body.host !== "string" || !/^[a-zA-Z0-9-]{1,80}$/.test(body.host)) return null;
  if (typeof body.prompt !== "string" || !body.prompt.trim() || body.prompt.length > 40_000) return null;
  if (body.threadId !== undefined && (typeof body.threadId !== "string" || body.threadId.length > 160)) return null;
  return { host: body.host, prompt: body.prompt, ...(typeof body.threadId === "string" ? { threadId: body.threadId } : {}) };
}

async function audit(host: string, type: string, stats: Record<string, unknown>) {
  try {
    await appendEvent({ source: "codex-control", host, type, stats });
  } catch {
    // A telemetry write failure must not interrupt a Codex turn.
  }
}

/** Start or resume one selected-host Codex turn and stream projected SSE events. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Codex controls are available from the local dashboard only." }, { status: 403 });
  }

  let input: { host: string; prompt: string; threadId?: string } | null;
  try {
    input = parseBody(await request.json());
  } catch {
    input = null;
  }
  if (!input) return NextResponse.json({ error: "A host and prompt are required; prompts are limited to 40,000 characters." }, { status: 400 });

  const host = findHost(input.host);
  if (!host) return NextResponse.json({ error: "The selected host is not in the private fleet inventory." }, { status: 404 });
  const profile = await readDashboardProfile();
  const child = spawn("python3", ["scripts/codex_control.py"], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "ignore"],
  });
  const encoder = new TextEncoder();
  const decoder = new StringDecoder("utf8");
  let buffered = "";
  let sawError = false;
  let sawTerminal = false;
  let closed = false;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: Record<string, unknown>) => {
        if (closed) return;
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };
      const handleLine = (line: string) => {
        if (!line.trim()) return;
        let event: Record<string, unknown>;
        try {
          const parsed: unknown = JSON.parse(line);
          if (!parsed || typeof parsed !== "object") return;
          event = parsed as Record<string, unknown>;
        } catch {
          sawError = true;
          send({ type: "error", message: "The Codex control bridge returned an invalid event." });
          return;
        }
        if (event.type === "started") {
          void audit(host.slug, "codex.turn.started", {
            profile: profile.id,
            threadId: event.threadId,
            turnId: event.turnId,
            transport: event.transport,
            networkAccess: profile.networkAccess,
            model: "gpt-6-luna",
          });
        } else if (event.type === "usage") {
          void audit(host.slug, "codex.usage", {
            profile: profile.id,
            inputTokens: event.inputTokens,
            cachedInputTokens: event.cachedInputTokens,
            outputTokens: event.outputTokens,
            reasoningTokens: event.reasoningTokens,
            totalTokens: event.totalTokens,
          });
        } else if (event.type === "completed") {
          sawTerminal = true;
          void audit(host.slug, "codex.turn.completed", {
            profile: profile.id,
            turnId: event.turnId,
            status: event.status,
            failed: event.failed === true,
          });
        } else if (event.type === "error") {
          sawError = true;
        }
        send(event);
      };

      child.stdout.on("data", (chunk: Buffer) => {
        buffered += decoder.write(chunk);
        let newline = buffered.indexOf("\n");
        while (newline >= 0) {
          handleLine(buffered.slice(0, newline));
          buffered = buffered.slice(newline + 1);
          newline = buffered.indexOf("\n");
        }
      });
      child.stdout.on("end", () => {
        buffered += decoder.end();
        if (buffered.trim()) handleLine(buffered);
      });
      child.on("error", () => {
        sawError = true;
        send({ type: "error", message: "Could not start the Codex control bridge." });
      });
      child.on("close", () => {
        if (closed) return;
        if (!sawError && !sawTerminal) {
          send({ type: "error", message: "The Codex control connection ended before the turn completed." });
        }
        controller.close();
      });
      request.signal.addEventListener("abort", () => child.kill("SIGTERM"), { once: true });
      child.stdin.end(JSON.stringify({
        mode: "turn",
        host,
        prompt: input.prompt,
        threadId: input.threadId,
        networkAccess: profile.networkAccess,
      }) + "\n");
    },
    cancel() {
      closed = true;
      child.kill("SIGTERM");
    },
  });

  return new Response(stream, {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      "Content-Type": "text/event-stream; charset=utf-8",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
