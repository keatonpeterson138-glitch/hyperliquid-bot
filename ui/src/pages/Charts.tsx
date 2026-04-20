// Charts workspace — tiled grid of independent ChartTiles (1/2/4/8).
// Each tile has its own symbol + interval + live WS + deep backfill.
// Catalog dropdown lists all Hyperliquid perps (pulled from /markets/meta).

import { useEffect, useMemo, useState } from "react";

import { ChartTile } from "../components/ChartTile";
import {
  markets as marketsApi,
  settings as settingsApi,
  universe,
} from "../api/endpoints";

type Layout = 1 | 2 | 4 | 8;

const DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB", "DOGE", "LINK"];
const DEFAULT_INTERVAL = "1h";

interface Tile {
  symbol: string;
  interval: string;
}

export function ChartsPage() {
  const [layout, setLayout] = useState<Layout>(1);
  const [tiles, setTiles] = useState<Tile[]>([{ symbol: "BTC", interval: DEFAULT_INTERVAL }]);
  const [symbolCatalog, setSymbolCatalog] = useState<string[]>(DEFAULT_SYMBOLS);
  const [testnet, setTestnet] = useState(false);

  // Symbol catalog — prefer live Hyperliquid meta (always populated).
  useEffect(() => {
    marketsApi
      .meta()
      .then((r) => {
        const raw = r.raw as { universe?: Array<{ name?: string }> };
        const names = (raw.universe ?? [])
          .map((u) => u.name)
          .filter((n): n is string => !!n);
        if (names.length > 0) setSymbolCatalog(names);
        else return universe.list({ active_only: true, kind: "perp" }).then((u) => {
          const fallback = u.markets.map((m) => m.symbol);
          if (fallback.length > 0) setSymbolCatalog(fallback);
        });
      })
      .catch(() =>
        universe
          .list({ active_only: true, kind: "perp" })
          .then((u) => {
            const fallback = u.markets.map((m) => m.symbol);
            if (fallback.length > 0) setSymbolCatalog(fallback);
          })
          .catch(() => undefined),
      );
    settingsApi.get().then((s) => setTestnet(s.testnet)).catch(() => undefined);
  }, []);

  // Grow or trim tile list when layout changes.
  const changeLayout = (next: Layout) => {
    setLayout(next);
    setTiles((prev) => {
      if (prev.length === next) return prev;
      if (prev.length > next) return prev.slice(0, next);
      const extra: Tile[] = [];
      const defaults = DEFAULT_SYMBOLS;
      for (let i = prev.length; i < next; i++) {
        extra.push({
          symbol: defaults[i % defaults.length],
          interval: DEFAULT_INTERVAL,
        });
      }
      return [...prev, ...extra];
    });
  };

  const tileHeight = useMemo(() => {
    // Rough per-tile height — two rows when layout >= 4.
    if (layout === 1) return 560;
    if (layout === 2) return 480;
    if (layout === 4) return 320;
    return 260; // 8 tiles, 4x2 grid
  }, [layout]);

  const setTile = (idx: number, patch: Partial<Tile>) =>
    setTiles((prev) => prev.map((t, i) => (i === idx ? { ...t, ...patch } : t)));

  const removeTile = (idx: number) =>
    setTiles((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setLayout(Math.max(1, next.length) as Layout);
      return next.length === 0 ? [{ symbol: "BTC", interval: DEFAULT_INTERVAL }] : next;
    });

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
        <span className="muted small">
          {symbolCatalog.length} symbols · back-pull deep history on first open · Hyperliquid WS live
        </span>
      </div>

      <div className={`chart-grid chart-grid--${layout}`}>
        {tiles.map((t, i) => (
          <ChartTile
            key={i}
            symbol={t.symbol}
            interval={t.interval}
            testnet={testnet}
            height={tileHeight}
            symbolOptions={symbolCatalog}
            showMarkups={layout === 1}
            onSymbolChange={(s) => setTile(i, { symbol: s })}
            onIntervalChange={(iv) => setTile(i, { interval: iv })}
            onRemove={tiles.length > 1 ? () => removeTile(i) : undefined}
          />
        ))}
      </div>
    </div>
  );
}
