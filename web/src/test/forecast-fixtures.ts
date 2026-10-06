// Explicit synthetic fixtures; never imported by production screens.
import { parseArtifact } from "@/lib/contracts";
import { artifactFixture } from "./fixtures";

export const forecastEvidence = parseArtifact({
  ...artifactFixture,
  id: "evidence-1",
  kind: "evidence",
  title: "Synthetic source publication",
  content: { text: "The event occurred." },
  metadata: { synthetic: true },
});
export const forecastHypothesis = parseArtifact({
  ...artifactFixture,
  id: "hypothesis-1",
  kind: "hypothesis",
  title: "Synthetic event hypothesis",
  content: { statement: "A synthetic event may occur." },
});
export const forecastNote = parseArtifact({
  ...artifactFixture,
  id: "note-1",
  kind: "note",
  title: "Synthetic research note",
  content: "Research notes",
});
export const receipt = (artifact: ReturnType<typeof parseArtifact>) => ({
  id: artifact.id,
  sha256: artifact.sha256,
  kind: artifact.kind,
  title: artifact.title,
});
export function forecastFixture(id = "forecast-1", status = "due") {
  return {
    forecast: {
      ...artifactFixture,
      id,
      kind: "forecast",
      title: `Synthetic question ${id}`,
      content: {
        question: `Will synthetic event ${id} occur?`,
        hypothesis: receipt(forecastHypothesis),
        registered_at: "2020-01-01T00:00:00Z",
        opens_at: "2020-02-01T00:00:00Z",
        closes_at:
          status === "pending"
            ? "2099-03-01T00:00:00Z"
            : "2020-03-01T00:00:00Z",
        yes_rule: "The designated source confirms the event.",
        no_rule: "The source confirms no event during the window.",
        unresolvable_rule: "The designated source is unavailable or ambiguous.",
        resolution_source: "The saved source publication.",
        status: status === "abstained" ? "abstain" : "forecast",
        probability: status === "abstained" ? null : 0.7,
        abstention_reason:
          status === "abstained"
            ? "Insufficient evidence to justify a probability."
            : null,
        baseline_probability: 0.5,
        baseline_rationale: "Explicit neutral comparison.",
        source_refs: [receipt(forecastEvidence)],
        synthetic: true,
      },
    },
    resolutions: [] as ReturnType<typeof resolutionFixture>[],
    latest_resolution: null as ReturnType<typeof resolutionFixture> | null,
    assessment: {
      status,
      scored: false,
      brier: null as number | null,
      baseline_brier: null as number | null,
      improvement: null as number | null,
    },
  };
}
export function resolutionFixture(
  id = "resolution-1",
  previous: string | null = null,
) {
  return {
    ...artifactFixture,
    id,
    kind: "forecast_resolution",
    title: `Synthetic operator resolution ${id}`,
    content: {
      outcome: "yes",
      rationale: `Operator judgment ${id}: the event is stated in the source.`,
      source_refs: [
        {
          artifact_id: forecastEvidence.id,
          artifact_sha256: forecastEvidence.sha256,
          excerpt: "The event occurred.",
          source_path: "/text",
        },
      ],
      recorded_at: "2020-03-02T00:00:00Z",
      previous_resolution_id: previous,
      synthetic: true,
    },
  };
}
