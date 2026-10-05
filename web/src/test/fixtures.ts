// Explicit test fixtures only. Production screens never import this module.
export const caseFixture = {
  id: "test-case",
  title: "Test fixture: hypothesis",
  hypothesis: "A test hypothesis with no claimed investment result.",
  workspace_id: "general",
  status: "draft",
  summary: null,
  tool_budget: 40,
  tool_calls_used: 0,
  created_at: "2026-10-05T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
};
export const capsFixture = {
  execution_mode: "paper",
  read_only: false,
  authenticated: true,
  authentication_required: false,
  provider: { name: "test", model: "test-provider", configured: true },
  sandbox: { available: false, reason: "Test environment" },
  worker: { last_seen_at: null, active: false },
  tools: [],
  limitations: [],
};
export const toolFixture = {
  id: "test-call",
  task_id: "test-task",
  call_id: "provider-call",
  name: "test_tool",
  arguments: { query: "test" },
  status: "completed",
  result: {
    ok: true,
    data: [{ value: "<script>alert('untrusted')</script>" }],
  },
  error: null,
  duration_ms: 42,
  started_at: "2026-10-05T10:00:00Z",
  finished_at: "2026-10-05T10:00:01Z",
};
export const artifactFixture = {
  id: "test-artifact",
  case_id: "test-case",
  task_id: "test-task",
  kind: "review",
  title: "Test review",
  content: {
    verdict: "rejected",
    findings: [
      { severity: "high", message: "The held-out comparison failed." },
    ],
    artifact_sha256: "a".repeat(64),
    artifact_id: "code-version",
    experiment_ids: ["experiment-version"],
  },
  sha256: "b".repeat(64),
  metadata: {},
  created_at: "2026-10-05T10:00:00Z",
};
