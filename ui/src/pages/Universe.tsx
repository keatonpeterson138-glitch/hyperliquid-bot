import { useEffect, useState } from "react";

import { universe } from "../api/endpoints";
import type { Market } from "../api/types";

export function UniversePage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    universe
      .list({ active_only: true })
      .then((r) => setMarkets(r.markets))
      .catch((e) => setError((e as Error).message));

  useEffect(() => {
    refresh();
  }, []);

  const handleRefresh = async () => {
    setError(null);
    setBusy(true);
    try {
      const result = await universe.refresh();
      alert(
        `Universe refreshed.\n` +
          `+${result.markets_added} new · ${result.markets_reactivated} reactivated · ` +
          `${result.markets_deactivated} deactivated · ${result.markets_total} total`,
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const filtered = filter
    ? markets.filter((m) =>
        m.symbol.toLowerCase().includes(filter.toLowerCase()) ||
        (m.category ?? "").toLowerCase().includes(filter.toLowerCase()),
      )
    : markets;

  const byCategory: Record<string, Market[]> = {};
  for (const m of filtered) {
    const cat = m.category ?? "other";
    (byCategory[cat] ??= []).push(m);
  }

  return (
    <div className="page">
      <h1 className="page__title">Universe</h1>

      <section className="toolbar">
        <input
          className="filter"
          placeholder="Filter by symbol or category…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button onClick={handleRefresh} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh from Hyperliquid"}
        </button>
        <span className="muted">{filtered.length} of {markets.length}</span>
      </section>

      {error ? <div className="error">{error}</div> : null}

      {Object.entries(byCategory).map(([cat, list]) => (
        <section key={cat} className="card">
          <h2 className="card__title">
            {cat} <span className="badge">{list.length}</span>
          </h2>
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Dex</th>
                <th>Max lev</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {list.map((m) => (
                <tr key={m.id}>
                  <td>{m.symbol}</td>
                  <td>{m.dex || "—"}</td>
                  <td>{m.max_leverage ?? "—"}</td>
                  <td>{m.tags.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
