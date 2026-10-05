// Synthetic UI fixtures only; no clinical findings or measured model performance.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseArtifact, type JsonObject } from "@/lib/contracts";
import { artifactFixture } from "@/test/fixtures";
import { ArtifactContent } from "./artifacts";

function score(matched: number): JsonObject {
  return {
    schema_version: "clinical-mechanical-score.v1",
    status: "scored",
    matched_fields: matched,
    expected_fields: 4,
    delivered_scoped_fraction: matched / 4,
    candidate_validation: {
      schema_valid: true,
      issue_count: 0,
      code: "schema_valid",
    },
    field_results: [
      {
        field_id: "synthetic-count",
        observation_id: "count-1",
        field_name: "count",
        status: "matched",
        reason: "value_and_source",
        value_agreement: true,
      },
      {
        field_id: "synthetic-role",
        observation_id: "endpoint-1",
        field_name: "reported_role",
        status: "unattributed",
        reason: "field_citation_binding",
        value_agreement: true,
      },
    ],
  };
}

function report(overrides: JsonObject = {}): JsonObject {
  return {
    schema_version: "clinical-mechanical-comparison.v1",
    candidate: score(3),
    baseline: score(1),
    delivered_scoped_fraction_delta: 0.5,
    dataset_case_id: "synthetic-dataset-case",
    database_case_id: "synthetic-local-case",
    scope_sha256: "a".repeat(64),
    reference_sha256: "b".repeat(64),
    sources: [
      {
        source_id: "synthetic-source",
        id: "evidence-artifact",
        kind: "evidence",
        sha256: "c".repeat(64),
      },
    ],
    inputs: [
      {
        id: "candidate-artifact",
        kind: "clinical_dossier",
        sha256: "d".repeat(64),
      },
    ],
    ...overrides,
  };
}

function show(content: JsonObject) {
  return render(
    <ArtifactContent
      artifact={parseArtifact({
        ...artifactFixture,
        kind: "evaluation_report",
        content,
      })}
    />,
  );
}

describe("protected guided extraction comparisons", () => {
  it("routes the versioned report to scoped delivery counts and a percentage-point difference", () => {
    show(report());
    const comparison = screen.getByRole("table", {
      name: "Delivered fields within the declared scope",
    });
    expect(within(comparison).getByText("3 / 4")).toBeInTheDocument();
    expect(within(comparison).getByText("1 / 4")).toBeInTheDocument();
    expect(within(comparison).getByText("75.0%")).toBeInTheDocument();
    expect(within(comparison).getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("+50.0 pp")).toBeInTheDocument();
    expect(
      screen.getByText(/does not measure clinical quality/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/F1/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Frozen output comparison"),
    ).not.toBeInTheDocument();
  });

  it("retains no submission and invalid output as explicit zero-delivery results", () => {
    show(
      report({
        candidate: {
          ...score(0),
          status: "no_submission",
          candidate_validation: {
            schema_valid: null,
            issue_count: 0,
            code: "no_submission",
          },
        },
        baseline: {
          ...score(0),
          status: "invalid_output",
          candidate_validation: {
            schema_valid: false,
            issue_count: 1,
            code: "root_or_budget",
          },
        },
        delivered_scoped_fraction_delta: 0,
      }),
    );
    const comparison = screen.getByRole("table", {
      name: "Delivered fields within the declared scope",
    });
    expect(within(comparison).getByText("No submission")).toBeInTheDocument();
    expect(within(comparison).getByText("Invalid output")).toBeInTheDocument();
    expect(
      within(comparison).getByText("Not assessed · no submission"),
    ).toBeInTheDocument();
    expect(
      within(comparison).getByText("Invalid schema · 1 issue"),
    ).toBeInTheDocument();
    expect(within(comparison).getAllByText("0 / 4")).toHaveLength(2);
    expect(screen.getByText("0.0 pp")).toBeInTheDocument();
  });

  it("keeps complete schema failure separate from scoped matches", () => {
    show(
      report({
        candidate: {
          ...score(3),
          candidate_validation: {
            schema_valid: false,
            issue_count: 2,
            code: "schema_invalid",
          },
        },
      }),
    );
    const comparison = screen.getByRole("table", {
      name: "Delivered fields within the declared scope",
    });
    expect(
      within(comparison).getByText("Invalid schema · 2 issues"),
    ).toBeInTheDocument();
    expect(within(comparison).getByText("3 / 4")).toBeInTheDocument();
    expect(within(comparison).getByText("75.0%")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Schema validation is separate from scoped field matching/,
      ),
    ).toBeInTheDocument();
  });

  it("reveals field identities and failed attribution even when the value agrees", () => {
    show(report());
    fireEvent.click(screen.getByText("Candidate field results · 2"));
    const fields = screen.getByRole("table", {
      name: "Candidate guided extraction fields",
    });
    const row = within(fields).getByText("synthetic-role").closest("tr")!;
    expect(within(row).getByText("Unattributed")).toBeInTheDocument();
    expect(within(row).getByText("Field Citation Binding")).toBeInTheDocument();
    expect(within(row).getByText("Value agreement: Yes")).toBeInTheDocument();
    expect(
      within(row).getByText("Observation: endpoint-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Candidate field results" }),
    ).toHaveAttribute("tabindex", "0");
  });

  it("exposes only allowlisted source/input identities and digests, never hidden reference content", () => {
    const data = report({
      expected_value: "PRIVATE_EXPECTED_VALUE",
      reference: {
        fields: [
          {
            expected_value: "PRIVATE_REFERENCE",
            rationale: "PRIVATE_RATIONALE",
          },
        ],
      },
      reviewer_notes: "PRIVATE_REVIEWER_NOTE",
      sources: [
        {
          source_id: "synthetic-source",
          id: "evidence-artifact",
          kind: "evidence",
          sha256: "c".repeat(64),
          expected_value: "PRIVATE_SOURCE_EXTRA",
        },
      ],
      candidate: { ...score(3), reviewer_notes: "PRIVATE_CANDIDATE_EXTRA" },
    });
    const { container } = show(data);
    fireEvent.click(
      screen.getByText("Frozen source bindings and input digests"),
    );
    expect(screen.getByText("synthetic-dataset-case")).toBeInTheDocument();
    expect(screen.getByText("synthetic-source")).toBeInTheDocument();
    expect(screen.getByText("evidence-artifact")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("c".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("d".repeat(64))).toBeInTheDocument();
    expect(container.textContent).not.toContain("PRIVATE_");
  });

  it("renders malformed data without inventing counts, successful schema checks or a delta", () => {
    show(
      report({
        candidate: {
          status: "scored",
          matched_fields: true,
          expected_fields: "4",
          delivered_scoped_fraction: 1,
          candidate_validation: { schema_valid: "true" },
          field_results: [null, false, "broken"],
        },
        baseline: false,
        sources: [false, null],
        inputs: {},
        delivered_scoped_fraction_delta: 1,
      }),
    );
    const comparison = screen.getByRole("table", {
      name: "Delivered fields within the declared scope",
    });
    expect(within(comparison).queryByText("100.0%")).not.toBeInTheDocument();
    expect(
      within(comparison).queryByText("Valid schema"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getAllByText("No field results recorded.")).toHaveLength(2);
    expect(
      screen.getByText("No source bindings recorded."),
    ).toBeInTheDocument();
  });

  it("does not display a fraction or delta that contradicts frozen counts", () => {
    show(
      report({
        candidate: { ...score(3), delivered_scoped_fraction: 1 },
        delivered_scoped_fraction_delta: 0.75,
      }),
    );
    expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
  });

  it("uses signed percentage points for a negative comparison", () => {
    show(
      report({
        candidate: score(1),
        baseline: score(3),
        delivered_scoped_fraction_delta: -0.5,
      }),
    );
    expect(screen.getByText("-50.0 pp")).toBeInTheDocument();
    expect(screen.queryByText("-50.0%")).not.toBeInTheDocument();
  });
});
