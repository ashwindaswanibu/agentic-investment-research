// Synthetic API fixtures only; no production research or model calls.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { artifactFixture, capsFixture, caseFixture } from "@/test/fixtures";
import { CaseScreen } from "./case-screen";

const controls = vi.hoisted(() => ({ canWrite: true }));
vi.mock("./app-shell", () => ({
  useEnvironment: () => ({
    capabilities: capsFixture,
    workspaces: [],
    canWrite: controls.canWrite,
  }),
}));
beforeEach(() => {
  controls.canWrite = true;
});
afterEach(() => vi.unstubAllGlobals());
function setup({
  status = "draft",
  sourceStatus = 200,
  sourceKind = "evidence",
} = {}) {
  const data = {
    ...caseFixture,
    status,
    tasks: [],
    tool_calls: [],
    events: [],
    artifacts: [
      {
        ...artifactFixture,
        id: "dossier",
        kind: "clinical_dossier",
        title: "Synthetic dossier",
        content: {
          dossier: {
            claims: [
              {
                id: "c",
                kind: "fact",
                statement: "A synthetic source claim.",
                source_refs: [{ artifact_id: "shared-source" }],
              },
            ],
          },
        },
      },
    ],
  };
  const fetcher = vi.fn((url: string, options?: RequestInit) => {
    const body = url.includes("/events?")
      ? { items: [], cursor: 0 }
      : url.includes("/artifacts/")
        ? sourceStatus === 200
          ? {
              ...artifactFixture,
              id: "shared-source",
              kind: sourceKind,
              title: "Shared synthetic evidence",
              content: { text: "Source text" },
            }
          : { error: { message: "Source is unavailable.", code: "NOT_FOUND" } }
        : options?.method === "POST"
          ? { ...caseFixture, status: "cancelled" }
          : data;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: url.includes("/artifacts/") ? sourceStatus : 200,
      }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<CaseScreen caseId={caseFixture.id} />);
  return fetcher;
}

describe("investigation interactions", () => {
  it("supports keyboard navigation across tabs with one tab stop", async () => {
    setup();
    const overview = await screen.findByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    const evidence = screen.getByRole("tab", { name: /Evidence/ });
    expect(evidence).toHaveFocus();
    expect(evidence).toHaveAttribute("aria-selected", "true");
    expect(overview).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tabpanel")).toHaveAttribute(
      "aria-labelledby",
      evidence.id,
    );
    fireEvent.keyDown(evidence, { key: "End" });
    expect(screen.getByRole("tab", { name: /Activity/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", { name: /Activity/ }), {
      key: "ArrowRight",
    });
    expect(overview).toHaveFocus();
  });

  it("opens persisted evidence from another case in the artifact inspector", async () => {
    const fetcher = setup();
    fireEvent.click(
      await screen.findByRole("button", { name: "Linked source 1" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Shared synthetic evidence",
    });
    expect(within(dialog).getByText("Source text")).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url]) => url === "/api/artifacts/shared-source",
      ),
    ).toBe(true);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close dialog" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([{ sourceStatus: 404 }, { sourceKind: "evaluation_reference" }])(
    "shows inaccessible or non-evidence references as an error, without opening them: %j",
    async (options) => {
      setup(options);
      fireEvent.click(
        await screen.findByRole("button", { name: "Linked source 1" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not open the linked source.",
      );
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Linked source 1" }),
      ).toBeEnabled();
    },
  );

  it.each(["draft", "running", "completed", "failed"])(
    "keeps %s cases inspectable without offering mutations in read-only mode",
    async (status) => {
      controls.canWrite = false;
      const fetcher = setup({ status });
      await screen.findByRole("tab", { name: "Overview" });
      expect(
        screen.queryByRole("button", {
          name: /Run investigation|Run again|Cancel run/,
        }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Read latest dossier" }),
      ).toBeInTheDocument();
      expect(
        fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
      ).toBe(false);
    },
  );

  it.each([
    { status: "draft", button: "Run investigation", action: "run" },
    { status: "running", button: "Cancel run", action: "cancel" },
  ])(
    "preserves the authorized $action action",
    async ({ status, button, action }) => {
      const fetcher = setup({ status });
      fireEvent.click(await screen.findByRole("button", { name: button }));
      await waitFor(() =>
        expect(
          fetcher.mock.calls.some(
            ([url, options]) =>
              url.endsWith(`/${action}`) && options?.method === "POST",
          ),
        ).toBe(true),
      );
      const posts = fetcher.mock.calls.filter(
        ([, options]) => options?.method === "POST",
      );
      expect(posts).toHaveLength(1);
      expect(
        (posts[0][1]?.headers as Record<string, string>)["Idempotency-Key"],
      ).toBeTruthy();
    },
  );
});
