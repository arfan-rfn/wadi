// Runtime proxy to the orchestrator (§13: config via env at RUNTIME).
//
// A next.config `rewrites()` destination is resolved at BUILD time and baked
// into the routes manifest — the container's WADI_API_URL would be ignored.
// This catch-all route handler reads the env var per request instead, so the
// same image works against any deployment.

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function apiBase(): string {
  return process.env.WADI_API_URL ?? "http://127.0.0.1:9234";
}

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const target = `${apiBase()}/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  const auth = request.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.blob(),
      cache: "no-store",
    });
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: `orchestrator unreachable at ${apiBase()} — is the stack up?` },
      { status: 502 },
    );
  }
}

export { proxy as GET, proxy as POST, proxy as DELETE, proxy as PUT, proxy as PATCH };
