// Synthetic presentation fixtures only; these are not research findings or medical facts.
import { render, screen, within, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArtifactCard, ArtifactContent } from "./artifacts";
import {
  ARTIFACT_KINDS,
  parseArtifact,
  type JsonObject,
} from "@/lib/contracts";
import { artifactFixture } from "@/test/fixtures";

const artifact = (kind: string, content: JsonObject | string = {}) =>
  parseArtifact({
    ...artifactFixture,
    kind,
    title: "Synthetic rendering record",
    content,
  });

const dossier: JsonObject = {
  dossier: {
    intervention: "Fictional Test A",
    indication: "Synthetic condition",
    population: "Synthetic adults",
    trials: [
      {
        trial_id: "SYNTHETIC-001",
        design: { allocation: "randomized" },
        arms: [
          {
            label: "Synthetic arm",
            intervention: "Fictional Test A",
            role: "treatment",
            planned_n: null,
          },
        ],
        endpoints: [
          {
            name: "Synthetic score",
            kind: "primary",
            timeframe: "Week 12",
            prespecified: "unknown",
          },
        ],
      },
    ],
    claims: [
      {
        id: "test-claim",
        kind: "inference",
        statement: "Synthetic inference for rendering",
        inference_basis: "A test reasoning gap, not a scientific conclusion.",
        source_refs: [
          {
            artifact_id: "test-source",
            artifact_sha256: "a".repeat(64),
            excerpt: "<script>not executable</script>",
            source_path: "/record/text",
          },
        ],
      },
    ],
    contrary_evidence_summary:
      "No contrary evidence in this synthetic fixture.",
    contrary_evidence_claim_ids: [],
    uncertainty: ["Synthetic uncertainty only."],
    missing_inputs: [
      {
        field: "Safety",
        reason: "No synthetic results",
        consequence: "No safety assessment",
      },
    ],
    forecast: {
      status: "abstain",
      target: "Synthetic primary outcome",
      as_of: "2026-01-01",
      horizon: "2026-12-31",
      outcome_rule: "Resolve against synthetic reference",
      abstention_reason: "Insufficient test evidence",
      resolution_source: "Synthetic registry",
    },
  },
  validation: {
    valid: true,
    coverage: {
      trials: 1,
      claims: 1,
      verified_source_references: 1,
      distinct_sources: 1,
    },
    failed_checks: [],
  },
};

describe("research quality and reusable capability artifacts", () => {
  it("shows clinical attribution scope, trial fields, exact citations and explicit abstention", () => {
    const { container } = render(
      <ArtifactContent artifact={artifact("clinical_dossier", dossier)} />,
    );
    expect(screen.getByText("Attribution checks passed")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Clinical truth, inference quality and predictive skill/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("SYNTHETIC-001")).toBeInTheDocument();
    expect(screen.getByText("Not reported")).toBeInTheDocument();
    expect(screen.getByText("Week 12")).toBeInTheDocument();
    expect(screen.getByText("Forecast withheld")).toBeInTheDocument();
    expect(screen.getByText("Insufficient test evidence")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Synthetic inference for rendering"));
    expect(screen.getByText("test-source")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(
      screen.getByText("<script>not executable</script>"),
    ).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });

  it("makes failed attribution checks actionable without treating them as a medical verdict", () => {
    const content = {
      ...dossier,
      validation: {
        valid: false,
        failed_checks: [
          {
            code: "quote_present",
            path: "/claims/0/source_refs/0",
            message: "Quote absent from retained source.",
          },
        ],
      },
    };
    render(
      <ArtifactContent artifact={artifact("clinical_dossier", content)} />,
    );
    expect(
      screen.getByText("Attribution checks need attention"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Quote absent from retained source."),
    ).toBeInTheDocument();
    expect(screen.getByText("/claims/0/source_refs/0")).toBeInTheDocument();
  });

  it("shows measured candidate/baseline scores and critical field differences", () => {
    const score = {
      valid: true,
      precision: 0.75,
      recall: 0.6,
      f1: 2 / 3,
      true_positives: 3,
      false_positives: 1,
      false_negatives: 2,
      reference_fields: 5,
      candidate_fields: 4,
      critical_errors: [
        {
          path: "/trials/test/allocation",
          code: "value_mismatch",
          expected: "randomized",
          actual: "nonrandomized",
        },
      ],
      limitations: ["Synthetic reference comparison only."],
    };
    render(
      <ArtifactContent
        artifact={artifact("evaluation_report", {
          candidate: score,
          baseline: {
            ...score,
            precision: 0.5,
            recall: 0.4,
            f1: 4 / 9,
            critical_errors: [],
          },
          f1_delta: 2 / 9,
          scope: "Synthetic paired assessment; not a population estimate.",
          protocol: "Frozen synthetic outputs",
        })}
      />,
    );
    const comparison = screen.getByRole("table", {
      name: "Frozen output comparison",
    });
    expect(within(comparison).getByText("0.750")).toBeInTheDocument();
    expect(within(comparison).getByText("0.444")).toBeInTheDocument();
    expect(screen.getByText("+0.222")).toBeInTheDocument();
    expect(
      screen.getByText("Candidate critical errors · 1"),
    ).toBeInTheDocument();
    expect(screen.getByText("nonrandomized")).toBeInTheDocument();
  });

  it("does not coerce missing or malformed scores into success", () => {
    render(
      <ArtifactContent
        artifact={artifact("evaluation_report", {
          candidate: { valid: true, precision: false, recall: "1.0", f1: 4 },
          baseline: null,
          f1_delta: "1",
        })}
      />,
    );
    const comparison = screen.getByRole("table", {
      name: "Frozen output comparison",
    });
    expect(within(comparison).queryByText("1.000")).toBeNull();
    expect(screen.queryByText("F1 difference")).toBeNull();
  });

  it("exposes specialist remit and tool limits without inventing activation", () => {
    render(
      <ArtifactContent
        artifact={artifact("specialist_spec", {
          name: "Synthetic specialist",
          domain: "Synthetic domain",
          mandate: "Investigate a test question",
          signal_rationale: "Test rationale",
          evidence_standards: "Use attributed evidence",
          output_standards: "Retain uncertainty",
          allowed_tools: ["read_artifact", "search_library"],
        })}
      />,
    );
    expect(screen.getByText("Investigate a test question")).toBeInTheDocument();
    expect(screen.getByText("search_library")).toBeInTheDocument();
    expect(
      screen.getByText(/Activation requires an independent review/),
    ).toBeInTheDocument();
  });

  it("counts actual qualification outcomes separately from unresolved records", () => {
    render(
      <ArtifactContent
        artifact={artifact("research_tool_qualification", {
          status: "failed",
          results: [
            { passed: true, ok: true, output: 3 },
            { passed: false, ok: true, output: 4 },
            { passed: "true" },
          ],
        })}
      />,
    );
    const group = screen.getByRole("group", {
      name: "Recorded qualification checks",
    });
    expect(within(group).getAllByText("1")).toHaveLength(3);
    expect(screen.getByText("Test 2 · Failed")).toBeInTheDocument();
    expect(screen.getByText("Test 3 · Unresolved")).toBeInTheDocument();
  });

  it("renders every new kind and malformed content safely with inspectable fallback", () => {
    for (const kind of ARTIFACT_KINDS) {
      const { unmount } = render(
        <ArtifactContent
          artifact={artifact(kind, "Malformed structured test content")}
        />,
      );
      unmount();
    }
    render(
      <ArtifactContent
        artifact={artifact("clinical_dossier", {
          dossier: false,
          validation: [],
        })}
      />,
    );
    expect(
      screen.getByText(
        "A structured clinical dossier is unavailable in this record.",
      ),
    ).toBeInTheDocument();
  });

  it("supports future artifact kinds with a safe card icon and generic content", () => {
    const onOpen = vi.fn();
    const item = artifact("future_research_record", {
      summary: "A future typed record",
    });
    render(
      <>
        <ArtifactCard artifact={item} onOpen={onOpen} />
        <ArtifactContent artifact={item} />
      </>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Synthetic rendering record/ }),
    );
    expect(onOpen).toHaveBeenCalledWith(item);
    expect(screen.getByText("A future typed record")).toBeInTheDocument();
  });
});
