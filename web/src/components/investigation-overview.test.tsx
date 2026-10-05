// Synthetic UI records only; these are not research findings or agent runs.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  parseArtifact,
  parseCaseDetail,
  type Artifact,
  type JsonObject,
} from "@/lib/contracts";
import { artifactFixture, caseFixture } from "@/test/fixtures";
import {
  InvestigationOverview,
  investigationReading,
} from "./investigation-overview";

function artifact(
  id: string,
  kind: string,
  content: JsonObject = {},
  time = "2026-10-05T10:00:00Z",
): Artifact {
  return parseArtifact({
    ...artifactFixture,
    id,
    kind,
    title: id,
    content,
    created_at: time,
  });
}
const source = artifact("Synthetic source", "evidence");
const dossier = artifact("Latest synthetic dossier", "clinical_dossier", {
  validation: { valid: true },
  dossier: {
    claims: [
      {
        id: "claim-1",
        kind: "inference",
        statement: "Synthetic inference, not an investment result.",
        source_refs: [
          { artifact_id: source.id },
          { artifact_id: "shared-source" },
        ],
      },
    ],
    missing_inputs: [
      {
        field: "Follow-up data",
        reason: "The fixture has none.",
        consequence: "Leave the question open.",
      },
    ],
    uncertainty: ["Synthetic uncertainty"],
  },
});
function detail(artifacts: Artifact[] = []) {
  return parseCaseDetail({
    ...caseFixture,
    tasks: [],
    artifacts,
    tool_calls: [],
    events: [],
  });
}
function show(artifacts: Artifact[] = []) {
  const onOpen = vi.fn(),
    onOpenSource = vi.fn(),
    onNavigate = vi.fn();
  const result = render(
    <InvestigationOverview
      data={detail(artifacts)}
      onOpen={onOpen}
      onOpenSource={onOpenSource}
      loadingSource={null}
      onNavigate={onNavigate}
    >
      Task details
    </InvestigationOverview>,
  );
  return { ...result, onOpen, onOpenSource, onNavigate };
}

describe("investigation overview", () => {
  it("selects the latest dossier by timestamp without mutating the server order or exposing private evaluations", () => {
    const old = artifact(
      "Old dossier",
      "clinical_dossier",
      { dossier: { claims: [{ statement: "Old claim" }] } },
      "2026-10-04T10:00:00Z",
    );
    const hidden = artifact("PRIVATE KEY", "evaluation_reference", {
      expected_value: "PRIVATE ANSWER",
    });
    const data = detail([dossier, hidden, old, source]);
    const order = data.artifacts.map((a) => a.id);
    expect(investigationReading(data).dossierArtifact?.id).toBe(dossier.id);
    expect(data.artifacts.map((a) => a.id)).toEqual(order);
    const { container } = show(data.artifacts);
    expect(container.textContent).not.toContain("Old claim");
    expect(container.textContent).not.toContain("PRIVATE");
  });

  it("opens the exact local source and resolves a shared source by its recorded id", () => {
    const { onOpen, onOpenSource } = show([dossier, source]);
    const findings = screen.getByRole("region", {
      name: "Findings to examine",
    });
    fireEvent.click(
      within(findings).getByRole("button", { name: source.title }),
    );
    expect(onOpen).toHaveBeenCalledWith(source);
    fireEvent.click(
      within(findings).getByRole("button", { name: "Linked source 2" }),
    );
    expect(onOpenSource).toHaveBeenCalledWith("shared-source");
    expect(
      screen.getByText(/1 additional source is linked from outside this case/),
    ).toBeInTheDocument();
    expect(within(findings).getByText("Inference")).toBeInTheDocument();
    expect(
      screen.getByText(/Source checks passed; interpretation needs review/),
    ).toBeInTheDocument();
  });

  it("keeps rejection, its reason, competing explanations and falsification visible", () => {
    show([
      artifact("Rejected hypothesis", "hypothesis", {
        status: "rejected",
        prediction: "Synthetic prediction",
        disposition_reason: "Contradictory evidence in the fixture.",
        competing_explanation: "Alternative explanation",
        falsification_rule: "A specific falsification condition",
      }),
    ]);
    const question = screen.getByRole("region", {
      name: "Rejected hypothesis",
    });
    for (const expected of [
      "Rejected",
      "Contradictory evidence in the fixture.",
      "Alternative explanation",
      "A specific falsification condition",
    ])
      expect(within(question).getByText(expected)).toBeInTheDocument();
  });

  it("shows missing evidence without inventing a conclusion from source-only observations", () => {
    show([
      artifact("Source-only dossier", "clinical_dossier", {
        dossier: { claims: [], observations: [{ count: 42 }] },
      }),
    ]);
    expect(
      screen.getByText(
        "Evidence is recorded. A research conclusion is still open.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Findings to examine" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/does not establish completeness/),
    ).toBeInTheDocument();
    expect(screen.getByText("No agent work has run yet")).toBeInTheDocument();
  });

  it("keeps malformed legacy content inspectable without manufacturing claims", () => {
    show([
      artifact("Legacy dossier", "clinical_dossier", {
        validation: { valid: "yes" },
        dossier: {
          claims: [null, "bad", { statement: 2 }],
          missing_inputs: [null],
          uncertainty: [false],
        },
      }),
    ]);
    expect(
      screen.getByRole("button", { name: "Read latest dossier" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Source checks not recorded/)).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Findings to examine" }),
    ).not.toBeInTheDocument();
  });

  it("keeps long findings and citation lists bounded with access to the full dossier", () => {
    const claims = Array.from({ length: 5 }, (_, i) => ({
      id: `c-${i}`,
      kind: "fact",
      statement: `Synthetic claim ${i}`,
      source_refs: Array.from({ length: 8 }, (_, n) => ({
        artifact_id: `source-${n}`,
      })),
    }));
    const long = artifact("Long dossier", "clinical_dossier", {
      dossier: { claims },
    });
    const { onOpen } = show([long]);
    const findings = screen.getByRole("region", {
      name: "Findings to examine",
    });
    expect(within(findings).getAllByRole("listitem")).toHaveLength(3);
    expect(
      within(findings).queryByText("Synthetic claim 3"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Read all 5 claims" }));
    expect(onOpen).toHaveBeenCalledWith(long);
    expect(
      within(findings).getAllByRole("button", {
        name: "All 8 source references",
      }),
    ).toHaveLength(3);
  });
});
