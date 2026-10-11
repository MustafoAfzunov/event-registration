// Single place for talking to the backend. All calls use relative /api URLs; nginx (compose)
// or the Vite dev proxy forwards them to the backend container.

export type Health = { status: "ok" | "degraded"; db: "ok" | "error" };

/** GET /api/health. Resolves for 200 and 503 (both carry a body); rejects if unreachable. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal, headers: { Accept: "application/json" } });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected status ${response.status}`);
  }
  return (await response.json()) as Health;
}
