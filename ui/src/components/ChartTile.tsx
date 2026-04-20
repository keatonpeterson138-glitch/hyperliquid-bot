// A single self-contained chart tile — its own symbol, interval, REST
// backfill, 30s tail refresh, and direct Hyperliquid WS subscription.
// Dropped N times into a grid to get the multi-chart workspace.
//
// Deep backfill: on (symbol, interval) change we ask the backend for
// the full historical depth target per interval — the backend's source
// router stitches Hyperliquid + Binance + Coinbase to go as deep as
// any source can supply.

import { useCallback, useEffect, useMemo, useState } from "react";

import { CandleChart, type ChartCoords } from "./CandleChart";
import { MarkupLayer } from "./MarkupLayer";
import { candles } from "../api/endpoints";
import { useHyperliquidCandles } from "../hooks/useHyperliquidCandles";
import type { CandlesResponse } from "../api/types";

export interface ChartTileProps {
  symbol: string;
  interval: string;
  testnet: boolean;
  height?: number;
  symbolOptions?: string[];
  intervalOptions?: readonly string[];
  showMarkups?: boolean;
  onSymbolChange?: (symbol: string) => void;
  onIntervalChange?: (interval: string) => void;
  onRemove?: () => void;
}

// Depth target per interval. Feeds the first-open backfill so the tile
// starts with as much history as the source router can stitch.
const DEEP_LOOKBACK_DAYS: Record<string, number> = {
  "1m":  90,          // rolling ~3 months (API rate limits make more painful)
  "5m":  365,         // 1 yr
  "15m": 3 * 365,     // 3 yr
  "30m": 5 * 365,     // 5 yr
  "1h":  7 * 365,     // 7 yr (stitches HL + Binance + Coinbase)
  "2h":  7 * 365,
  "4h":  10 * 365,    // decade
  "8h":  10 * 365,
  "1d":  15 * 365,    // max-everything
  "3d":  15 * 365,
  "1w":  20 * 365,
  "1M":  20 * 365,
};

const REFRESH_MS = 30_000;

export function ChartTile({
  symbol,
  interval,
  testnet,
  height = 360,
  symbolOptions = ["BTC", "ETH", "SOL", "HYPE"],
  intervalOptions = ["1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d", "1w"],
  showMarkups = false,
  onSymbolChange,
  onIntervalChange,
  onRemove,
}: ChartTileProps) {
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coords, setCoords] = useState<ChartCoords | null>(null);

  // Full-range fetch on (symbol, interval) change + periodic tail refresh.
  useEffect(() => {
    let cancelled = false;
    const lookbackDays = DEEP_LOOKBACK_DAYS[interval] ?? 90;

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

    const refreshTail = async () => {
      try {
        const r = await candles.refresh(symbol, interval, 48);
        if (cancelled) return;
        setData((prev) => {
          if (!prev) return r;
          const map = new Map(prev.bars.map((b) => [b.timestamp, b]));
          for (const b of r.bars) map.set(b.timestamp, b);
          const bars = [...map.values()].sort((a, b) =>
            a.timestamp < b.timestamp ? -1 : 1,
          );
          return { ...prev, bars, bar_count: bars.length };
        });
      } catch {
        /* transient */
      }
    };

    void loadFull();
    const id = window.setInterval(refreshTail, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [symbol, interval]);

  // Merge live bar from Hyperliquid WS into the chart.
  const mergeLiveBar = useCallback((bar: {
    timestamp: string; open: number; high: number; low: number;
    close: number; volume: number; trades: number | null; source: string;
  }) => {
    setData((prev) => {
      if (!prev) return prev;
      const bars = prev.bars.slice();
      const idx = bars.findIndex((b) => b.timestamp === bar.timestamp);
      if (idx >= 0) bars[idx] = { ...bars[idx], ...bar };
      else {
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

  const last = data?.bars[data.bars.length - 1];
  const earliest = data?.bars[0];
  const symOptions = useMemo(() => {
    if (symbolOptions.includes(symbol)) return symbolOptions;
    return [symbol, ...symbolOptions];
  }, [symbolOptions, symbol]);

  return (
    <div className="chart-tile">
      <div className="chart-tile__toolbar">
        <select
          className="chart-tile__sym"
          value={symbol}
          onChange={(e) => onSymbolChange?.(e.target.value)}
        >
          {symOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="chart-tile__iv"
          value={interval}
          onChange={(e) => onIntervalChange?.(e.target.value)}
        >
          {intervalOptions.map((i) => (
            <option key={i} value={i}>
              {i}
            </option>
          ))}
        </select>
        <div className="chart-tile__stats">
          {loading && <span className="muted small">loading…</span>}
          {error && <span className="error small" title={error}>err</span>}
          {last && (
            <>
              <span className="chart-tile__price">{last.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
              <span className={`chart-tile__live ${liveStatus.status === "open" ? "tone--pos" : liveStatus.status === "closed" ? "tone--neg" : "muted"}`}>
                ● {liveStatus.status}
              </span>
              <span className="muted small">
                {data?.bar_count ?? 0} bars
                {earliest ? ` since ${earliest.timestamp.slice(0, 10)}` : ""}
              </span>
            </>
          )}
        </div>
        {onRemove && (
          <button className="chart-tile__close" onClick={onRemove} title="Remove tile">×</button>
        )}
      </div>
      <div className="chart-tile__chart" style={{ position: "relative" }}>
        <CandleChart data={data} height={height} onCoordsChange={setCoords} />
        {showMarkups && coords && (
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
    </div>
  );
}
