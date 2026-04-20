// Full chart workspace: symbol + interval pickers, backend-driven candle
// fetch, lightweight-charts render, SVG markup overlay. Live ticks come
// directly from Hyperliquid's WebSocket (useHyperliquidCandles hook).

import { useCallback, useEffect, useMemo, useState } from "react";

import { CandleChart, type ChartCoords } from "../components/CandleChart";
import { MarkupLayer } from "../components/MarkupLayer";
import { candles, markets as marketsApi, settings as settingsApi, universe } from "../api/endpoints";
import { useHyperliquidCandles } from "../hooks/useHyperliquidCandles";
import type { CandlesResponse, Market } from "../api/types";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d", "1w"] as const;
type Interval = (typeof INTERVALS)[number];

const DEFAULT_LOOKBACK_DAYS: Record<Interval, number> = {
  "1m": 1,
  "5m": 3,
  "15m": 7,
  "30m": 14,
  "1h": 30,
  "4h": 120,
  "8h": 240,
  "1d": 730,
  "1w": 1460,
};

export function ChartsPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [symbol, setSymbol] = useState<string>("BTC");
  const [interval, setInterval] = useState<Interval>("1h");
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [coords, setCoords] = useState<ChartCoords | null>(null);
  const [testnet, setTestnet] = useState<boolean>(false);

  useEffect(() => {
    // Prefer the live Hyperliquid meta (always populated) and fall back
    // to the local universe catalog (might be empty on first run if
    // UniverseManager.refresh() hasn't fired yet).
    marketsApi
      .meta()
      .then((r) => {
        const raw = r.raw as { universe?: Array<{ name?: string }> };
        const fromMeta = (raw.universe ?? [])
          .map((u) => u.name)
          .filter((n): n is string => !!n)
          .map((name) => ({
            id: `perp:${name}`,
            kind: "perp",
            symbol: name,
            dex: "",
            base: name,
            category: "crypto",
            subcategory: null,
            max_leverage: null,
            sz_decimals: null,
            tick_size: null,
            min_size: null,
            resolution_date: null,
            bounds: null,
            active: true,
            first_seen: null,
            last_seen: null,
            tags: [],
          })) as Market[];
        if (fromMeta.length > 0) {
          setMarkets(fromMeta);
          return;
        }
        return universe.list({ active_only: true, kind: "perp" }).then((u) => setMarkets(u.markets));
      })
      .catch(() =>
        universe
          .list({ active_only: true, kind: "perp" })
          .then((u) => setMarkets(u.markets))
          .catch(() => undefined),
      );
    settingsApi
      .get()
      .then((s) => setTestnet(s.testnet))
      .catch(() => undefined);
  }, []);

  // Merge a single live bar into the chart data. Keyed on timestamp so
  // partial-bar updates overwrite; a new bar appends.
  const mergeLiveBar = useCallback((bar: {
    timestamp: string; open: number; high: number; low: number;
    close: number; volume: number; trades: number | null; source: string;
  }) => {
    setData((prev) => {
      if (!prev) return prev;
      const bars = prev.bars.slice();
      const idx = bars.findIndex((b) => b.timestamp === bar.timestamp);
      if (idx >= 0) {
        bars[idx] = { ...bars[idx], ...bar };
      } else {
        bars.push(bar);
        bars.sort((a, b) => (a.timestamp < b.timestamp ? -1 : 1));
      }
      return { ...prev, bars, bar_count: bars.length };
    });
  }, []);

  const liveStatus = useHyperliquidCandles({
    symbol, interval, testnet, onCandle: mergeLiveBar,
    enabled: Boolean(symbol),
  });

  useEffect(() => {
    let cancelled = false;
    const lookbackDays = DEFAULT_LOOKBACK_DAYS[interval];

    const loadFull = async () => {
      const to = new Date();
      const from = new Date(to.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
      setLoading(true);
      setError(null);
      try {
        const r = await candles.get(symbol, interval, from.toISOString(), to.toISOString());
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    // Lightweight tail refresh — only pulls the last ~48h and merges.
    const refreshTail = async () => {
      try {
        const r = await candles.refresh(symbol, interval, 48);
        if (cancelled) return;
        setData((prev) => {
          if (!prev) return r;
          const mergedMap = new Map(prev.bars.map((b) => [b.timestamp, b]));
          for (const b of r.bars) mergedMap.set(b.timestamp, b);
          const bars = [...mergedMap.values()].sort((a, b) =>
            a.timestamp < b.timestamp ? -1 : 1,
          );
          return { ...prev, bars, bar_count: bars.length };
        });
      } catch {
        /* transient — next tick will try again */
      }
    };

    void loadFull();
    const id = window.setInterval(refreshTail, 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [symbol, interval]);

  const symbolOptions = useMemo(() => {
    const items = markets.map((m) => m.symbol);
    if (!items.includes(symbol)) items.unshift(symbol);
    return items;
  }, [markets, symbol]);

  const last = data?.bars[data.bars.length - 1];

  return (
    <div className="page">
      <h1 className="page__title">Charts</h1>

      <section className="card">
        <div className="chart-toolbar">
          <label className="field">
            <span>Symbol</span>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbolOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Interval</span>
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value as Interval)}
            >
              {INTERVALS.map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
          </label>
          <div className="chart-stats">
            {loading ? (
              <span className="muted">Loading…</span>
            ) : last ? (
              <>
                <Stat label="Last" value={last.close.toFixed(2)} />
                <Stat label="Bars" value={(data?.bar_count ?? 0).toString()} />
                <Stat
                  label="Live"
                  value={liveStatus.status}
                  tone={
                    liveStatus.status === "open"
                      ? "pos"
                      : liveStatus.status === "connecting"
                        ? undefined
                        : "neg"
                  }
                />
              </>
            ) : null}
          </div>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <div style={{ position: "relative" }}>
          <CandleChart data={data} height={480} onCoordsChange={setCoords} />
          {coords && (
            <MarkupLayer
              symbol={symbol}
              interval={interval}
              priceToPixel={coords.priceToPixel}
              pixelToPrice={coords.pixelToPrice}
              width={coords.width}
              height={coords.height}
            />
          )}
        </div>
      </section>

      <section className="card">
        <h2 className="card__title">Source breakdown</h2>
        {data?.source_breakdown && Object.keys(data.source_breakdown).length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Bars</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.source_breakdown).map(([src, n]) => (
                <tr key={src}>
                  <td>{src}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            No data in the local lake for {symbol}/{interval}. Run a backfill
            via <code>python -m backend.tools.backfill --symbol {symbol}</code>.
          </p>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pos" | "neg";
}) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className={`stat-inline__value ${tone ? `tone--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
