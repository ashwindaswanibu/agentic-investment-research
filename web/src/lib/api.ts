export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  parse: (value: unknown) => T,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    cache: "no-store",
    headers: { Accept: "application/json", ...options.headers },
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(
      "The research API returned an unreadable response.",
      "invalid_response",
      response.status,
    );
  }
  if (!response.ok) {
    const error =
      body && typeof body === "object" && "error" in body ? body.error : null;
    const detail =
      error && typeof error === "object"
        ? (error as Record<string, unknown>)
        : {};
    throw new ApiError(
      typeof detail.message === "string"
        ? detail.message
        : `Request failed (${response.status}).`,
      typeof detail.code === "string" ? detail.code : "request_failed",
      response.status,
    );
  }
  return parse(body);
}

export function mutate<T>(
  path: string,
  body: unknown,
  parse: (value: unknown) => T,
  idempotencyKey: string,
): Promise<T> {
  return request(path, parse, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}
export function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "An unexpected error occurred.";
}
