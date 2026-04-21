// Manual "place an order" panel — symbol + side + size + optional SL/TP
// + leverage. Posts to /orders which either forwards to the live exchange
// gateway (vault unlocked) or stores pending locally (gateway stubbed).
//
// Used on the Dashboard and easy to drop on any page via ``<QuickTradePanel />``.

import { useCallback, useEffect, useState } from "react";

import { markets as marketsApi, orders as ordersApi } from "../api/endpoints";

const PRESET_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB", "DOGE", "LINK"];

type Side = "long" | "short";
type EntryType = "market" | "limit";

interface Props {
  defaultSymbol?: string;
  onPlaced?: () => void;
  compact?: boolean;
}

export function QuickTradePanel({ defaultSymbol = "BTC", onPlaced, compact = false }: Props) {
  const [symbol, setSymbol] = useState<string>(defaultSymbol);
  const [symbolCatalog, setSymbolCatalog] = useState<string[]>(PRESET_SYMBOLS);
  const [side, setSide] = useState<Side>("long");
  const [sizeUsd, setSizeUsd] = useState<string>("100");
  const [entryType, setEntryType] = useState<EntryType>("market");
  const [entryPrice, setEntryPrice] = useState<string>("");
  const [slPrice, setSlPrice] = useState<string>("");
  const [tpPrice, setTpPrice] = useState<string>("");
  const [leverage, setLeverage] = useState<string>("3");
  const [markPrice, setMarkPrice] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Load the live Hyperliquid symbol catalog so the dropdown isn't
  // limited to the default eight.
  useEffect(() => {
    marketsApi.meta().then((r) => {
      const raw = r.raw as { universe?: Array<{ name?: string }> };
      const names = (raw.universe ?? [])
        .map((u) => u.name)
        .filter((n): n is string => !!n);
      if (names.length > 0) setSymbolCatalog(names);
    }).catch(() => undefined);
  }, []);

  // Live mark price via /markets/ticker — refresh every 3s.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await marketsApi.tickers([symbol]);
        if (cancelled) return;
        const t = r.tickers.find((x) => x.symbol.toUpperCase() === symbol.toUpperCase());
        if (t && t.price !== null) setMarkPrice(t.price);
      } catch {
        /* transient */
      }
    };
    tick();
    const id = window.setInterval(tick, 3000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [symbol]);

  // Quick helpers to fill SL/TP from a % offset.
  const suggestSL = useCallback((pct: number) => {
    if (!markPrice) return;
    const p = side === "long" ? markPrice * (1 - pct / 100) : markPrice * (1 + pct / 100);
    setSlPrice(p.toFixed(2));
  }, [markPrice, side]);

  const suggestTP = useCallback((pct: number) => {
    if (!markPrice) return;
    const p = side === "long" ? markPrice * (1 + pct / 100) : markPrice * (1 - pct / 100);
    setTpPrice(p.toFixed(2));
  }, [markPrice, side]);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setErr(null);
    setFeedback(null);
    try {
      const size_usd = parseFloat(sizeUsd);
      if (!(size_usd > 0)) throw new Error("Size must be > 0");
      const body: Parameters<typeof ordersApi.create>[0] = {
        symbol,
        side,
        size_usd,
        entry_type: entryType,
      };
      const lev = parseInt(leverage, 10);
      if (Number.isFinite(lev) && lev > 0) body.leverage = lev;
      if (entryType === "limit") {
        if (!entryPrice.trim()) throw new Error("Limit orders need a price");
        body.entry_price = parseFloat(entryPrice);
      }
      if (slPrice.trim()) body.sl_price = parseFloat(slPrice);
      if (tpPrice.trim()) body.tp_price = parseFloat(tpPrice);

      const order = await ordersApi.create(body);
      const status = (order as { status?: string }).status ?? "submitted";
      setFeedback(
        `Order ${status}: ${side.toUpperCase()} ${symbol} $${size_usd.toFixed(2)} ` +
        (entryType === "market" ? "@ market" : `@ ${entryPrice}`) +
        (slPrice ? `, SL ${slPrice}` : "") +
        (tpPrice ? `, TP ${tpPrice}` : ""),
      );
      setEntryPrice("");
      setSlPrice("");
      setTpPrice("");
      onPlaced?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [symbol, side, sizeUsd, entryType, entryPrice, slPrice, tpPrice, leverage, onPlaced]);

  return (
    <section className={`card quick-trade ${compact ? "quick-trade--compact" : ""}`}>
      <header className="quick-trade__head">
        <h2 className="card__title">Quick Trade</h2>
        {markPrice !== null && (
          <span className="quick-trade__mark">
            Mark <b>{markPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
          </span>
        )}
      </header>

      <div className="quick-trade__row">
        <label className="field">
          <span>Symbol</span>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {symbolCatalog.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>

        <div className="quick-trade__side">
          <button
            className={`quick-trade__side-btn ${side === "long" ? "quick-trade__side-btn--long-on" : ""}`}
            onClick={() => setSide("long")}
          >
            Long
          </button>
          <button
            className={`quick-trade__side-btn ${side === "short" ? "quick-trade__side-btn--short-on" : ""}`}
            onClick={() => setSide("short")}
          >
            Short
          </button>
        </div>
      </div>

      <div className="quick-trade__row">
        <label className="field">
          <span>Size (USD)</span>
          <input type="number" value={sizeUsd} onChange={(e) => setSizeUsd(e.target.value)} step="10" min="0" />
        </label>
        <label className="field">
          <span>Leverage</span>
          <select value={leverage} onChange={(e) => setLeverage(e.target.value)}>
            {[1, 2, 3, 5, 10, 20, 50].map((l) => <option key={l} value={l}>{l}×</option>)}
          </select>
        </label>
        <label className="field">
          <span>Type</span>
          <select value={entryType} onChange={(e) => setEntryType(e.target.value as EntryType)}>
            <option value="market">Market</option>
            <option value="limit">Limit</option>
          </select>
        </label>
        {entryType === "limit" && (
          <label className="field">
            <span>Limit price</span>
            <input
              type="number" value={entryPrice} step="0.1"
              onChange={(e) => setEntryPrice(e.target.value)}
              placeholder={markPrice ? markPrice.toFixed(2) : "price"}
            />
          </label>
        )}
      </div>

      <div className="quick-trade__row">
        <label className="field">
          <span>Stop loss</span>
          <div className="quick-trade__input-with-chips">
            <input
              type="number" value={slPrice} step="0.1"
              onChange={(e) => setSlPrice(e.target.value)}
              placeholder="price"
            />
            <div className="quick-trade__chips">
              {[0.5, 1, 2, 5].map((p) => (
                <button key={p} className="chip chip--small" onClick={() => suggestSL(p)}>-{p}%</button>
              ))}
            </div>
          </div>
        </label>
        <label className="field">
          <span>Take profit</span>
          <div className="quick-trade__input-with-chips">
            <input
              type="number" value={tpPrice} step="0.1"
              onChange={(e) => setTpPrice(e.target.value)}
              placeholder="price"
            />
            <div className="quick-trade__chips">
              {[1, 2, 3, 5, 10].map((p) => (
                <button key={p} className="chip chip--small" onClick={() => suggestTP(p)}>+{p}%</button>
              ))}
            </div>
          </div>
        </label>
      </div>

      <div className="quick-trade__submit-row">
        <button
          className={`quick-trade__submit quick-trade__submit--${side}`}
          disabled={submitting}
          onClick={submit}
        >
          {submitting
            ? "Submitting…"
            : `${side === "long" ? "BUY" : "SELL"} ${symbol} · $${sizeUsd}`}
        </button>
      </div>

      {err && <div className="banner banner--error">{err}</div>}
      {feedback && <div className="banner banner--ok">{feedback}</div>}
      <p className="muted small">
        Orders land pending until the Hyperliquid wallet is unlocked in the
        Vault (or MetaMask → agent wallet). No funds move until then.
      </p>
    </section>
  );
}
