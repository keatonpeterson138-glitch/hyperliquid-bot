// TickerBar - live price row pulled from Hyperliquid allMids.
// Polls /markets/ticker every 2s; flashes green/red on per-cell change.

import { useEffect, useRef, useState } from "react";

import { markets } from "../api/endpoints";
import type { Ticker } from "../api/endpoints";

const DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE"];
const POLL_MS = 2_000;

export function TickerBar({ symbols = DEFAULT_SYMBOLS }: { symbols?: string[] }) {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [stale, setStale] = useState(false);
  const prevRef = useRef<Map<string, number | null>>(new Map());

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await markets.tickers(symbols);
        if (cancelled) return;
        setTickers(r.tickers);
        setStale(false);
      } catch {
        if (!cancelled) setStale(true);
      }
    };
    void tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [symbols]);

  return (
    <div className={`ticker-bar ${stale ? "ticker-bar--stale" : ""}`}>
      {tickers.map((t) => {
        const prev = prevRef.current.get(t.symbol) ?? null;
        const tone =
          t.price === null || prev === null || t.price === prev
            ? undefined
            : t.price > prev
              ? "pos"
              : "neg";
        prevRef.current.set(t.symbol, t.price);
        return (
          <div key={t.symbol} className="ticker">
            <span className="ticker__sym">{t.symbol}</span>
            <span className={`ticker__price ${tone ? `tone--${tone}` : ""}`}>
              {t.price === null ? "—" : fmtPrice(t.price)}
            </span>
          </div>
        );
      })}
      {stale && <span className="muted small">stale</span>}
    </div>
  );
}

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(3);
  return p.toFixed(5);
}
