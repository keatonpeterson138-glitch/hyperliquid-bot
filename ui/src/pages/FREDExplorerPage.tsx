// FRED Explorer — browse + chart every Federal Reserve economic series.
//
// Left rail: popular series (rates / inflation / labor / liquidity / etc.)
// + free-text search against FRED's catalog (fred.stlouisfed.org has
// ~800k series indexed).
// Right: line chart of the selected series, with date-range picker.
//
// Requires a free FRED API key — Sidebar -> API Keys -> provider 'fred'.

import {
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fred } from "../api/endpoints";
import type { FREDObservation, FREDSeriesInfo } from "../api/endpoints";

export function FREDExplorerPage() {
  const [popular, setPopular] = useState<FREDSeriesInfo[]>([]);
  const [searchResults, setSearchResults] = useState<FREDSeriesInfo[]>([]);
  const [selected, setSelected] = useState<FREDSeriesInfo | null>(null);
  const [query, setQuery] = useState("");
  const [observations, setObservations] = useState<FREDObservation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromTs, setFromTs] = useState(() =>
    new Date(Date.now() - 20 * 365 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [toTs, setToTs] = useState(() => new Date().toISOString().slice(0, 10));

  useEffect(() => {
    fred.popular().then(setPopular).catch((e) => setError((e as Error).message));
  }, []);

  const runSearch = useCallback(async () => {
    if (query.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    try {
      const r = await fred.search(query.trim(), 30);
      setSearchResults(r);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [query]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fred
      .series(selected.id, `${fromTs}T00:00:00Z`, `${toTs}T23:59:59Z`)
      .then((r) => !cancelled && setObservations(r.observations))
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selected?.id, fromTs, toTs]);

  const listed = searchResults.length > 0 ? searchResults : popular;

  return (
    <div className="page">
      <h1 className="page__title">FRED Explorer</h1>
      <p className="muted small">
        Federal Reserve Economic Data — 800k+ series including Fed funds rate,
        CPI, unemployment, GDP, VIX, balance sheet. Needs a free API key from{" "}
        <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noreferrer">
          fred.stlouisfed.org
        </a>
        . Add it under <a href="/apikeys">API Keys</a> → provider <code>fred</code>.
      </p>

      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <h2 className="card__title">Series</h2>
          <div className="chart-toolbar">
            <input
              value={query}
              placeholder="search (e.g. mortgage rate, oil, jobless)"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              style={{ flex: 1 }}
            />
            <button onClick={runSearch}>Search</button>
            {searchResults.length > 0 && (
              <button onClick={() => { setSearchResults([]); setQuery(""); }}>Clear</button>
            )}
          </div>
          {error && <div className="error small">{error}</div>}
          <ul className="market-list" style={{ maxHeight: "calc(100vh - 280px)", overflow: "auto" }}>
            {listed.map((s) => (
              <li
                key={s.id}
                className={`market-list__item ${selected?.id === s.id ? "is-selected" : ""}`}
              >
                <button onClick={() => setSelected(s)}>
                  <span className="market-list__sym">{s.id}</span>
                  <span className="market-list__meta muted small">
                    {s.name}
                    {s.category ? ` · ${s.category}` : ""}
                    {s.frequency ? ` · ${s.frequency}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="outcomes-detail">
          {!selected ? (
            <div className="card"><p className="muted">Pick a series on the left.</p></div>
          ) : (
            <>
              <section className="card">
                <div className="outcome-header">
                  <div>
                    <h2 className="card__title">{selected.id}</h2>
                    <div className="muted small">
                      {selected.name}
                      {selected.units ? ` · ${selected.units}` : ""}
                      {selected.frequency ? ` · ${selected.frequency}` : ""}
                    </div>
                  </div>
                  <div className="outcome-header__stats">
                    {observations.length > 0 && (
                      <>
                        <Stat label="Latest" value={observations[observations.length - 1].value.toFixed(4)} />
                        <Stat label="Observations" value={String(observations.length)} />
                      </>
                    )}
                  </div>
                </div>
                <div className="chart-toolbar">
                  <label className="field">
                    <span>From</span>
                    <input type="date" value={fromTs} onChange={(e) => setFromTs(e.target.value)} />
                  </label>
                  <label className="field">
                    <span>To</span>
                    <input type="date" value={toTs} onChange={(e) => setToTs(e.target.value)} />
                  </label>
                  {loading && <span className="muted small">Loading…</span>}
                </div>
              </section>
              <section className="card">
                <h3 className="card__title">Chart</h3>
                <FREDChart observations={observations} />
              </section>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function FREDChart({ observations }: { observations: FREDObservation[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const chart = createChart(c, {
      width: c.clientWidth,
      height: 380,
      layout: { background: { color: "#0d1117" }, textColor: "#e6edf3" },
      grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
      timeScale: { timeVisible: false, borderColor: "#30363d" },
      rightPriceScale: { borderColor: "#30363d" },
    });
    const s = chart.addSeries(LineSeries, { color: "#58a6ff", lineWidth: 2 });
    chartRef.current = chart;
    seriesRef.current = s;
    const ro = new ResizeObserver(() => chart.applyOptions({ width: c.clientWidth, height: 380 }));
    ro.observe(c);
    return () => { ro.disconnect(); chart.remove(); };
  }, []);

  const data: LineData[] = useMemo(() =>
    observations.map((o) => ({
      time: (Math.floor(new Date(o.timestamp).getTime() / 1000) as unknown) as Time,
      value: o.value,
    })), [observations]);

  useEffect(() => {
    seriesRef.current?.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={ref} className="chart-container" />;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className="stat-inline__value">{value}</div>
    </div>
  );
}
