// Research Workbench - pick a study, fill its inputs, run, render.
// Schema comes from /research (list) and results from /research/run.
// Results render as table + summary; chart specs are displayed but not
// drawn yet (the Vega-lite renderer lands in Phase 13 backlog).

import { useEffect, useState } from "react";

import { api } from "../api/client";

interface StudyInfo {
  name: string;
  description: string;
}

interface ChartSpec {
  kind: string;
  title: string;
  x: string;
  y: string | string[];
  meta: Record<string, unknown>;
}

interface StudyResult {
  study: string;
  inputs: Record<string, unknown>;
  summary_md: string;
  columns: string[];
  rows: unknown[][];
  charts: ChartSpec[];
  extras: Record<string, unknown>;
}

// Input field suggestions per study - keeps UX navigable even without a
// per-study schema registry.
const STUDY_INPUTS: Record<string, Array<{ key: string; type: "text" | "number" | "date" | "csv"; placeholder?: string; defaultVal?: string }>> = {
  correlation_matrix: [
    { key: "symbols", type: "csv", placeholder: "BTC,ETH,SOL,HYPE", defaultVal: "BTC,ETH,SOL,HYPE" },
    { key: "interval", type: "text", defaultVal: "1h" },
    { key: "from_ts", type: "date" },
    { key: "to_ts", type: "date" },
  ],
  seasonality_heatmap: [
    { key: "symbol", type: "text", defaultVal: "BTC" },
    { key: "interval", type: "text", defaultVal: "1h" },
    { key: "from_ts", type: "date" },
    { key: "to_ts", type: "date" },
  ],
  volatility_regime: [
    { key: "symbol", type: "text", defaultVal: "BTC" },
    { key: "interval", type: "text", defaultVal: "1h" },
    { key: "window", type: "number", defaultVal: "24" },
    { key: "from_ts", type: "date" },
    { key: "to_ts", type: "date" },
  ],
  returns_summary: [
    { key: "symbol", type: "text", defaultVal: "BTC" },
    { key: "interval", type: "text", defaultVal: "1h" },
    { key: "from_ts", type: "date" },
    { key: "to_ts", type: "date" },
  ],
  event_study: [
    { key: "symbol", type: "text", defaultVal: "BTC" },
    { key: "interval", type: "text", defaultVal: "1h" },
    { key: "window", type: "number", defaultVal: "12" },
    { key: "events", type: "csv", placeholder: "2025-01-20T00:00:00, 2025-03-01T00:00:00" },
    { key: "from_ts", type: "date" },
    { key: "to_ts", type: "date" },
  ],
};

const defaultDates = () => {
  const to = new Date();
  const from = new Date(to.getTime() - 180 * 24 * 3_600_000);
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
};

export function ResearchPage() {
  const [studies, setStudies] = useState<StudyInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StudyResult | null>(null);

  useEffect(() => {
    api
      .get<StudyInfo[]>("/research")
      .then((list) => {
        setStudies(list);
        if (list.length > 0) setSelected(list[0].name);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    const fields = STUDY_INPUTS[selected] ?? [];
    const dates = defaultDates();
    const defaults: Record<string, string> = {};
    for (const f of fields) {
      defaults[f.key] =
        f.defaultVal ??
        (f.type === "date" ? (f.key === "to_ts" ? dates.to : dates.from) : "");
    }
    setInputs(defaults);
    setResult(null);
  }, [selected]);

  const run = async () => {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      const fields = STUDY_INPUTS[selected] ?? [];
      const payload: Record<string, unknown> = {};
      for (const f of fields) {
        const raw = inputs[f.key] ?? "";
        if (f.type === "csv") payload[f.key] = raw.split(",").map((s) => s.trim()).filter(Boolean);
        else if (f.type === "number") payload[f.key] = Number(raw);
        else if (f.type === "date") payload[f.key] = raw ? `${raw}T00:00:00` : null;
        else payload[f.key] = raw;
      }
      const r = await api.post<StudyResult>("/research/run", {
        study: selected,
        inputs: payload,
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const selectedInfo = studies.find((s) => s.name === selected);
  const fields = selected ? STUDY_INPUTS[selected] ?? [] : [];

  return (
    <div className="page">
      <h1 className="page__title">Research</h1>

      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <h2 className="card__title">Studies</h2>
          {error && <div className="error small">{error}</div>}
          {studies.length === 0 ? (
            <p className="muted">No studies available.</p>
          ) : (
            <ul className="market-list">
              {studies.map((s) => (
                <li
                  key={s.name}
                  className={`market-list__item ${s.name === selected ? "is-selected" : ""}`}
                >
                  <button onClick={() => setSelected(s.name)}>
                    <span className="market-list__sym">{s.name}</span>
                    <span className="market-list__meta muted small">{s.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          {!selected ? (
            <div className="card"><p className="muted">Pick a study on the left.</p></div>
          ) : (
            <>
              <section className="card">
                <h2 className="card__title">{selected}</h2>
                <p className="muted small">{selectedInfo?.description}</p>
                <div className="settings-grid">
                  {fields.map((f) => (
                    <div key={f.key} className="settings-row">
                      <label className="settings-row__label">{f.key}</label>
                      <div className="settings-row__control">
                        <input
                          type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
                          value={inputs[f.key] ?? ""}
                          placeholder={f.placeholder}
                          onChange={(e) => setInputs({ ...inputs, [f.key]: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="chart-toolbar">
                  <button onClick={run} disabled={running}>
                    {running ? "Running…" : "Run study"}
                  </button>
                </div>
              </section>

              {result && <StudyResultView result={result} />}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function StudyResultView({ result }: { result: StudyResult }) {
  const maxRows = 200;
  return (
    <>
      <section className="card">
        <h3 className="card__title">Result</h3>
        <p>{result.summary_md}</p>
        {result.charts.length > 0 && (
          <div className="muted small">
            Chart specs: {result.charts.map((c) => `${c.kind} (${c.title})`).join(", ")}
          </div>
        )}
      </section>

      <section className="card">
        <h3 className="card__title">
          Data ({result.rows.length} row{result.rows.length === 1 ? "" : "s"})
          {result.rows.length > maxRows ? ` — showing first ${maxRows}` : ""}
        </h3>
        <div style={{ maxHeight: 500, overflow: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                {result.columns.map((c) => <th key={c}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {result.rows.slice(0, maxRows).map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{fmtCell(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return String(v);
    if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return v.toFixed(4);
  }
  return String(v);
}
