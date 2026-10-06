import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const resources = new Set([
  "health",
  "capabilities",
  "session",
  "workspaces",
  "cases",
  "tasks",
  "artifacts",
  "forecasts",
  "experiments",
  "library",
  "events",
  "paper",
]);

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (
    !path.length ||
    !resources.has(path[0]) ||
    path.some((part) => part === "." || part === ".." || part.includes("/"))
  ) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Unknown API resource." } },
      { status: 404 },
    );
  }
  const base = process.env.RESEARCH_API_URL || "http://127.0.0.1:8010";
  const url = new URL(
    `${base.replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}`,
  );
  url.search = request.nextUrl.search;
  const headers = new Headers({ Accept: "application/json" });
  const origin = request.headers.get("Origin");
  if (request.method !== "GET" && request.method !== "HEAD") {
    const allowedOrigins = new Set([
      "http://127.0.0.1:3000",
      "http://localhost:3000",
      ...(process.env.RESEARCH_ALLOWED_ORIGINS || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    ]);
    if (
      (origin && !allowedOrigins.has(origin)) ||
      request.headers.get("Sec-Fetch-Site") === "cross-site"
    ) {
      return NextResponse.json(
        {
          error: {
            code: "origin_forbidden",
            message:
              "This action must originate from the research application.",
          },
        },
        { status: 403 },
      );
    }
  }
  if (origin) headers.set("Origin", origin);
  const authorization = request.headers.get("Authorization");
  if (authorization) headers.set("Authorization", authorization);
  const cookie = request.headers.get("Cookie");
  if (cookie) headers.set("Cookie", cookie);
  const key = request.headers.get("Idempotency-Key");
  if (key) headers.set("Idempotency-Key", key);
  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const tooLarge = () =>
      NextResponse.json(
        {
          error: {
            code: "request_too_large",
            message: "This request exceeds the 2 MB limit.",
          },
        },
        { status: 413 },
      );
    if (Number(request.headers.get("Content-Length") || 0) > 2_000_000)
      return tooLarge();
    const reader = request.body?.getReader();
    if (reader) {
      const decoder = new TextDecoder();
      let size = 0;
      body = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 2_000_000) {
            await reader.cancel();
            return tooLarge();
          }
          body += decoder.decode(value, { stream: true });
        }
        body += decoder.decode();
      } finally {
        reader.releaseLock();
      }
    }
    headers.set("Content-Type", "application/json");
  }
  try {
    const result = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(25_000),
      redirect: "error",
    });
    const responseHeaders = new Headers({
      "Content-Type": result.headers.get("Content-Type") || "application/json",
      "Cache-Control": "no-store",
    });
    for (const cookie of result.headers.getSetCookie())
      responseHeaders.append("Set-Cookie", cookie);
    return new NextResponse(result.body, {
      status: result.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "upstream_unavailable",
          message:
            "The research service is unavailable. Check the backend connection and try again.",
        },
      },
      { status: 503 },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
