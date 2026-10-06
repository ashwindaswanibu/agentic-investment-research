import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  forecastEvidence,
  forecastFixture,
  forecastHypothesis,
  forecastNote,
  resolutionFixture,
} from "@/test/forecast-fixtures";
import { ForecastPanel } from "./forecasts";

const controls = vi.hoisted(() => ({ canWrite: true }));
vi.mock("./app-shell", () => ({ useEnvironment: () => controls }));
beforeEach(() => {
  controls.canWrite = true;
});
afterEach(() => vi.unstubAllGlobals());

function setup(
  initial = [forecastFixture()],
  options: { conflict?: boolean; sourceHash?: string } = {},
) {
  let items = initial;
  const onOpen = vi.fn();
  const onChanged = vi.fn();
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    let body: unknown = { items },
      status = 200;
    if (url.includes("/artifacts/"))
      body = {
        ...forecastEvidence,
        sha256: options.sourceHash ?? forecastEvidence.sha256,
      };
    else if (init?.method === "POST") {
      if (options.conflict) {
        status = 409;
        body = {
          error: {
            code: "resolution_conflict",
            message: "Another operator appended a newer judgment.",
          },
        };
      } else {
        status = 201;
        body = url.endsWith("/resolutions")
          ? resolutionFixture()
          : forecastFixture().forecast;
      }
    }
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <ForecastPanel
      caseId="test-case"
      artifacts={[forecastHypothesis, forecastEvidence, forecastNote]}
      onOpen={onOpen}
      onChanged={onChanged}
    />,
  );
  return {
    fetcher,
    onOpen,
    onChanged,
    setItems: (next: typeof initial) => {
      items = next;
    },
  };
}
const change = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
function fillResolution() {
  change("Observed outcome", "yes");
  change(
    "Operator rationale",
    "The saved Yes rule is met by the cited evidence.",
  );
  change("Evidence artifact 1", forecastEvidence.id);
  change("Exact excerpt 1", "The event occurred.");
}
async function openRegistration(abstain = false) {
  fireEvent.click(
    await screen.findByRole("button", { name: "Register forecast" }),
  );
  change("Linked hypothesis", forecastHypothesis.id);
  change(
    "Binary question",
    "Will the defined event occur in the future window?",
  );
  change(/Window opens/, "2099-02-01T09:30");
  change(/Window closes/, "2099-03-01T09:30");
  if (abstain) {
    change("Commitment", "abstain");
    change("Reason for abstaining", "Insufficient source support.");
  } else change("Forecast P(Yes) · %", "0");
  change("Baseline P(Yes) · %", "50");
  change("Baseline rationale", "Neutral reference probability.");
  change("Yes resolution rule", "Source confirms event in window.");
  change("No resolution rule", "Source confirms no event in window.");
  change("Unresolvable rule", "Source cannot distinguish outcomes.");
  change("Designated resolution source", "Published event report.");
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Synthetic source publication/ }),
  );
}

describe("forecast lifecycle panel", () => {
  it("retains all states, puts due work first, and marks synthetic and unscored records", async () => {
    const resolved = forecastFixture("resolved", "resolved");
    resolved.forecast.content.probability = 1;
    resolved.latest_resolution = resolutionFixture();
    resolved.resolutions = [resolved.latest_resolution];
    resolved.assessment = {
      status: "resolved",
      scored: true,
      brier: 0,
      baseline_brier: 0.25,
      improvement: 0.25,
    };
    setup([
      resolved,
      forecastFixture("pending", "pending"),
      forecastFixture("abstained", "abstained"),
      forecastFixture("due", "due"),
      forecastFixture("unresolvable", "unresolvable"),
    ]);
    const records = await screen.findAllByRole("article");
    expect(records).toHaveLength(5);
    expect(records[0]).toHaveAccessibleName("Will synthetic event due occur?");
    expect(within(records[0]).getByText("Synthetic fixture")).toBeVisible();
    expect(screen.getByText("0.0000")).toBeVisible();
    expect(screen.getByText("+0.2500")).toBeVisible();
    expect(
      screen.getByText(/A single outcome is not a calibration assessment/),
    ).toBeVisible();
    expect(
      within(
        screen.getByRole("article", { name: /pending occur/ }),
      ).queryByRole("button", { name: "Record resolution" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /An outcome can be recorded; this abstention remains unscored/,
      ),
    ).toBeVisible();
  });
  it("keeps exact sources inspectable without mutations in read-only mode", async () => {
    controls.canWrite = false;
    const resolved = forecastFixture("resolved", "resolved");
    resolved.latest_resolution = resolutionFixture();
    resolved.resolutions = [resolved.latest_resolution];
    const { onOpen, fetcher } = setup([resolved]);
    await screen.findByRole("article");
    expect(
      screen.queryByRole("button", {
        name: /Register forecast|Append correction|Record resolution/,
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "Open exact evidence 1" })[0],
    );
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(forecastEvidence));
    expect(
      fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
  });
  it("refuses to open a source that differs from its recorded hash", async () => {
    const { onOpen } = setup(undefined, { sourceHash: "c".repeat(64) });
    await screen.findByRole("article");
    fireEvent.click(
      screen.getByText("Registration, resolution rules & sources"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Synthetic source publication" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not match the recorded source ID and content hash",
    );
    expect(onOpen).not.toHaveBeenCalled();
  });
  it.each([false, true])(
    "registers an immutable forecast or abstention with local-to-UTC window and exact hypothesis version (%s)",
    async (abstain) => {
      const { fetcher, onChanged } = setup([]);
      await openRegistration(abstain);
      fireEvent.click(
        screen.getByRole("button", {
          name: abstain ? "Register abstention" : "Save immutable forecast",
        }),
      );
      await waitFor(() => expect(onChanged).toHaveBeenCalled());
      const [, init] = fetcher.mock.calls.find(
        ([, options]) => options?.method === "POST",
      )!;
      const body = JSON.parse(init!.body as string);
      expect(body).toMatchObject({
        hypothesis_id: forecastHypothesis.id,
        hypothesis_sha256: forecastHypothesis.sha256,
        opens_at: new Date(2099, 1, 1, 9, 30).toISOString(),
        closes_at: new Date(2099, 2, 1, 9, 30).toISOString(),
        status: abstain ? "abstain" : "forecast",
        probability: abstain ? null : 0,
        baseline_probability: 0.5,
        source_artifact_ids: [forecastEvidence.id],
      });
      expect(body).not.toHaveProperty("registered_at");
      expect(
        (init!.headers as Record<string, string>)["Idempotency-Key"],
      ).toBeTruthy();
    },
  );
  it("blocks backdated registration before sending a mutation", async () => {
    const { fetcher } = setup([]);
    await openRegistration();
    change(/Window opens/, "2020-01-01T00:00");
    fireEvent.click(
      screen.getByRole("button", { name: "Save immutable forecast" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "cannot be backdated",
    );
    expect(
      fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
  });
  it("appends a source-linked operator judgment with an exact excerpt and no previous revision", async () => {
    const { fetcher, onChanged } = setup();
    fireEvent.click(
      await screen.findByRole("button", { name: "Record resolution" }),
    );
    fillResolution();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Locate excerpt with a JSON pointer",
      }),
    );
    change("JSON pointer 1", "/text");
    expect(
      within(screen.getByLabelText("Evidence artifact 1")).queryByText(
        /Synthetic research note/,
      ),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save resolution" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [url, init] = fetcher.mock.calls.find(
      ([, options]) => options?.method === "POST",
    )!;
    expect(url).toBe("/api/forecasts/forecast-1/resolutions");
    expect(JSON.parse(init!.body as string)).toMatchObject({
      outcome: "yes",
      previous_resolution_id: null,
      source_refs: [
        {
          artifact_id: forecastEvidence.id,
          artifact_sha256: forecastEvidence.sha256,
          excerpt: "The event occurred.",
          source_path: "/text",
        },
      ],
    });
  });
  it("pins corrections to the opened revision and requires refreshed review after a conflict", async () => {
    const record = forecastFixture("forecast-1", "resolved");
    record.latest_resolution = resolutionFixture("resolution-1");
    record.resolutions = [record.latest_resolution];
    const { fetcher, setItems } = setup([record], { conflict: true });
    fireEvent.click(
      await screen.findByRole("button", { name: "Append correction" }),
    );
    fillResolution();
    const next = {
      ...record,
      latest_resolution: resolutionFixture("resolution-2", "resolution-1"),
      resolutions: [
        ...record.resolutions,
        resolutionFixture("resolution-2", "resolution-1"),
      ],
    };
    setItems([next]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh forecasts" }));
    await screen.findByText("Resolution history · 2 entries");
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Another operator appended a newer judgment.",
    );
    const [, init] = fetcher.mock.calls.find(
      ([, options]) => options?.method === "POST",
    )!;
    expect(JSON.parse(init!.body as string).previous_resolution_id).toBe(
      "resolution-1",
    );
    expect(
      screen.getByRole("button", { name: "Save correction" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Reload resolution history" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("form", { name: "Append resolution correction" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Append correction" }),
    ).toBeEnabled();
  });
});
