import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, mutate, request } from "./api";

afterEach(() => vi.unstubAllGlobals());
describe("API requests", () => {
  it("retains a supplied idempotency key across retries", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "test" }), { status: 201 }),
      );
    vi.stubGlobal("fetch", fetcher);
    await mutate("/cases", { title: "test" }, (v) => v, "same-request-key");
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("/api/cases");
    expect(options.headers["Idempotency-Key"]).toBe("same-request-key");
    expect(options.headers).not.toHaveProperty("Authorization");
  });
  it("exposes stable backend error codes and readable messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              error: {
                code: "read_only",
                message: "This deployment is read only.",
              },
            }),
            { status: 403 },
          ),
        ),
    );
    await expect(request("/cases", (v) => v)).rejects.toMatchObject({
      code: "read_only",
      status: 403,
      message: "This deployment is read only.",
    });
  });
  it("rejects non-JSON errors without claiming the request succeeded", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("upstream failed", { status: 502 })),
    );
    await expect(request("/cases", (v) => v)).rejects.toBeInstanceOf(ApiError);
  });
  it("passes cancellation to fetch and does not cache responses", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    await request("/cases", (v) => v, { signal: controller.signal });
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      signal: controller.signal,
      cache: "no-store",
    });
  });
});
