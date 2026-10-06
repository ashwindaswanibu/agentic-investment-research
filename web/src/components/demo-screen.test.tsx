import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DemoScreen } from "./demo-screen";
import { parseDemo } from "@/lib/demo";
import { capsFixture } from "@/test/fixtures";

const access = vi.hoisted(() => ({ readOnly: true }));
vi.mock("./app-shell", () => ({
  useEnvironment: () => ({
    capabilities: { ...capsFixture, read_only: access.readOnly },
    capabilityError: null,
  }),
}));
const sample = {
  schema_version: 1,
  synthetic: true,
  built_at: "2026-10-05T20:00:00Z",
  walkthroughs: [
    {
      id: "instruments",
      title: "Comparison",
      description: "Invented prices demonstrate real payoff calculations.",
      href: "/cases/11111111-1111-1111-1111-111111111111?tab=research",
    },
    {
      id: "forecasts",
      title: "Forecasts",
      description: "Invented reports demonstrate source-backed corrections.",
      href: "/cases/22222222-2222-2222-2222-222222222222?tab=forecasts",
    },
  ],
};
beforeEach(() => {
  access.readOnly = true;
});
afterEach(() => vi.unstubAllGlobals());

describe("public demonstration", () => {
  it("shows real package links and discloses fixture scope without suggesting a live agent run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(sample))),
    );
    render(<DemoScreen />);
    expect(
      await screen.findByRole("link", { name: "Inspect the comparison" }),
    ).toHaveAttribute("href", sample.walkthroughs[0].href);
    expect(
      screen.getByRole("link", { name: "Follow the forecast" }),
    ).toHaveAttribute("href", sample.walkthroughs[1].href);
    expect(screen.getByText(/No model is running here/)).toBeInTheDocument();
    expect(screen.getByText(/synthetic inputs/)).toBeInTheDocument();
  });
  it("does not manufacture sample links when this is an ordinary server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 404 })),
    );
    render(<DemoScreen />);
    await screen.findByText(/no verified demo package/);
    expect(
      screen.queryByRole("link", { name: "Inspect the comparison" }),
    ).toBeNull();
  });
  it("will not present a writable workspace as the public demo", async () => {
    access.readOnly = false;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(sample))),
    );
    render(<DemoScreen />);
    await screen.findByText(/operator workspace/);
    expect(
      screen.queryByRole("link", { name: "Follow the forecast" }),
    ).toBeNull();
  });
  it.each([
    "https://evil.invalid/",
    "//evil.invalid",
    "/cases/../session",
    "javascript:alert(1)",
  ])("rejects an unexpected manifest link %s", (href) => {
    expect(() =>
      parseDemo({
        ...sample,
        walkthroughs: [
          { ...sample.walkthroughs[0], href },
          sample.walkthroughs[1],
        ],
      }),
    ).toThrow();
  });
  it("rejects a manifest that drops the synthetic marker or duplicates a walkthrough", () => {
    expect(() => parseDemo({ ...sample, synthetic: false })).toThrow();
    expect(() =>
      parseDemo({
        ...sample,
        walkthroughs: [sample.walkthroughs[0], sample.walkthroughs[0]],
      }),
    ).toThrow();
  });
});
