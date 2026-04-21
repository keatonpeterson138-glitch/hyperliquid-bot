// Cumulative realised-PnL line chart with 1D/1W/1M/3M toggles.
// Pulls from /wallet/pnl; falls back to a blank placeholder when there's
// no wallet configured yet.

import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { wallet as walletApi, type PnLSeriesResponse, type PnLWindow } from "../api/endpoints";

const WINDOWS: { key: PnLWindow; label: string }[] = [
  { key: "1d", label: "1D" },
  { key: "1w", label: "1W" },
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
];

const CHART_COLORS = {
  bg: "#0d1117",
  text: "#e6edf3",
  grid: "#30363d",
  pos: "#3fb950",
  neg: "#f85149",
};

interface Props { height?: number }

export function PnLChart({ height = 280 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [window, setWindow] = useState<PnLWindow>("1m");
  const [data, setData] = useState<PnLSeriesResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth, height,
      layout: { background: { color: CHART_COLORS.bg }, textColor: CHART_COLORS.text },
      grid: {
        vertLines: { color: CHART_COLORS.grid },
        horzLines: { color: CHART_COLORS.grid },
      },
      timeScale: { timeVisible: true, borderColor: CHART_COLORS.grid, rightOffset: 6 },
      rightPriceScale: { borderColor: CHART_COLORS.grid },
      crosshair: { mode: 1 },
    });
    const line = chart.addSeries(LineSeries, { color: CHART_COLORS.pos, lineWidth: 2 });
    chartRef.current = chart;
    seriesRef.current = line;

    const resize = () => chart.applyOptions({ width: el.clientWidth, height });
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    return () => { observer.disconnect(); chart.remove(); };
  }, [height]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    walletApi.pnl(window)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setErr((e as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [window]);

  useEffect(() => {
    const line = seriesRef.current;
    if (!line || !data) return;
    const points: LineData[] = data.points.map((p) => ({
      time: (Math.floor(new Date(p.timestamp).getTime() / 1000) as unknown) as Time,
      value: p.cumulative,
    }));
    line.setData(points);
    // Recolor based on last value (positive = green, negative = red)
    const last = points[points.length - 1]?.value ?? 0;
    line.applyOptions({ color: last >= 0 ? CHART_COLORS.pos : CHART_COLORS.neg });
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  const total = data?.realised_total_usd ?? 0;
  const fees = data?.fee_total_usd ?? 0;
  const net = total - fees;

  return (
    <section className="card pnl-card">
      <header className="pnl-card__head">
        <div>
          <h2 className="card__title">Cumulative realised P&amp;L</h2>
          <div className="pnl-card__totals">
            <span>Gross <b className={total >= 0 ? "tone--pos" : "tone--neg"}>
              {total >= 0 ? "+" : ""}${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </b></span>
            <span>Fees <b>${fees.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b></span>
            <span>Net <b className={net >= 0 ? "tone--pos" : "tone--neg"}>
              {net >= 0 ? "+" : ""}${net.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </b></span>
          </div>
        </div>
        <div className="pnl-card__tabs">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              className={`chip ${window === w.key ? "chip--active" : ""}`}
              onClick={() => setWindow(w.key)}
              disabled={loading && window === w.key}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>

      {err && (
        <div className="banner">
          {err.includes("no wallet_address")
            ? <>No wallet address set. Sidebar → <a href="#/wallet">Wallet</a> → enter your Hyperliquid address to see live P&amp;L.</>
            : err}
        </div>
      )}

      <div ref={containerRef} className="pnl-card__chart" style={{ height }} />

      {data && data.points.length === 0 && !err && (
        <div className="muted small" style={{ marginTop: 8 }}>
          No closed trades in this window yet — P&amp;L chart will populate as you trade.
        </div>
      )}
    </section>
  );
}
