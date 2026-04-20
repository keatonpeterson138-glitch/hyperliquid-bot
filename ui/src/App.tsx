import { useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

const BACKEND_URL = "http://127.0.0.1:8787";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BACKEND_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: HealthResponse) => {
        if (!cancelled) setHealth(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="app">
      <header>
        <h1>Hyperliquid Bot</h1>
        <span className="version">v0.2.0 — Phase 0-B scaffold</span>
      </header>

      <section className="status">
        <h2>Backend status</h2>
        {health && (
          <pre className="status-ok">
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
        {error && (
          <pre className="status-err">
            Backend not reachable at {BACKEND_URL}: {error}
          </pre>
        )}
        {!health && !error && <p>Checking…</p>}
      </section>

      <section className="roadmap">
        <h2>Roadmap</h2>
        <p>
          See <code>internal_docs/OVERHAUL_PLAN.md</code> for the v1 architecture
          and <code>todo/path_to_v1.md</code> for phase-by-phase status.
        </p>
      </section>
    </main>
  );
}
