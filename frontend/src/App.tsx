import { useEffect, useState } from "react";
import { fetchHealth } from "./api";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok" }
  | { kind: "db-down" }
  | { kind: "unreachable" };

const MESSAGES: Record<HealthState["kind"], string> = {
  loading: "Checking backend…",
  ok: "Backend: ok · Database: ok",
  "db-down": "Backend is up, but the database is unavailable.",
  unreachable: "Backend is unreachable.",
};

export default function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((h) => setHealth({ kind: h.db === "ok" ? "ok" : "db-down" }))
      .catch(() => {
        if (!controller.signal.aborted) setHealth({ kind: "unreachable" });
      });
    return () => controller.abort();
  }, []);

  const state = health.kind === "ok" ? "ok" : health.kind === "loading" ? "loading" : "error";
  return (
    <main>
      <h1>Event Registration</h1>
      <p className="status" role="status" data-state={state}>
        {MESSAGES[health.kind]}
      </p>
    </main>
  );
}
