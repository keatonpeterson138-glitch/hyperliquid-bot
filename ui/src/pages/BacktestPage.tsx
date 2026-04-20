// Backtest Lab — run a strategy against historical candles, visualise
// the equity curve, inspect metrics + trades. Results persist in the
// server-side BacktestRegistry so revisiting a run_id replays cached
// data without re-simulating.

import {
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";

interface BacktestResponse {
  run_id: string;
  symbol: string;
  interval: string;
  strategy: string;
  config: Record<string, unknown>;
  starting_cash: number;
  ending_equity: number;
  metrics: Record<string, number>;
  trades: Array<{
    entered_at: string;
    exited_at: string;
    symbol: string;
    side: string;
    size_usd: number;
    entry_price: number;
    exit_price: number;
    pnl_usd: number;
    hold_bars: number;
    reason: string;
  }>;
  equity_curve: Array<{ timestamp: string; equity: number; cash: number }>;
}

const STRATEGIES = [
  "ema_crossover",
  "rsi_mean_reversion",
  "breakout",
  "funding_dip",
];
const INTERVALS = ["5m", "15m", "30m", "1h", "4h", "1d"];

const METRIC_GROUPS: Array<[string, string[]]> = [
  ["Returns", ["total_return_pct", "cagr", "ending_equity_usd"]],
  ["Risk", ["sharpe", "sortino", "calmar", "max_dd_pct"]],
  ["Trades", ["trade_count", "win_rate", "profit_factor", "expectancy_usd", "avg_win_usd", "avg_loss_usd", "max_consec_losses", "avg_hold_bars", "pct_in_market"]],
];

export function BacktestPage() {
  const [symbol, setSymbol] = useState("BTC");
  const [interval, setInterval] = useState("1h");
  const [strategy, setStrategy] = useState("ema_crossover");
  const [sizeUsd, setSizeUsd] = useState(100);
  const [leverage, setLeverage] = useState(1);
  const [slPct, setSlPct] = useState<number | "">(0.02);
  const [tpPct, setTpPct] = useState<number | "">(0.05);
  const [fromTs, setFromTs] = useState(() =>
    new Date(Date.now() - 90 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [toTs, setToTs] = useState(() => new Date().toISOString().slice(0, 10));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [history, setHistory] = useState<BacktestResponse[]>([]);

  useEffect(() => {
    api
      .get<BacktestResponse[]>("/backtest")
      .then(setHistory)
      .catch(() => undefined);
  }, [result]);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await api.post<BacktestResponse>("/backtest", {
        symbol,
        interval,
        strategy,
        from_ts: new Date(fromTs + "T00:00:00Z").toISOString(),
        to_ts: new Date(toTs + "T23:59:59Z").toISOString(),
        size_usd: sizeUsd,
        leverage,
        stop_loss_pct: slPct === "" ? null : slPct,
        take_profit_pct: tpPct === "" ? null : tpPct,
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
      <h1 className="page__title">Backtest Lab</h1>

      <section className="card">
        <h2 className="card__title">Configure</h2>
        <div className="chart-toolbar">
          <Field label="Symbol"><input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></Field>
          <Field label="Interval">
            <select value={interval} onChange={(e) => setInterval(e.target.value)}>
              {INTERVALS.map((i) => <option key={i}>{i}</option>)}
            </select>
          </Field>
          <Field label="Strategy">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {STRATEGIES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="From"><input type="date" value={fromTs} onChange={(e) => setFromTs(e.target.value)} /></Field>
          <Field label="To"><input type="date" value={toTs} onChange={(e) => setToTs(e.target.value)} /></Field>
        </div>
        <div className="chart-toolbar">
          <Field label="Size USD"><input type="number" value={sizeUsd} onChange={(e) => setSizeUsd(Number(e.target.value))} /></Field>
          <Field label="Leverage"><input type="number" value={leverage} onChange={(e) => setLeverage(Number(e.target.value))} /></Field>
          <Field label="Stop-loss %"><input type="number" step="0.005" value={slPct} onChange={(e) => setSlPct(e.target.value === "" ? "" : Number(e.target.value))} /></Field>
          <Field label="Take-profit %"><input type="number" step="0.005" value={tpPct} onChange={(e) => setTpPct(e.target.value === "" ? "" : Number(e.target.value))} /></Field>
          <button onClick={run} disabled={running}>{running ? "Running…" : "Run backtest"}</button>
        </div>
        {error && <div className="error small">{error}</div>}
      </section>

      {result && <BacktestResultView result={result} />}

      <section className="card">
        <h2 className="card__title">Recent runs ({history.length})</h2>
        {history.length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th><th>Symbol</th><th>Strategy</th><th>Trades</th>
                <th>Return %</th><th>Sharpe</th><th>Max DD %</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.run_id} onClick={() => setResult(h)} style={{ cursor: "pointer" }}>
                  <td className="muted small">{h.run_id.slice(0, 10)}</td>
                  <td>{h.symbol}</td>
                  <td>{h.strategy}</td>
                  <td>{h.metrics.trade_count}</td>
                  <td className={toneClass(h.metrics.total_return_pct)}>{fmt(h.metrics.total_return_pct, 2)}</td>
                  <td>{fmt(h.metrics.sharpe, 2)}</td>
                  <td className="tone--neg">{fmt(h.metrics.max_dd_pct, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function BacktestResultView({ result }: { result: BacktestResponse }) {
  const points: LineData[] = useMemo(() => {
    const arr = result.equity_curve.map((p) => ({
      time: (Math.floor(new Date(p.timestamp).getTime() / 1000) as unknown) as Time,
      value: p.equity,
    }));
    // dedupe on time (lightweight-charts requires unique ascending time)
    const seen = new Set<number>();
    return arr.filter((p) => {
      const t = p.time as unknown as number;
      if (seen.has(t)) return false;
      seen.add(t);
      return true;
    });
  }, [result.equity_curve]);

  return (
    <>
      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">{result.symbol} · {result.strategy} · {result.interval}</h2>
            <div className="muted small">run_id {result.run_id}</div>
          </div>
          <div className="outcome-header__stats">
            <Stat label="Starting" value={fmtUSD(result.starting_cash)} />
            <Stat label="Ending" value={fmtUSD(result.ending_equity)} />
            <Stat
              label="Return"
              value={`${fmt(result.metrics.total_return_pct, 2)}%`}
              tone={result.metrics.total_return_pct >= 0 ? "pos" : "neg"}
            />
            <Stat label="Trades" value={String(result.metrics.trade_count)} />
            <Stat label="Sharpe" value={fmt(result.metrics.sharpe, 2)} />
            <Stat label="Max DD" value={`${fmt(result.metrics.max_dd_pct, 2)}%`} tone="neg" />
          </div>
        </div>
      </section>

      <section className="card">
        <h3 className="card__title">Equity curve</h3>
        <EquityChart points={points} />
      </section>

      <section className="card">
        <h3 className="card__title">Metrics</h3>
        <div className="metrics-grid">
          {METRIC_GROUPS.map(([group, keys]) => (
            <div key={group}>
              <h4 className="card__title">{group}</h4>
              <table className="table">
                <tbody>
                  {keys.map((k) => (
                    <tr key={k}>
                      <td className="muted small">{k}</td>
                      <td>{fmt(result.metrics[k] ?? 0, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h3 className="card__title">Trades ({result.trades.length})</h3>
        {result.trades.length === 0 ? (
          <p className="muted">No completed trades — strategy held throughout.</p>
        ) : (
          <div style={{ maxHeight: 400, overflow: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Entered</th><th>Side</th><th>Entry</th>
                  <th>Exited</th><th>Exit</th><th>Bars</th>
                  <th>PnL</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.map((t, i) => (
                  <tr key={i}>
                    <td className="muted small">{t.entered_at.slice(0, 19).replace("T", " ")}</td>
                    <td>{t.side}</td>
                    <td>{fmt(t.entry_price, 2)}</td>
                    <td className="muted small">{t.exited_at.slice(0, 19).replace("T", " ")}</td>
                    <td>{fmt(t.exit_price, 2)}</td>
                    <td>{t.hold_bars}</td>
                    <td className={toneClass(t.pnl_usd)}>{fmtUSD(t.pnl_usd)}</td>
                    <td className="muted small">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function EquityChart({ points }: { points: LineData[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth, height: 280,
      layout: { background: { color: "#0d1117" }, textColor: "#e6edf3" },
      grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#30363d" },
      rightPriceScale: { borderColor: "#30363d" },
    });
    const series = chart.addSeries(LineSeries, { color: "#58a6ff", lineWidth: 2 });
    chartRef.current = chart;
    seriesRef.current = series;
    const resize = () => chart.applyOptions({ width: container.clientWidth, height: 280 });
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    return () => { ro.disconnect(); chart.remove(); };
  }, []);

  useEffect(() => {
    seriesRef.current?.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={containerRef} className="chart-container" />;
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
function fmt(v: number | undefined | null, dp = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(dp);
}
function fmtUSD(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return "$" + v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function toneClass(v: number): string {
  if (!Number.isFinite(v)) return "";
  return v > 0 ? "tone--pos" : v < 0 ? "tone--neg" : "";
}
