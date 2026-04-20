// Analog / pattern search. Pick a symbol + interval + window params,
// hit Run, see the top-K historical windows that look like now plus the
// forward-return distribution (what happened next, on average, in the
// bars after each match).

import { useState } from "react";

import { api } from "../api/client";

interface AnalogMatch {
  symbol: string;
  start_ts: string;
  end_ts: string;
  distance: number;
  forward_return: number | null;
}

interface AnalogResult {
  query_symbol: string;
  window_len: number;
  forward_bars: number;
  query_window: number[];
  matches: AnalogMatch[];
  forward_distribution: Record<string, number>;
}

export function AnalogPage() {
  const [symbol, setSymbol] = useState("BTC");
  const [interval, setInterval] = useState("1h");
  const [windowLen, setWindowLen] = useState(40);
  const [forwardBars, setForwardBars] = useState(20);
  const [topK, setTopK] = useState(20);
  const [scope, setScope] = useState<"symbol" | "universe">("symbol");
  const [scopeSymbols, setScopeSymbols] = useState("BTC,ETH,SOL,HYPE,AVAX,ARB");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalogResult | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const to = new Date();
      const from = new Date(to.getTime() - 365 * 2 * 24 * 3_600_000);
      // Query window ends ~ (windowLen + forwardBars) bars before now so
      // the forward window falls inside history.
      const queryEnd = new Date(to.getTime() - forwardBars * 3_600_000);
      const scopes =
        scope === "universe"
          ? scopeSymbols.split(",").map((s) => s.trim()).filter(Boolean)
          : [symbol];
      const r = await api.post<AnalogResult>("/analog/query", {
        symbol,
        interval,
        from_ts: from.toISOString(),
        to_ts: to.toISOString(),
        query_end_ts: queryEnd.toISOString(),
        window_len: windowLen,
        forward_bars: forwardBars,
        top_k: topK,
        scope_symbols: scopes,
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="page">
      <h1 className="page__title">Analog Search</h1>

      <section className="card">
        <h2 className="card__title">Query</h2>
        <div className="chart-toolbar">
          <Field label="Symbol"><input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></Field>
          <Field label="Interval"><input value={interval} onChange={(e) => setInterval(e.target.value)} /></Field>
          <Field label="Window bars"><input type="number" value={windowLen} onChange={(e) => setWindowLen(Number(e.target.value))} /></Field>
          <Field label="Forward bars"><input type="number" value={forwardBars} onChange={(e) => setForwardBars(Number(e.target.value))} /></Field>
          <Field label="Top K"><input type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></Field>
        </div>
        <div className="chart-toolbar">
          <Field label="Scope">
            <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
              <option value="symbol">Single symbol</option>
              <option value="universe">Multi-symbol</option>
            </select>
          </Field>
          {scope === "universe" && (
            <Field label="Scope symbols">
              <input value={scopeSymbols} onChange={(e) => setScopeSymbols(e.target.value)} />
            </Field>
          )}
          <button onClick={run} disabled={running}>{running ? "Searching…" : "Find matches"}</button>
        </div>
        {error && <div className="error small">{error}</div>}
        <p className="muted small">
          Uses DTW with LB_Keogh pruning over z-scored closes. "Forward return"
          is the cumulative return over the next {forwardBars} bars after each
          match, aggregated across the top-K to show what happened next.
        </p>
      </section>

      {result && <AnalogResultView result={result} />}
    </div>
  );
}

function AnalogResultView({ result }: { result: AnalogResult }) {
  const dist = result.forward_distribution;
  return (
    <>
      <section className="card">
        <h2 className="card__title">Forward-return distribution ({Math.round(dist.n ?? 0)} matches)</h2>
        {Object.keys(dist).length === 0 ? (
          <p className="muted">No matches.</p>
        ) : (
          <div className="outcome-header__stats">
            <Stat label="P5" value={fmtPct(dist.p05)} tone={tone(dist.p05)} />
            <Stat label="P25" value={fmtPct(dist.p25)} tone={tone(dist.p25)} />
            <Stat label="Median" value={fmtPct(dist.p50)} tone={tone(dist.p50)} />
            <Stat label="P75" value={fmtPct(dist.p75)} tone={tone(dist.p75)} />
            <Stat label="P95" value={fmtPct(dist.p95)} tone={tone(dist.p95)} />
            <Stat label="Mean" value={fmtPct(dist.mean)} tone={tone(dist.mean)} />
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="card__title">Top {result.matches.length} matches</h2>
        {result.matches.length === 0 ? (
          <p className="muted">No matches found — try widening the scope or reducing window length.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th><th>Window start</th><th>Window end</th>
                <th>DTW distance</th><th>Forward return</th>
              </tr>
            </thead>
            <tbody>
              {result.matches.map((m, i) => (
                <tr key={i}>
                  <td>{m.symbol}</td>
                  <td className="muted small">{m.start_ts.slice(0, 16).replace("T", " ")}</td>
                  <td className="muted small">{m.end_ts.slice(0, 16).replace("T", " ")}</td>
                  <td>{m.distance.toFixed(3)}</td>
                  <td className={tone(m.forward_return) ? `tone--${tone(m.forward_return)}` : ""}>
                    {fmtPct(m.forward_return)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className={`stat-inline__value ${tone ? `tone--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
}
function tone(v: number | null | undefined): "pos" | "neg" | undefined {
  if (v === null || v === undefined || !Number.isFinite(v)) return undefined;
  return v > 0 ? "pos" : v < 0 ? "neg" : undefined;
}
