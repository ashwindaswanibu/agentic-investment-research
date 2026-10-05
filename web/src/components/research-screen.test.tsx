import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchScreen } from "./research-screen";
import { capsFixture, caseFixture } from "@/test/fixtures";

const controls = vi.hoisted(() => ({ canWrite: true, push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: controls.push }),
}));
vi.mock("./app-shell", () => ({
  useEnvironment: () => ({
    capabilities: capsFixture,
    workspaces: [
      {
        id: "general",
        name: "General research",
        description: "Test workspace",
      },
    ],
    canWrite: controls.canWrite,
    capabilityError: null,
  }),
}));
beforeEach(() => {
  controls.canWrite = true;
  controls.push.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("investigation launch flow", () => {
  it("disables creation in read-only mode without substituting demonstration cases", async () => {
    controls.canWrite = false;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }))),
    );
    render(<ResearchScreen />);
    await screen.findByText("Start with a question worth testing");
    expect(
      screen.getByRole("button", { name: "New investigation" }),
    ).toBeDisabled();
    expect(screen.queryByText(caseFixture.title)).toBeNull();
  });
  it("prevents duplicate creates while a request is pending and navigates to the persisted case", async () => {
    let resolveCreate: ((value: Response) => void) | undefined;
    const fetcher = vi.fn((_url: string, options?: RequestInit) =>
      options?.method === "POST"
        ? new Promise<Response>((resolve) => {
            resolveCreate = resolve;
          })
        : Promise.resolve(new Response(JSON.stringify({ items: [] }))),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<ResearchScreen />);
    await screen.findByText("Start with a question worth testing");
    fireEvent.click(screen.getByRole("button", { name: "New investigation" }));
    fireEvent.change(screen.getByLabelText("Investigation title"), {
      target: { value: "Test fixture: hypothesis" },
    });
    fireEvent.change(screen.getByLabelText("Hypothesis & research question"), {
      target: { value: caseFixture.hypothesis },
    });
    const form = screen
      .getByRole("button", { name: "Create investigation" })
      .closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    const posts = fetcher.mock.calls.filter(
      ([, options]) => options?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(
      (posts[0][1]?.headers as Record<string, string>)["Idempotency-Key"],
    ).toBeTruthy();
    resolveCreate!(new Response(JSON.stringify(caseFixture), { status: 201 }));
    await waitFor(() =>
      expect(controls.push).toHaveBeenCalledWith("/cases/test-case"),
    );
  });
});
