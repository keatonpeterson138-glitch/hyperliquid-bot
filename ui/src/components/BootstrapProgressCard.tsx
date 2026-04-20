// Dashboard card showing macro-seed progress.
// Auto-polls /bootstrap/status every 2s while running. Hides entirely
// once the lake is fully seeded to avoid cluttering the dashboard.

import { useEffect, useState } from "react";

import { bootstrap } from "../api/endpoints";
import type { BootstrapStatus } from "../api/endpoints";

export function BootstrapProgressCard() {
  const [status, setStatus] = useState<BootstrapStatus | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await bootstrap.status();
        if (cancelled) return;
        setStatus(s);
        // Hide once fully complete and nothing is in flight.
        if (!s.running && s.total > 0 && s.done >= s.total) {
          // keep showing for ~30s after completion then hide
          setTimeout(() => !cancelled && setHidden(true), 30_000);
        }
      } catch {
        /* transient — keep polling */
      }
    };
    void tick();
    const id = window.setInterval(tick, 2_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  if (hidden || !status || status.total === 0) return null;

  const pct = status.total > 0 ? (status.done / status.total) * 100 : 0;

  return (
    <section className="card">
      <div className="outcome-header">
        <div>
          <h2 className="card__title">
            {status.running
              ? "Loading historical data…"
              : status.done >= status.total
                ? "Historical data loaded"
                : "Historical data seed paused"}
          </h2>
          <div className="muted small">
            Auto-pull of S&P 500, Nasdaq, WTI, Gold, Silver, DXY, BTC/ETH/SOL
            majors. Runs in the background; no action needed.
          </div>
        </div>
        <div className="outcome-header__stats">
          <Stat label="Done" value={`${status.done}/${status.total}`} />
          {status.errors > 0 && <Stat label="Errors" value={String(status.errors)} tone="neg" />}
          <Stat label="Rows" value={status.rows_total.toLocaleString()} />
        </div>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {status.current && (
        <div className="muted small">Now fetching: {status.current}</div>
      )}
      {status.errors_detail.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary className="muted small">{status.errors} error(s)</summary>
          <ul className="muted small">
            {status.errors_detail.map((e, i) => (
              <li key={i}>
                {e.symbol} {e.interval}: {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className={`stat-inline__value ${tone ? `tone--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
