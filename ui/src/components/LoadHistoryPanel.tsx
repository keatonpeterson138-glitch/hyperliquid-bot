// "Load historical data" panel for Data Lab. User picks symbols +
// intervals + depth preset -> sequential /backfill calls with live
// progress. On completion, parent refreshes the catalog.
//
// Depth presets map the config of bootstrap_lake to UI-friendly options
// so a new user can go "give me the top 20 with 1 year of hourly data"
// in two clicks.

import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { markets } from "../api/endpoints";

const INTERVAL_CHOICES = ["1d", "4h", "1h", "30m", "15m", "5m", "1m"] as const;

const DEPTH_PRESETS = {
  deep:     { label: "Deep (plan depth targets)", days: null },    // per-interval per §6.1
  three_yr: { label: "3 years",  days: 3 * 365 },
  one_yr:   { label: "1 year",   days: 365 },
  three_mo: { label: "3 months", days: 90 },
  one_mo:   { label: "1 month",  days: 30 },
  custom:   { label: "Custom dates", days: null },
} as const;
type DepthPreset = keyof typeof DEPTH_PRESETS;

// Per-interval plan targets from OVERHAUL_PLAN §6.1 / bootstrap_lake.
const PLAN_DEPTH_DAYS: Record<string, number> = {
  "1d":  10 * 365,
  "4h":  7 * 365,
  "1h":  7 * 365,
  "30m": 3 * 365,
  "15m": 3 * 365,
  "5m":  2 * 365,
  "1m":  365,
};

const SYMBOL_PRESETS = {
  top5:  { label: "Top 5 (BTC, ETH, SOL, HYPE, AVAX)", symbols: ["BTC", "ETH", "SOL", "HYPE", "AVAX"] },
  top20: { label: "Top 20 by market",                  symbols: [] as string[] /* filled from catalog */ },
  all:   { label: "Every Hyperliquid perp",            symbols: [] as string[] },
  custom:{ label: "Custom",                             symbols: [] as string[] },
} as const;
type SymbolPreset = keyof typeof SYMBOL_PRESETS;

interface SliceProgress {
  symbol: string;
  interval: string;
  status: "pending" | "running" | "done" | "error";
  rows_written?: number;
  error?: string;
  duration_ms?: number;
}

export function LoadHistoryPanel({ onComplete }: { onComplete: () => void }) {
  const [catalog, setCatalog] = useState<string[]>([]);
  const [symbolPreset, setSymbolPreset] = useState<SymbolPreset>("top5");
  const [customSyms, setCustomSyms] = useState("BTC,ETH,SOL,HYPE,AVAX,ARB,DOGE,LINK");
  const [intervals, setIntervals] = useState<string[]>(["1h", "1d"]);
  const [depth, setDepth] = useState<DepthPreset>("one_yr");
  const [customFrom, setCustomFrom] = useState(() =>
    new Date(Date.now() - 365 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [customTo, setCustomTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [queue, setQueue] = useState<SliceProgress[]>([]);
  const [running, setRunning] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);

  useEffect(() => {
    markets
      .meta()
      .then((r) => {
        const raw = r.raw as { universe?: Array<{ name?: string }> };
        const names = (raw.universe ?? []).map((u) => u.name).filter((n): n is string => !!n);
        setCatalog(names);
      })
      .catch(() => setCatalog([]));
  }, []);

  const resolveSymbols = useCallback((): string[] => {
    if (symbolPreset === "custom") {
      return customSyms
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);
    }
    if (symbolPreset === "top5") return [...SYMBOL_PRESETS.top5.symbols];
    if (symbolPreset === "top20") {
      // No market-cap source; fall back to catalog order (which is
      // Hyperliquid's own universe ordering — BTC first, then usage rank).
      return catalog.slice(0, 20);
    }
    return catalog;
  }, [symbolPreset, customSyms, catalog]);

  const toggleInterval = (iv: string) =>
    setIntervals((prev) => (prev.includes(iv) ? prev.filter((x) => x !== iv) : [...prev, iv]));

  const start = async () => {
    const symbols = resolveSymbols();
    if (symbols.length === 0) return;
    if (intervals.length === 0) return;

    const preset = DEPTH_PRESETS[depth];
    const initial: SliceProgress[] = symbols.flatMap((s) =>
      intervals.map((iv) => ({ symbol: s, interval: iv, status: "pending" as const })),
    );
    setQueue(initial);
    setRunning(true);
    setCancelRequested(false);

    for (let i = 0; i < initial.length; i++) {
      if (cancelRequested) break;
      const task = initial[i];
      setQueue((q) => q.map((t, idx) => (idx === i ? { ...t, status: "running" } : t)));

      let fromIso: string;
      let toIso: string;
      if (depth === "custom") {
        fromIso = `${customFrom}T00:00:00Z`;
        toIso = `${customTo}T23:59:59Z`;
      } else if (preset.days !== null) {
        toIso = new Date().toISOString();
        fromIso = new Date(Date.now() - preset.days * 24 * 3_600_000).toISOString();
      } else {
        // Deep — follow per-interval plan targets.
        const days = PLAN_DEPTH_DAYS[task.interval] ?? 365;
        toIso = new Date().toISOString();
        fromIso = new Date(Date.now() - days * 24 * 3_600_000).toISOString();
      }

      const started = Date.now();
      try {
        const r = await api.post<{
          rows_written: number;
          sources_used: string[];
          errors: unknown[];
        }>("/backfill", {
          symbol: task.symbol,
          interval: task.interval,
          start: fromIso,
          end: toIso,
          allow_partial: true,
        });
        setQueue((q) =>
          q.map((t, idx) =>
            idx === i
              ? { ...t, status: "done", rows_written: r.rows_written, duration_ms: Date.now() - started }
              : t,
          ),
        );
      } catch (e) {
        setQueue((q) =>
          q.map((t, idx) =>
            idx === i
              ? { ...t, status: "error", error: (e as Error).message, duration_ms: Date.now() - started }
              : t,
          ),
        );
      }
    }

    setRunning(false);
    onComplete();
  };

  const cancel = () => setCancelRequested(true);

  const done = queue.filter((q) => q.status === "done").length;
  const errors = queue.filter((q) => q.status === "error").length;
  const total = queue.length;
  const totalRows = queue.reduce((sum, q) => sum + (q.rows_written ?? 0), 0);

  return (
    <section className="card">
      <h2 className="card__title">Load historical data</h2>
      <p className="muted small">
        Pulls from Hyperliquid + Binance + Coinbase + yfinance. The router
        stitches sources to go as deep as any provider allows — BTC back to
        2015 via Coinbase, most HIP-3 stocks decades via yfinance.
      </p>

      <h3 className="card__title">1. Symbols</h3>
      <div className="chart-toolbar">
        {(Object.keys(SYMBOL_PRESETS) as SymbolPreset[]).map((key) => (
          <label key={key} className="chip-row">
            <input
              type="radio"
              name="sympreset"
              checked={symbolPreset === key}
              onChange={() => setSymbolPreset(key)}
            />{" "}
            {SYMBOL_PRESETS[key].label}
          </label>
        ))}
      </div>
      {symbolPreset === "custom" && (
        <label className="field">
          <span>Symbols (comma-separated)</span>
          <input value={customSyms} onChange={(e) => setCustomSyms(e.target.value)} />
        </label>
      )}
      <p className="muted small">
        {resolveSymbols().length} symbol(s) will be pulled. Universe size: {catalog.length}.
      </p>

      <h3 className="card__title">2. Intervals</h3>
      <div className="chip-row">
        {INTERVAL_CHOICES.map((iv) => (
          <label key={iv} className={`chip ${intervals.includes(iv) ? "chip--active" : ""}`}>
            <input
              type="checkbox"
              checked={intervals.includes(iv)}
              onChange={() => toggleInterval(iv)}
              style={{ marginRight: 4 }}
            />{" "}
            {iv}
          </label>
        ))}
      </div>

      <h3 className="card__title">3. Depth</h3>
      <div className="chip-row">
        {(Object.keys(DEPTH_PRESETS) as DepthPreset[]).map((key) => (
          <label key={key} className="chip-row">
            <input
              type="radio"
              name="depth"
              checked={depth === key}
              onChange={() => setDepth(key)}
            />{" "}
            {DEPTH_PRESETS[key].label}
          </label>
        ))}
      </div>
      {depth === "custom" && (
        <div className="chart-toolbar">
          <label className="field">
            <span>From</span>
            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
          </label>
          <label className="field">
            <span>To</span>
            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
          </label>
        </div>
      )}

      <div className="chart-toolbar">
        <button onClick={start} disabled={running || resolveSymbols().length === 0 || intervals.length === 0}>
          {running ? "Loading…" : `Load ${resolveSymbols().length * intervals.length} slice(s)`}
        </button>
        {running && <button onClick={cancel}>Stop after current</button>}
        {total > 0 && !running && (
          <span className="muted small">
            Done {done}/{total} · {errors} error(s) · {totalRows.toLocaleString()} rows
          </span>
        )}
      </div>

      {queue.length > 0 && (
        <>
          <h3 className="card__title">Progress</h3>
          <div style={{ maxHeight: 280, overflow: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Interval</th>
                  <th>Status</th>
                  <th>Rows</th>
                  <th>Duration</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((t, i) => (
                  <tr key={i}>
                    <td>{t.symbol}</td>
                    <td>{t.interval}</td>
                    <td>
                      <span className={`badge badge--${statusClass(t.status)}`}>{t.status}</span>
                    </td>
                    <td>{t.rows_written?.toLocaleString() ?? "—"}</td>
                    <td className="muted small">
                      {t.duration_ms !== undefined ? `${(t.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td className="muted small tone--neg" title={t.error}>{t.error ? t.error.slice(0, 40) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function statusClass(s: SliceProgress["status"]): string {
  if (s === "done") return "active";
  if (s === "running") return "pending";
  if (s === "error") return "cancelled";
  return "draft";
}
