// Charts workspace — tiled grid of independent ChartTiles (1/2/4/8).
// Each tile has its own symbol, interval, chart type, indicator set,
// overlay symbols, live WS, and deep backfill. Persists to localStorage
// via the workspace helpers so reloading the tab restores the setup.

import { useEffect, useMemo, useRef, useState } from "react";

import { ChartTile } from "../components/ChartTile";
import {
  markets as marketsApi,
  settings as settingsApi,
  universe,
} from "../api/endpoints";
import {
  defaultTile,
  loadWorkspace,
  saveWorkspace,
  type ChartType,
  type IndicatorState,
  type Layout,
  type TileState,
} from "../lib/workspaceStorage";

const DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB", "DOGE", "LINK"];
const DEFAULT_INTERVAL = "1h";

// Non-crypto chartables — stitched into the symbol catalog alongside
// Hyperliquid's perp universe so the dropdown covers every data source
// the backend router can stitch (stocks via yfinance/Alpha Vantage,
// macro series via FRED, Hyperliquid HIP-3 stocks/commodities, etc.).
const STOCK_SYMBOLS = [
  "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "AMD",
  "INTC", "NFLX", "COIN", "MSTR", "HOOD", "PLTR", "TSM",
];
const HIP3_PERPS = [
  "xyz:SP500", "xyz:XYZ100",
  "cash:GOLD", "cash:SILVER", "cash:OIL", "cash:CORN", "cash:WHEAT",
];
const INDEX_SYMBOLS = ["^GSPC", "^DJI", "^IXIC", "^VIX", "^TNX"];
const FRED_SERIES = [
  "DFF",    "DGS10",   "DGS2",    "T10Y2Y",  "DFII10",
  "T10YIE", "T5YIFR",  "CPIAUCSL","CPILFESL","UNRATE",
  "PAYEMS", "ICSA",    "GDPC1",   "INDPRO",  "UMCSENT",
  "VIXCLS", "DTWEXBGS","WALCL",   "M2SL",    "RRPONTSYD",
];
const NON_CRYPTO_SYMBOLS = [
  ...STOCK_SYMBOLS,
  ...HIP3_PERPS,
  ...INDEX_SYMBOLS,
  ...FRED_SERIES,
];

export function ChartsPage() {
  const initialRef = useRef(loadWorkspace());

  const [layout, setLayout] = useState<Layout>(
    initialRef.current?.layout ?? 1,
  );
  const [tiles, setTiles] = useState<TileState[]>(
    initialRef.current?.tiles?.length
      ? initialRef.current.tiles
      : [defaultTile("BTC", DEFAULT_INTERVAL)],
  );
  const [symbolCatalog, setSymbolCatalog] = useState<string[]>(DEFAULT_SYMBOLS);
  const [testnet, setTestnet] = useState(false);

  // Persist on every layout/tiles change. Guard the first render so we
  // don't overwrite with the pre-load state before the restore finishes.
  const hasLoaded = useRef(false);
  useEffect(() => {
    if (!hasLoaded.current) {
      hasLoaded.current = true;
      return;
    }
    saveWorkspace({ version: 1, layout, tiles });
  }, [layout, tiles]);

  useEffect(() => {
    const merge = (cryptoNames: string[]) => {
      // De-dupe while preserving order — crypto first (most frequent use),
      // then stocks / HIP-3 / indices / FRED macro so everything's one click.
      const seen = new Set<string>();
      const out: string[] = [];
      for (const s of [...cryptoNames, ...NON_CRYPTO_SYMBOLS]) {
        if (!seen.has(s)) { seen.add(s); out.push(s); }
      }
      setSymbolCatalog(out);
    };

    marketsApi
      .meta()
      .then((r) => {
        const raw = r.raw as { universe?: Array<{ name?: string }> };
        const names = (raw.universe ?? [])
          .map((u) => u.name)
          .filter((n): n is string => !!n);
        if (names.length > 0) merge(names);
        else return universe.list({ active_only: true, kind: "perp" }).then((u) => {
          merge(u.markets.map((m) => m.symbol));
        });
      })
      .catch(() =>
        universe
          .list({ active_only: true, kind: "perp" })
          .then((u) => merge(u.markets.map((m) => m.symbol)))
          .catch(() => merge(DEFAULT_SYMBOLS)),
      );
    settingsApi.get().then((s) => setTestnet(s.testnet)).catch(() => undefined);
  }, []);

  const changeLayout = (next: Layout) => {
    setLayout(next);
    setTiles((prev) => {
      if (prev.length === next) return prev;
      if (prev.length > next) return prev.slice(0, next);
      const extra: TileState[] = [];
      const defaults = DEFAULT_SYMBOLS;
      for (let i = prev.length; i < next; i++) {
        extra.push(defaultTile(defaults[i % defaults.length], DEFAULT_INTERVAL));
      }
      return [...prev, ...extra];
    });
  };

  const tileHeight = useMemo(() => {
    if (layout === 1) return 560;
    if (layout === 2) return 480;
    if (layout === 4) return 320;
    return 260;
  }, [layout]);

  const setTile = (idx: number, patch: Partial<TileState>) =>
    setTiles((prev) => prev.map((t, i) => (i === idx ? { ...t, ...patch } : t)));

  const setTileIndicators = (idx: number, patch: Partial<IndicatorState>) =>
    setTiles((prev) => prev.map((t, i) =>
      i === idx ? { ...t, indicators: { ...t.indicators, ...patch } } : t,
    ));

  const setTileChartType = (idx: number, chartType: ChartType) =>
    setTiles((prev) => prev.map((t, i) => (i === idx ? { ...t, chartType } : t)));

  const setTileOverlays = (idx: number, overlays: string[]) =>
    setTiles((prev) => prev.map((t, i) => (i === idx ? { ...t, overlays } : t)));

  const removeTile = (idx: number) =>
    setTiles((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setLayout(Math.max(1, next.length) as Layout);
      return next.length === 0 ? [defaultTile("BTC", DEFAULT_INTERVAL)] : next;
    });

  const resetWorkspace = () => {
    if (!confirm("Reset the chart workspace? This clears every tile + indicator + overlay.")) return;
    setLayout(1);
    setTiles([defaultTile("BTC", DEFAULT_INTERVAL)]);
  };

  return (
    <div className="page">
      <h1 className="page__title">Charts</h1>

      <div className="chart-toolbar">
        <label className="field">
          <span>Layout</span>
          <select
            value={layout}
            onChange={(e) => changeLayout(Number(e.target.value) as Layout)}
          >
            <option value={1}>1 chart</option>
            <option value={2}>2 charts (side-by-side)</option>
            <option value={4}>4 charts (2×2 grid)</option>
            <option value={8}>8 charts (4×2 grid)</option>
          </select>
        </label>
        <button onClick={resetWorkspace} className="btn btn--subtle">Reset workspace</button>
        <span className="muted small">
          {symbolCatalog.length} symbols · deep back-pull · Hyperliquid WS live · persists per tab
        </span>
      </div>

      <div className={`chart-grid chart-grid--${layout}`}>
        {tiles.map((t, i) => (
          <ChartTile
            key={i}
            symbol={t.symbol}
            interval={t.interval}
            chartType={t.chartType}
            indicators={t.indicators}
            overlays={t.overlays}
            testnet={testnet}
            height={tileHeight}
            symbolOptions={symbolCatalog}
            showMarkups={layout === 1}
            onSymbolChange={(s) => setTile(i, { symbol: s })}
            onIntervalChange={(iv) => setTile(i, { interval: iv })}
            onChartTypeChange={(ct) => setTileChartType(i, ct)}
            onIndicatorsChange={(patch) => setTileIndicators(i, patch)}
            onOverlaysChange={(ov) => setTileOverlays(i, ov)}
            onRemove={tiles.length > 1 ? () => removeTile(i) : undefined}
          />
        ))}
      </div>
    </div>
  );
}
