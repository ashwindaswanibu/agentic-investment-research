// Synthetic engineering fixtures only. Never imported by production components.
export const mandateValues = {
  name: "Synthetic test mandate",
  symbols: "TEST, EXAMPLE",
  max_symbol_weight: "0.25",
  max_order_notional: "1250.50",
  max_quote_age_seconds: "30",
  fee_bps: "1.5",
  max_open_orders: "3",
  order_ttl_seconds: "300",
  max_decision_age_seconds: "900",
  poll_interval_seconds: "15",
  max_drawdown_amount: "125.00",
  expires_at: "2040-01-01T12:00",
};
export const mandateFixture = {
  id: "test-mandate",
  sha256: "d".repeat(64),
  created_at: "2026-10-06T12:00:00Z",
  payload: {
    name: "Synthetic test mandate",
    allowed_symbols: ["TEST", "EXAMPLE"],
    policy: {
      max_symbol_weight: "0.25",
      max_order_notional: "1250.50",
      max_quote_age_seconds: 30,
      fee_bps: "1.5",
    },
    max_open_orders: 3,
    order_ttl_seconds: 300,
    max_decision_age_seconds: 900,
    poll_interval_seconds: 15,
    max_drawdown_amount: "125.00",
    expires_at: "2040-01-01T12:00:00Z",
  },
};
export const operationsFixture = {
  control: { version: 3, mode: "halted", mandate_id: "test-mandate" },
  mandate: mandateFixture,
  mandates: [mandateFixture],
  feed: {
    provider: "synthetic-test",
    configured: false,
    reason: "No feed in this test fixture.",
  },
  worker: { active: false, last_seen_at: null },
  latest_observation: null,
  latest_tick: null,
  drawdown: { peak_equity: null, tripped: false },
  performance: { equity_series: [], daily: [], latest: null },
  limitations: ["Synthetic fixture only."],
};
