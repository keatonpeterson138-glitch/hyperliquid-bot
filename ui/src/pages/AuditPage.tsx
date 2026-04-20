import { useEffect, useState } from "react";

import { BACKEND_URL } from "../api/client";
import { api } from "../api/client";

interface AuditEvent {
  id: number;
  ts: string;
  event_type: string;
  source: string;
  symbol: string | null;
  slot_id: string | null;
  reason: string | null;
}

interface AuditResponse {
  total: number;
  events: AuditEvent[];
}

export function AuditPage() {
  const [data, setData] = useState<AuditResponse | null>(null);
  const [filter, setFilter] = useState("");

  const refresh = () =>
    api
      .get<AuditResponse>("/audit?limit=200")
      .then(setData)
      .catch(() => undefined);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, []);

  const events = data?.events ?? [];
  const filtered = filter
    ? events.filter((e) =>
        [e.event_type, e.symbol, e.reason, e.source]
          .filter(Boolean)
          .some((v) => (v as string).toLowerCase().includes(filter.toLowerCase())),
      )
    : events;

  return (
    <div className="page">
      <h1 className="page__title">Audit log</h1>
      <section className="toolbar">
        <input
          className="filter"
          placeholder="Filter by event/symbol/reason…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <a className="button-link" href={`${BACKEND_URL}/audit.csv`}>
          Export CSV
        </a>
        <span className="muted">
          {filtered.length} of {data?.total ?? 0}
        </span>
      </section>
      <section className="card">
        <table className="table">
          <thead>
            <tr>
              <th>ts</th>
              <th>type</th>
              <th>source</th>
              <th>symbol</th>
              <th>slot</th>
              <th>reason</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id}>
                <td className="small">{e.ts}</td>
                <td>{e.event_type}</td>
                <td>{e.source}</td>
                <td>{e.symbol ?? "—"}</td>
                <td className="small">{e.slot_id ?? "—"}</td>
                <td>{e.reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 ? <p className="muted">No events.</p> : null}
      </section>
    </div>
  );
}
