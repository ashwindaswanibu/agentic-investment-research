export interface Demo {
  schema_version: 1;
  synthetic: true;
  built_at: string;
  walkthroughs: {
    id: "instruments" | "forecasts";
    title: string;
    description: string;
    href: string;
  }[];
}

export function parseDemo(value: unknown): Demo {
  const fail = (): never => {
    throw new Error(
      "The demonstration manifest is invalid. Rebuild the demo package.",
    );
  };
  if (!value || typeof value !== "object") return fail();
  const data = value as Record<string, unknown>;
  if (
    data.schema_version !== 1 ||
    data.synthetic !== true ||
    typeof data.built_at !== "string" ||
    !Number.isFinite(Date.parse(data.built_at)) ||
    !Array.isArray(data.walkthroughs) ||
    data.walkthroughs.length !== 2
  )
    return fail();
  const seen = new Set();
  const walkthroughs = data.walkthroughs.map<Demo["walkthroughs"][number]>(
    (item) => {
      if (!item || typeof item !== "object") return fail();
      const row = item as Record<string, unknown>;
      if (
        (row.id !== "instruments" && row.id !== "forecasts") ||
        seen.has(row.id) ||
        typeof row.title !== "string" ||
        !row.title.trim() ||
        row.title.length > 200 ||
        typeof row.description !== "string" ||
        !row.description.trim() ||
        row.description.length > 2000 ||
        typeof row.href !== "string" ||
        !/^\/cases\/[a-f\d]{8}-(?:[a-f\d]{4}-){3}[a-f\d]{12}\?tab=(?:research|forecasts)$/.test(
          row.href,
        ) ||
        !row.href.endsWith(
          `tab=${row.id === "instruments" ? "research" : "forecasts"}`,
        )
      )
        return fail();
      seen.add(row.id);
      return {
        id: row.id,
        title: row.title,
        description: row.description,
        href: row.href,
      };
    },
  );
  return {
    schema_version: 1,
    synthetic: true,
    built_at: data.built_at,
    walkthroughs,
  };
}
