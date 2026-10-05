// Synthetic UI fixtures only: these values are not clinical evidence or measured research results.
import { render, screen, within, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Json, JsonObject } from "@/lib/contracts";
import { ClinicalDossierContent } from "./research-artifacts";

const present = (value: Json) => ({ state: "present", value });
const unresolved = {
  state: "unresolved",
  reason: "Synthetic evidence does not settle this.",
};
const notApplicable = {
  state: "not_applicable",
  reason: "This fictional population has no comparator.",
};
const source = {
  artifact_id: "synthetic-source",
  artifact_sha256: "a".repeat(64),
  source_path: "/record/outcomes/0",
};
const ref = {
  ...source,
  source_path: "/record/text",
  excerpt: "Synthetic attributed statement.",
};
const common = { context_id: "ctx-a", source_refs: [ref] };
const count: JsonObject = {
  ...common,
  kind: "population_count",
  observation_id: "count-assigned",
  group: { container: source, local_id: " OG000 " },
  count: present(0),
  count_normalization: "integer_from_digit_string",
  count_source_ref: { ...ref, source_path: "/record/count", excerpt: "0" },
  unit: present("participants"),
  population_definition: present("Synthetic randomized and dosed population"),
  reported_stage: present("Randomized and dosed"),
  stages: present(["randomized", "dosed"]),
  assignment_basis: present("as_assigned"),
  reported_status: unresolved,
};
const endpoint: JsonObject = {
  ...common,
  kind: "endpoint",
  observation_id: "endpoint-a",
  definition: present("Fictional score change"),
  reported_role: present("primary"),
  timeframe: present("12 weeks"),
  time_origin: present("randomization"),
  population_definition: unresolved,
  comparator_description: notApplicable,
  population_count_ids: ["count-assigned"],
  groups: [],
  prespecification: unresolved,
};
const design: JsonObject = {
  ...common,
  kind: "design",
  observation_id: "design-assignment",
  design_scope: "trial_assignment",
  study_type: present("interventional"),
  allocation: present("randomized"),
  intervention_model: present("PARALLEL"),
  masking: unresolved,
  phase: unresolved,
  comparator_source: present("concurrent_internal"),
};
const availability: JsonObject = {
  ...common,
  kind: "availability",
  observation_id: "results-availability",
  subject: "registry_results",
  available: present(false),
  available_source_ref: {
    ...ref,
    source_path: "/record/hasResults",
    excerpt: "false",
  },
  scope_description: "Only the frozen synthetic registry snapshot.",
};

function content(
  observations: JsonObject[] = [count, endpoint, design, availability],
): JsonObject {
  return {
    dossier: {
      schema_version: "clinical-dossier.v2",
      intervention: "Synthetic intervention",
      indication: "Synthetic condition",
      population: "Synthetic population",
      trials: [
        { trial_id: "SYNTHETIC-TRIAL", trial_family_id: "SYNTHETIC-FAMILY" },
      ],
      contexts: [
        {
          context_id: "ctx-a",
          trial_id: "SYNTHETIC-TRIAL",
          kind: "outcome_analysis",
          label: "First synthetic analysis",
          source,
          analysis_id: "synthetic-analysis-a",
        },
        {
          context_id: "ctx-b",
          trial_id: "SYNTHETIC-TRIAL",
          kind: "outcome_analysis",
          label: "Second synthetic analysis",
          source: { ...source, source_path: "/record/outcomes/12" },
        },
      ],
      observations,
      reconciliations: [],
      claims: [],
      contrary_evidence_claim_ids: [],
      contrary_evidence_summary: "Synthetic UI fixture only.",
      missing_inputs: [],
      uncertainty: ["No clinical conclusion can follow from this test."],
      forecast: null,
    },
    validation: {
      valid: true,
      coverage: {
        trials: 1,
        contexts: 2,
        observations: observations.length,
        distinct_sources: 1,
      },
      failed_checks: [],
    },
  };
}

function observation(id: string) {
  return screen.getByRole("region", { name: `Observation ${id}` });
}

describe("source-qualified clinical dossier presentation", () => {
  it("keeps explicit zero, false and source null distinct from missing values", () => {
    render(
      <ClinicalDossierContent
        content={content([
          count,
          availability,
          {
            ...count,
            observation_id: "count-null",
            count: present(null),
            count_normalization: "none",
          },
        ])}
      />,
    );
    expect(
      within(observation("count-assigned")).getByText("0", {
        selector: "span",
      }),
    ).toBeVisible();
    expect(
      within(observation("results-availability")).getByText("False"),
    ).toBeVisible();
    expect(
      within(observation("count-null")).getByText("Present · null"),
    ).toBeVisible();
    expect(
      screen.getByText("Structure and attribution checks passed"),
    ).toBeVisible();
    expect(
      screen.getByText(
        /Clinical truth, inference quality and predictive skill/,
      ),
    ).toBeVisible();
    expect(screen.getByText("No forecast submitted")).toBeVisible();
    expect(screen.queryByText("Recorded prediction")).toBeNull();
  });

  it("shows the exact missing key and parent location without implying global absence", () => {
    const absent = {
      state: "source_absent",
      reason: "The exact synthetic key is absent in this retained object.",
      proof: {
        parent: { ...source, source_path: "/record/design" },
        key: " safety ",
      },
    };
    render(
      <ClinicalDossierContent
        content={content([{ ...endpoint, timeframe: absent }])}
      />,
    );
    const region = observation("endpoint-a");
    expect(within(region).getByText("Source key absent")).toBeVisible();
    expect(within(region).getByText('" safety "')).toBeVisible();
    expect(within(region).getByText("/record/design")).toBeVisible();
    expect(
      within(region).getByText(/this key only, not all available evidence/),
    ).toBeVisible();
    expect(within(region).getAllByText("Unresolved").length).toBeGreaterThan(0);
    expect(within(region).getByText("Not applicable")).toBeVisible();
  });

  it("keeps identical group IDs in different source containers separate", () => {
    render(
      <ClinicalDossierContent
        content={content([
          count,
          {
            ...count,
            context_id: "ctx-b",
            observation_id: "count-safety",
            count: present(2),
            group: {
              container: { ...source, source_path: "/record/outcomes/12" },
              local_id: " OG000 ",
            },
            assignment_basis: present("actual_treatment_received"),
          },
        ])}
      />,
    );
    const first = observation("count-assigned");
    const second = observation("count-safety");
    expect(within(first).getByText('" OG000 "')).toBeVisible();
    expect(within(second).getByText('" OG000 "')).toBeVisible();
    expect(within(first).getByText("/record/outcomes/0")).toBeVisible();
    expect(within(second).getByText("/record/outcomes/12")).toBeVisible();
    expect(within(first).getByText("As Assigned")).toBeVisible();
    expect(within(second).getByText("Actual Treatment Received")).toBeVisible();
    expect(
      within(second).getByText(/Context: Second synthetic analysis/),
    ).toBeVisible();
    expect(within(first).getByText("Randomized + Dosed")).toBeVisible();
    expect(
      within(first).getByText("Population conditions (all apply)"),
    ).toBeVisible();
  });

  it("shows count normalization and expandable exact count citations", () => {
    const { container } = render(
      <ClinicalDossierContent
        content={content([
          {
            ...count,
            count_source_ref: {
              ...ref,
              excerpt: "<script>synthetic text, not executable</script>",
            },
          },
          {
            ...count,
            observation_id: "text-count",
            count_normalization: "reported_in_text",
          },
        ])}
      />,
    );
    const first = observation("count-assigned");
    expect(
      within(first).getByText("Digit string converted to an integer"),
    ).toBeVisible();
    expect(
      within(observation("text-count")).getByText(
        "Count extracted from source text",
      ),
    ).toBeVisible();
    fireEvent.click(within(first).getByText("Citations for count-assigned"));
    expect(within(first).getByText("Count source")).toBeVisible();
    expect(
      within(first).getByText(
        "<script>synthetic text, not executable</script>",
      ),
    ).toBeVisible();
    expect(
      within(first)
        .getAllByText("a".repeat(64))
        .some((item) => item.closest("details")?.open),
    ).toBe(true);
    expect(container.querySelector("script")).toBeNull();
  });

  it("exposes the exact boolean availability citation separately from broader evidence", () => {
    render(<ClinicalDossierContent content={content([availability])} />);
    const region = observation("results-availability");
    fireEvent.click(
      within(region).getByText("Citations for results-availability"),
    );
    expect(within(region).getByText("Availability source")).toBeVisible();
    expect(within(region).getByText("false")).toBeVisible();
    expect(within(region).getByText("/record/hasResults")).toBeVisible();
  });

  it("distinguishes original assignment from the reported analysis and does not infer prespecification", () => {
    render(
      <ClinicalDossierContent
        content={content([
          design,
          {
            ...design,
            observation_id: "design-analysis",
            design_scope: "analysis_comparison",
            allocation: present("nonrandomized"),
            comparator_source: present("external"),
          },
          endpoint,
        ])}
      />,
    );
    expect(
      within(observation("design-assignment")).getByText(
        "Design · Trial assignment",
      ),
    ).toBeVisible();
    expect(
      within(observation("design-analysis")).getByText(
        "Design · Analysis comparison",
      ),
    ).toBeVisible();
    expect(
      within(observation("design-analysis")).getByText("Nonrandomized"),
    ).toBeVisible();
    const region = observation("endpoint-a");
    expect(within(region).getByText("Primary")).toBeVisible();
    const prespecification =
      within(region).getByText("Prespecification").parentElement!;
    expect(within(prespecification).getByText("Unresolved")).toBeVisible();
    expect(within(region).getByText("randomization")).toBeVisible();
  });

  it("renders fact and inference reconciliation without overwriting observations", () => {
    const data = content();
    (data.dossier as JsonObject).reconciliations = [
      {
        observation_ids: ["count-assigned", "endpoint-a"],
        relationship: "compatible_contexts",
        explanation: "Synthetic source explicitly connects these records.",
        kind: "fact",
        source_refs: [ref],
      },
      {
        observation_ids: ["count-assigned", "design-assignment"],
        relationship: "unresolved_difference",
        explanation: "A synthetic difference remains unresolved.",
        kind: "inference",
        inference_basis: "The retained records do not establish equivalence.",
        source_refs: [],
      },
    ];
    render(<ClinicalDossierContent content={data} />);
    expect(screen.getByText("Source-reported reconciliation")).toBeVisible();
    expect(screen.getByText("Inferred reconciliation")).toBeVisible();
    expect(
      screen.getByText("The retained records do not establish equivalence."),
    ).toBeVisible();
    expect(observation("count-assigned")).toBeVisible();
    expect(observation("endpoint-a")).toBeVisible();
  });

  it("renders malformed states, anchors and future kinds without invented values or crashes", () => {
    const data = content([
      {
        ...count,
        count: { state: "present" },
        group: { container: false, local_id: null },
        unit: { state: "unsupported" },
      },
      {
        ...endpoint,
        timeframe: { state: "source_absent", proof: null },
        prespecification: { state: "present", value: { unexpected: true } },
      },
      {
        observation_id: "future-record",
        kind: "future_kind",
        context_id: "missing-context",
      },
    ]);
    data.validation = {
      valid: false,
      failed_checks: [
        {
          code: "synthetic_invalid",
          message: "Synthetic record is malformed.",
          path: "/observations/0",
        },
      ],
    };
    render(<ClinicalDossierContent content={data} />);
    expect(
      screen.getByText("Structure and attribution checks need attention"),
    ).toBeVisible();
    expect(screen.getByText("Present value not recorded")).toBeVisible();
    expect(screen.getByText("Unrecognized field state")).toBeVisible();
    expect(
      screen.getByText("Present value has an unsupported shape"),
    ).toBeVisible();
    expect(
      screen.getAllByText("Exact source location not recorded.").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText("This observation kind is not supported by this view."),
    ).toBeVisible();
  });

  it("keeps source contexts and their exact versions inspectable", () => {
    render(<ClinicalDossierContent content={content([])} />);
    fireEvent.click(screen.getByText("First synthetic analysis"));
    expect(
      screen.getByText("Analysis identity: synthetic-analysis-a"),
    ).toBeVisible();
    const context = screen
      .getByText("First synthetic analysis")
      .closest("details")!;
    expect(within(context).getByText("/record/outcomes/0")).toBeVisible();
    fireEvent.click(within(context).getByText("Exact source version"));
    expect(within(context).getByText("a".repeat(64))).toBeVisible();
    expect(screen.getByText("No observations recorded.")).toBeVisible();
  });
});
