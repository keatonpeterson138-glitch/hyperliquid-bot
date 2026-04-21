// A single self-contained chart tile — own symbol, interval, chartType,
// indicator toggles, overlay symbols, REST backfill, 30s tail refresh,
// and direct Hyperliquid WS subscription. Dropped N times into a grid
// for the multi-chart workspace.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CandleChart, type ChartCoords, type OverlaySeries } from "./CandleChart";
import { MarkupLayer } from "./MarkupLayer";
import { SymbolCombobox } from "./SymbolCombobox";
import { candles } from "../api/endpoints";
import { useHyperliquidCandles } from "../hooks/useHyperliquidCandles";
import type { CandlesResponse } from "../api/types";
import { getCachedCandles, setCachedCandles } from "../lib/chartCache";
import {
  DEFAULT_INDICATORS,
  type ChartType,
  type IndicatorState,
} from "../lib/workspaceStorage";

export interface ChartTileProps {
  symbol: string;
  interval: string;
  chartType?: ChartType;
  indicators?: IndicatorState;
  overlays?: string[];
  testnet: boolean;
  height?: number;
  symbolOptions?: string[];
  intervalOptions?: readonly string[];
  showMarkups?: boolean;
  onSymbolChange?: (symbol: string) => void;
  onIntervalChange?: (interval: string) => void;
  onChartTypeChange?: (t: ChartType) => void;
  onIndicatorsChange?: (patch: Partial<IndicatorState>) => void;
  onOverlaysChange?: (next: string[]) => void;
  onRemove?: () => void;
}

const DEEP_LOOKBACK_DAYS: Record<string, number> = {
  "1m":  90,
  "5m":  365,
  "15m": 3 * 365,
  "30m": 5 * 365,
  "1h":  7 * 365,
  "2h":  7 * 365,
  "4h":  10 * 365,
  "8h":  10 * 365,
  "1d":  15 * 365,
  "3d":  15 * 365,
  "1w":  20 * 365,
  "1M":  20 * 365,
};

const REFRESH_MS = 30_000;

const CHART_TYPES: Array<{ key: ChartType; label: string }> = [
  { key: "candle", label: "Candle" },
  { key: "bar",    label: "Bar" },
  { key: "line",   label: "Line" },
  { key: "area",   label: "Area" },
];

const INDICATOR_TOGGLES: Array<{ key: keyof IndicatorState; label: string }> = [
  { key: "ema12",    label: "EMA 12" },
  { key: "ema26",    label: "EMA 26" },
  { key: "ema50",    label: "EMA 50" },
  { key: "ema200",   label: "EMA 200" },
  { key: "rsi",      label: "RSI (14)" },
  { key: "volume",   label: "Volume" },
  { key: "logScale", label: "Log scale" },
];

export function ChartTile({
  symbol,
  interval,
  chartType = "candle",
  indicators = DEFAULT_INDICATORS,
  overlays = [],
  testnet,
  height = 360,
  symbolOptions = ["BTC", "ETH", "SOL", "HYPE"],
  intervalOptions = ["1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d", "1w"],
  showMarkups = false,
  onSymbolChange,
  onIntervalChange,
  onChartTypeChange,
  onIndicatorsChange,
  onOverlaysChange,
  onRemove,
}: ChartTileProps) {
  // Seed from the module-level cache so tab switches don't blank the
  // chart — the fresh fetch below runs in the background and replaces
  // the cached copy when it returns.
  const [data, setData] = useState<CandlesResponse | null>(
    () => getCachedCandles(symbol, interval),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coords, setCoords] = useState<ChartCoords | null>(null);
  const [showMenu, setShowMenu] = useState<null | "indicators" | "overlays" | "type">(null);
  const [overlayData, setOverlayData] = useState<Record<string, CandlesResponse | null>>({});
  const [overlayInput, setOverlayInput] = useState("");

  // Close popovers when clicking outside.
  const toolbarRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!showMenu) return;
    const onDocClick = (e: MouseEvent) => {
      if (!toolbarRef.current?.contains(e.target as Node)) setShowMenu(null);
    };
    window.addEventListener("mousedown", onDocClick);
    return () => window.removeEventListener("mousedown", onDocClick);
  }, [showMenu]);

  // Main symbol full-range fetch on (symbol, interval) change + periodic tail refresh.
  useEffect(() => {
    let cancelled = false;
    const lookbackDays = DEEP_LOOKBACK_DAYS[interval] ?? 90;

    // On (symbol, interval) switch, rehydrate from cache immediately so
    // the chart never goes blank; the network fetch replaces the cached
    // copy below.
    const cached = getCachedCandles(symbol, interval);
    if (cached) setData(cached);

    const loadFull = async () => {
      const to = new Date();
      const from = new Date(to.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
      setLoading(true);
      setError(null);
      try {
        const r = await candles.get(symbol, interval, from.toISOString(), to.toISOString());
        if (!cancelled) {
          setData(r);
          setCachedCandles(symbol, interval, r);
        }
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
          let merged: CandlesResponse;
          if (!prev) merged = r;
          else {
            const map = new Map(prev.bars.map((b) => [b.timestamp, b]));
            for (const b of r.bars) map.set(b.timestamp, b);
            const bars = [...map.values()].sort((a, b) =>
              a.timestamp < b.timestamp ? -1 : 1,
            );
            merged = { ...prev, bars, bar_count: bars.length };
          }
          setCachedCandles(symbol, interval, merged);
          return merged;
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

  // Fetch overlay candles whenever the list or interval changes. We
  // deliberately refetch every overlay on any change — the ~10KB per
  // symbol is cheap enough that deduping adds more complexity than it
  // saves. Cancel flag guards against setting state after unmount.
  useEffect(() => {
    let cancelled = false;
    if (overlays.length === 0) {
      setOverlayData({});
      return () => { cancelled = true; };
    }
    const lookbackDays = DEEP_LOOKBACK_DAYS[interval] ?? 90;
    const to = new Date();
    const from = new Date(to.getTime() - lookbackDays * 24 * 60 * 60 * 1000);

    // Prune dropped overlays so their series tear down.
    setOverlayData((prev) => {
      const next: Record<string, CandlesResponse | null> = {};
      for (const k of overlays) {
        if (k in prev) next[k] = prev[k];
      }
      return next;
    });

    for (const s of overlays) {
      candles
        .get(s, interval, from.toISOString(), to.toISOString())
        .then((r) => {
          if (!cancelled) setOverlayData((prev) => ({ ...prev, [s]: r }));
        })
        .catch(() => {
          if (!cancelled) setOverlayData((prev) => ({ ...prev, [s]: null }));
        });
    }
    return () => { cancelled = true; };
  }, [overlays, interval]);

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
      const next = { ...prev, bars, bar_count: bars.length };
      setCachedCandles(symbol, interval, next);
      return next;
    });
  }, [symbol, interval]);

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

  const overlaySeries = useMemo<OverlaySeries[]>(() => {
    const colors = ["#79c0ff", "#ff7b72", "#d2a8ff", "#ffa657", "#7ee787"];
    return overlays.map((s, i) => ({
      symbol: s,
      data: overlayData[s] ?? null,
      color: colors[i % colors.length],
    }));
  }, [overlays, overlayData]);

  const addOverlay = (sym: string) => {
    const s = sym.trim().toUpperCase();
    if (!s || s === symbol.toUpperCase() || overlays.includes(s)) return;
    onOverlaysChange?.([...overlays, s]);
    setOverlayInput("");
  };

  return (
    <div className="chart-tile">
      <div className="chart-tile__toolbar" ref={toolbarRef}>
        <SymbolCombobox
          className="chart-tile__sym"
          value={symbol}
          onChange={(s) => onSymbolChange?.(s)}
          options={symOptions}
          placeholder="Symbol"
        />
        <select
          className="chart-tile__iv"
          value={interval}
          onChange={(e) => onIntervalChange?.(e.target.value)}
        >
          {intervalOptions.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>

        <div className="chart-tile__menu-wrap">
          <button
            className="chart-tile__menu-btn"
            onClick={() => setShowMenu(showMenu === "type" ? null : "type")}
            title="Chart type"
          >
            {CHART_TYPES.find((t) => t.key === chartType)?.label ?? "Candle"} ▾
          </button>
          {showMenu === "type" && (
            <div className="chart-tile__menu">
              {CHART_TYPES.map((t) => (
                <button
                  key={t.key}
                  className={`chart-tile__menu-item ${chartType === t.key ? "is-active" : ""}`}
                  onClick={() => { onChartTypeChange?.(t.key); setShowMenu(null); }}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="chart-tile__menu-wrap">
          <button
            className="chart-tile__menu-btn"
            onClick={() => setShowMenu(showMenu === "indicators" ? null : "indicators")}
            title="Indicators"
          >
            Indicators ▾
          </button>
          {showMenu === "indicators" && (
            <div className="chart-tile__menu">
              {INDICATOR_TOGGLES.map((ind) => (
                <label key={ind.key} className="chart-tile__menu-item">
                  <input
                    type="checkbox"
                    checked={indicators[ind.key]}
                    onChange={(e) => onIndicatorsChange?.({ [ind.key]: e.target.checked })}
                  />
                  <span>{ind.label}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="chart-tile__menu-wrap">
          <button
            className="chart-tile__menu-btn"
            onClick={() => setShowMenu(showMenu === "overlays" ? null : "overlays")}
            title="Compare overlays"
          >
            Overlays ({overlays.length}) ▾
          </button>
          {showMenu === "overlays" && (
            <div className="chart-tile__menu chart-tile__menu--wide">
              <div className="chart-tile__menu-hint muted small">
                Add another symbol — rendered as a line normalized to 100 at the first bar.
              </div>
              <div className="chart-tile__menu-row">
                <SymbolCombobox
                  value={overlayInput}
                  onChange={(s) => addOverlay(s)}
                  options={symOptions.filter((s) => s !== symbol && !overlays.includes(s))}
                  placeholder="Type a symbol to add (SPY, DGS10, BTC…)"
                  allowFreeText
                />
                <button onClick={() => addOverlay(overlayInput)} disabled={!overlayInput.trim()}>
                  Add
                </button>
              </div>
              {overlays.length === 0 ? (
                <div className="muted small">No overlays.</div>
              ) : (
                <ul className="chart-tile__overlay-list">
                  {overlays.map((s, i) => {
                    const loaded = s in overlayData && overlayData[s] !== null;
                    return (
                      <li key={s}>
                        <span
                          className="chart-tile__overlay-swatch"
                          style={{ background: ["#79c0ff", "#ff7b72", "#d2a8ff", "#ffa657", "#7ee787"][i % 5] }}
                        />
                        <span>{s}</span>
                        {!loaded && overlayData[s] === null && <span className="error small">err</span>}
                        {!(s in overlayData) && <span className="muted small">loading…</span>}
                        <button
                          className="chart-tile__overlay-remove"
                          onClick={() => onOverlaysChange?.(overlays.filter((x) => x !== s))}
                          title="Remove overlay"
                        >
                          ×
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="chart-tile__stats">
          {loading && <span className="muted small">loading…</span>}
          {error && <span className="error small" title={error}>err</span>}
          {last && (
            <>
              <span className="chart-tile__price">
                {last.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
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
        <CandleChart
          data={data}
          height={height}
          chartType={chartType}
          indicators={indicators}
          overlays={overlaySeries}
          onCoordsChange={setCoords}
        />
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
