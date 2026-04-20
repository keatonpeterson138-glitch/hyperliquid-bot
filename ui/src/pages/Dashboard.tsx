import { useEffect, useState } from "react";

import { NewsPanel } from "../components/NewsPanel";
import { TickerBar } from "../components/TickerBar";
import { health, slots as slotsApi } from "../api/endpoints";
import { useStream } from "../hooks/useStream";
import type { HealthResponse, Slot, StreamEvent } from "../api/types";

export function Dashboard() {
  const [healthData, setHealthData] = useState<HealthResponse | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const { events, status } = useStream();

  useEffect(() => {
    health.get().then(setHealthData).catch(() => undefined);
    slotsApi.list().then(setSlots).catch(() => undefined);
    const id = setInterval(() => {
      slotsApi.list().then(setSlots).catch(() => undefined);
    }, 5_000);
    return () => clearInterval(id);
  }, []);

  const enabledCount = slots.filter((s) => s.enabled).length;

  return (
    <div className="page">
      <h1 className="page__title">Dashboard</h1>

      <section className="card ticker-card">
        <TickerBar symbols={["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB"]} />
      </section>

      <section className="card">
        <h2 className="card__title">Backend</h2>
        {healthData ? (
          <pre className="code">{JSON.stringify(healthData, null, 2)}</pre>
        ) : (
          <p>Connecting…</p>
        )}
      </section>

      <section className="card">
        <h2 className="card__title">Slots</h2>
        <div className="stats">
          <Stat label="Total" value={slots.length.toString()} />
          <Stat label="Enabled" value={enabledCount.toString()} />
          <Stat label="In position" value={slots.filter((s) => s.state?.current_position).length.toString()} />
        </div>
      </section>

      <section className="card">
        <NewsPanel />
      </section>

      <section className="card">
        <h2 className="card__title">
          Live event stream <span className="badge">{status}</span>
        </h2>
        <p className="muted">Last 10 events from the trading backend.</p>
        <ul className="events">
          {events.slice(-10).reverse().map((e: StreamEvent, i) => (
            <li key={`${e.ts}-${i}`} className="event">
              <span className="event__ts">{e.ts}</span>
              <span className="event__type">{e.type}</span>
              <span className="event__detail">{summarize(e)}</span>
            </li>
          ))}
          {events.length === 0 && <li className="muted">No events yet.</li>}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </div>
  );
}

function summarize(e: StreamEvent): string {
  const exclude = new Set(["ts", "type"]);
  const parts: string[] = [];
  for (const [k, v] of Object.entries(e)) {
    if (exclude.has(k)) continue;
    parts.push(`${k}=${typeof v === "object" ? JSON.stringify(v) : v}`);
  }
  return parts.join(" ");
}
