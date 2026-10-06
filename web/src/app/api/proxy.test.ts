// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./[...path]/route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("same-origin backend proxy", () => {
  it("forwards the public demo manifest without caching it", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('{"synthetic":true}'));
    vi.stubGlobal("fetch", fetcher);
    const response = await GET(
      new NextRequest("http://localhost:3000/api/demo"),
      {
        params: Promise.resolve({ path: ["demo"] }),
      },
    );
    expect(response.status).toBe(200);
    expect(String(fetcher.mock.calls[0][0])).toBe(
      "http://127.0.0.1:8010/api/demo",
    );
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
  it("forwards forecast resolutions and preserves backend correction conflicts", async () => {
    const body = { outcome: "no", previous_resolution_id: "prior-resolution" };
    const conflict = {
      error: {
        code: "RESOLUTION_CONFLICT",
        message: "Review the latest resolution.",
      },
    };
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(conflict), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(
      new NextRequest(
        "http://localhost:3000/api/forecasts/forecast-id/resolutions",
        {
          method: "POST",
          headers: {
            Origin: "http://127.0.0.1:3000",
            "Idempotency-Key": "resolution-retry-key",
            Cookie: "session=existing",
          },
          body: JSON.stringify(body),
        },
      ),
      {
        params: Promise.resolve({
          path: ["forecasts", "forecast-id", "resolutions"],
        }),
      },
    );
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual(conflict);
    const [url, options] = fetcher.mock.calls[0];
    expect(String(url)).toBe(
      "http://127.0.0.1:8010/api/forecasts/forecast-id/resolutions",
    );
    expect(JSON.parse(options.body)).toEqual(body);
    expect(options.headers.get("Idempotency-Key")).toBe("resolution-retry-key");
    expect(options.headers.get("Cookie")).toBe("session=existing");
  });
  it("accepts the configured loopback origin even when Next normalizes the request URL to localhost", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    const req = new NextRequest("http://localhost:3000/api/cases", {
      method: "POST",
      headers: { Origin: "http://127.0.0.1:3000" },
      body: "{}",
    });
    expect(
      (await POST(req, { params: Promise.resolve({ path: ["cases"] }) }))
        .status,
    ).toBe(200);
    expect((fetcher.mock.calls[0][1].headers as Headers).get("Origin")).toBe(
      "http://127.0.0.1:3000",
    );
  });
  it("rejects cross-origin mutation before contacting the backend", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const req = new NextRequest("http://localhost:3000/api/cases", {
      method: "POST",
      headers: { Origin: "https://another-site.invalid" },
      body: "{}",
    });
    const res = await POST(req, {
      params: Promise.resolve({ path: ["cases"] }),
    });
    expect(res.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("rejects a declared oversized body without forwarding it", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const req = new NextRequest("http://localhost:3000/api/cases", {
      method: "POST",
      headers: { "Content-Length": "2000001" },
      body: "{}",
    });
    expect(
      (await POST(req, { params: Promise.resolve({ path: ["cases"] }) }))
        .status,
    ).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("bounds bodies even when Content-Length is absent", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const req = new NextRequest("http://localhost:3000/api/cases", {
      method: "POST",
      body: "x".repeat(2_000_001),
    });
    expect(
      (await POST(req, { params: Promise.resolve({ path: ["cases"] }) }))
        .status,
    ).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("forwards session cookies and origin without inventing an operator credential", async () => {
    vi.stubEnv("RESEARCH_API_TOKEN", "must-not-be-injected");
    const fetcher = vi.fn().mockResolvedValue(
      new Response("{}", {
        headers: { "Set-Cookie": "session=test; HttpOnly; SameSite=Strict" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const req = new NextRequest("http://localhost:3000/api/session", {
      method: "POST",
      headers: {
        Origin: "http://localhost:3000",
        Cookie: "session=existing",
        "Idempotency-Key": "test-key",
      },
      body: "{}",
    });
    const response = await POST(req, {
      params: Promise.resolve({ path: ["session"] }),
    });
    const headers = fetcher.mock.calls[0][1].headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("Cookie")).toBe("session=existing");
    expect(headers.get("Origin")).toBe("http://localhost:3000");
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
  });
  it("maps upstream outages to a readable 503 instead of leaking internal details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("secret internal host details")),
    );
    const result = await GET(
      new NextRequest("http://localhost:3000/api/cases"),
      { params: Promise.resolve({ path: ["cases"] }) },
    );
    expect(result.status).toBe(503);
    const body = await result.json();
    expect(body.error.code).toBe("upstream_unavailable");
    expect(body.error.message).not.toContain("secret");
  });
});
