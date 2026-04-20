// Data Lab - browse the Parquet data lake at a glance, preview each
// (symbol, interval) entry with a mini candle chart, and trigger a
// backfill range from the UI. Also exposes catalog export for any row.
//
// This is the tab for "where is my data and did it actually land?".

import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { candles } from "../api/endpoints";
import type { CandlesResponse } from "../api/types";

interface CatalogEntry {
  symbol: string;
  interval: string;
  earliest: string | null;
  latest: string | null;
  bar_count: number;
  source_count: number;
}

export function DataLabPage() {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [selected, setSelected] = useState<CatalogEntry | null>(null);
  const [filterSym, setFilterSym] = useState("");
  const [filterInterval, setFilterInterval] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshCatalog = useCallback(() => {
    api
      .get<{ entries: CatalogEntry[] }>("/catalog")
      .then((r) => setEntries(r.entries))
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    refreshCatalog();
  }, [refreshCatalog]);

  const filtered = useMemo(() => {
    return entries.filter(
      (e) =>
        e.symbol.toLowerCase().includes(filterSym.toLowerCase()) &&
        (filterInterval === "" || e.interval === filterInterval),
    );
  }, [entries, filterSym, filterInterval]);

  const intervals = useMemo(
    () => [...new Set(entries.map((e) => e.interval))].sort(),
    [entries],
  );

  const totalBars = useMemo(
    () => entries.reduce((s, e) => s + e.bar_count, 0),
    [entries],
  );
  const uniqueSymbols = useMemo(
    () => new Set(entries.map((e) => e.symbol)).size,
    [entries],
  );

  const totalMB = totalBars * 200 / (1024 * 1024); // rough: ~200 bytes/bar

  return (
    <div className="page">
      <h1 className="page__title">Data Lab</h1>

      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">Lake overview</h2>
            <div className="muted small">
              Hive-partitioned Parquet under <code>data/parquet/ohlcv/</code>.
              Auto-backfills on first chart open; fine-grained backfills
              available below.
            </div>
          </div>
          <div className="outcome-header__stats">
            <Stat label="Symbols" value={String(uniqueSymbols)} />
            <Stat label="(Sym × Interval)" value={String(entries.length)} />
            <Stat label="Total bars" value={totalBars.toLocaleString()} />
            <Stat label="≈ disk" value={`${totalMB.toFixed(1)} MB`} />
          </div>
        </div>
      </section>

      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <div className="outcomes-board__header">
            <h2 className="card__title">Catalog</h2>
            <button onClick={refreshCatalog}>↻</button>
          </div>
          <div className="chart-toolbar" style={{ margin: "0 0 8px" }}>
            <label className="field" style={{ flex: 1 }}>
              <span>Symbol</span>
              <input value={filterSym} onChange={(e) => setFilterSym(e.target.value)} placeholder="btc" />
            </label>
            <label className="field">
              <span>Interval</span>
              <select value={filterInterval} onChange={(e) => setFilterInterval(e.target.value)}>
                <option value="">all</option>
                {intervals.map((i) => <option key={i}>{i}</option>)}
              </select>
            </label>
          </div>
          {error && <div className="error small">{error}</div>}
          {filtered.length === 0 ? (
            <p className="muted">No entries. Open a chart or run the backfill tool below.</p>
          ) : (
            <ul className="market-list" style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}>
              {filtered.map((e) => (
                <li
                  key={`${e.symbol}-${e.interval}`}
                  className={`market-list__item ${selected?.symbol === e.symbol && selected?.interval === e.interval ? "is-selected" : ""}`}
                >
                  <button onClick={() => setSelected(e)}>
                    <span className="market-list__sym">{e.symbol} · {e.interval}</span>
                    <span className="market-list__meta muted small">
                      {e.bar_count.toLocaleString()} bars · {e.source_count} sources
                      {e.earliest ? ` · since ${e.earliest.slice(0, 10)}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          {!selected ? (
            <div className="card"><p className="muted">Pick an entry to preview + manage.</p></div>
          ) : (
            <EntryDetail
              entry={selected}
              onBackfilled={refreshCatalog}
              busy={busy}
              setBusy={setBusy}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function EntryDetail({
  entry,
  onBackfilled,
  busy,
  setBusy,
}: {
  entry: CatalogEntry;
  onBackfilled: () => void;
  busy: boolean;
  setBusy: (b: boolean) => void;
}) {
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [backfillFrom, setBackfillFrom] = useState(() =>
    new Date(Date.now() - 365 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [backfillTo, setBackfillTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [backfillMsg, setBackfillMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const to = new Date();
    const from = new Date(to.getTime() - 30 * 24 * 3_600_000);
    setLoading(true);
    candles
      .get(entry.symbol, entry.interval, from.toISOString(), to.toISOString())
      .then((r) => !cancelled && setData(r))
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [entry.symbol, entry.interval]);

  const runBackfill = async () => {
    setBusy(true);
    setBackfillMsg(null);
    try {
      const r = await api.post<{ rows_written: number; sources_used: string[]; errors: unknown[] }>(
        "/backfill",
        {
          symbol: entry.symbol,
          interval: entry.interval,
          start: `${backfillFrom}T00:00:00Z`,
          end: `${backfillTo}T23:59:59Z`,
          allow_partial: true,
        },
      );
      setBackfillMsg(
        `Wrote ${r.rows_written} rows from ${r.sources_used.join(" + ") || "no sources"}`,
      );
      onBackfilled();
    } catch (e) {
      setBackfillMsg(`Failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const exportCSV = () => {
    if (!data) return;
    const rows = [["timestamp", "open", "high", "low", "close", "volume", "source"]];
    for (const b of data.bars) {
      rows.push([b.timestamp, String(b.open), String(b.high), String(b.low), String(b.close), String(b.volume), b.source ?? ""]);
    }
    const csv = rows.map((r) => r.map((cell) => `"${cell}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${entry.symbol}_${entry.interval}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">{entry.symbol} · {entry.interval}</h2>
            <div className="muted small">
              {entry.bar_count.toLocaleString()} bars, {entry.source_count} source(s),
              {entry.earliest ? ` earliest ${entry.earliest.slice(0, 10)},` : ""}
              {entry.latest ? ` latest ${entry.latest.slice(0, 10)}` : ""}
            </div>
          </div>
          <div className="outcome-header__stats">
            <button onClick={exportCSV} disabled={!data || data.bars.length === 0}>
              Export CSV
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <h3 className="card__title">Last 30 days preview</h3>
        {loading && <p className="muted">Loading…</p>}
        {data && data.bars.length > 0 ? (
          <MiniChart data={data} />
        ) : !loading ? (
          <p className="muted">No bars in the last 30 days. Run a backfill below.</p>
        ) : null}
        {data && Object.keys(data.source_breakdown).length > 0 && (
          <div className="muted small">
            Sources: {Object.entries(data.source_breakdown)
              .map(([k, v]) => `${k} (${v})`)
              .join(", ")}
          </div>
        )}
      </section>

      <section className="card">
        <h3 className="card__title">Backfill more history</h3>
        <div className="chart-toolbar">
          <label className="field">
            <span>From</span>
            <input type="date" value={backfillFrom} onChange={(e) => setBackfillFrom(e.target.value)} />
          </label>
          <label className="field">
            <span>To</span>
            <input type="date" value={backfillTo} onChange={(e) => setBackfillTo(e.target.value)} />
          </label>
          <button onClick={runBackfill} disabled={busy}>
            {busy ? "Pulling…" : "Run backfill"}
          </button>
        </div>
        <p className="muted small">
          Source router auto-stitches Hyperliquid + Binance + Coinbase + yfinance.
          Requests synchronously; large ranges can take 30-60 seconds.
        </p>
        {backfillMsg && <div className="small">{backfillMsg}</div>}
      </section>
    </>
  );
}

function MiniChart({ data }: { data: CandlesResponse }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth, height: 260,
      layout: { background: { color: "#0d1117" }, textColor: "#e6edf3" },
      grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#30363d" },
      rightPriceScale: { borderColor: "#30363d" },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#3fb950", downColor: "#f85149",
      borderVisible: false, wickUpColor: "#3fb950", wickDownColor: "#f85149",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const ro = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth, height: 260 }));
    ro.observe(container);
    return () => { ro.disconnect(); chart.remove(); };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) return;
    const pts: CandlestickData[] = data.bars.map((b) => ({
      time: (Math.floor(new Date(b.timestamp).getTime() / 1000) as unknown) as Time,
      open: b.open, high: b.high, low: b.low, close: b.close,
    }));
    seriesRef.current.setData(pts);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={ref} className="chart-container" />;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className="stat-inline__value">{value}</div>
    </div>
  );
}
