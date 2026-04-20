// HIP-4 outcome workspace — Phase 6 shell.
//
// Left rail: outcome board (category-grouped list of active markets,
// subcategory filter). Right pane: per-market detail view — probability
// curve from the tape API, pricing-model edge snapshot, and the resolution
// header. Slot deployment + live WS + order panel land in Phase 6 later.

import { useCallback, useEffect, useMemo, useState } from "react";

import { outcomes } from "../api/endpoints";
import { ApiError } from "../api/client";
import { ProbabilityChart } from "../components/ProbabilityChart";
import type { Market, OutcomeEdge, OutcomeTick } from "../api/types";

const DEFAULT_LOOKBACK_DAYS = 14;

const SUBCATEGORIES = [
  { key: null, label: "All" },
  { key: "politics", label: "Politics" },
  { key: "sports", label: "Sports" },
  { key: "crypto", label: "Crypto" },
  { key: "macro", label: "Macro" },
] as const;

export function OutcomesPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [subcategory, setSubcategory] = useState<string | null>(null);
  const [marketsError, setMarketsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = useMemo(
    () => markets.find((m) => m.id === selectedId) ?? null,
    [markets, selectedId],
  );

  const loadMarkets = useCallback(() => {
    setMarketsError(null);
    outcomes
      .list({ subcategory: subcategory ?? undefined })
      .then((r) => {
        setMarkets(r.markets);
        if (r.markets.length > 0) {
          setSelectedId((prev) =>
            prev && r.markets.some((m) => m.id === prev) ? prev : r.markets[0].id,
          );
        } else {
          setSelectedId(null);
        }
      })
      .catch((e) => {
        const err = e as ApiError;
        if (err.status === 503) {
          setMarketsError(
            "Outcome discovery is not wired yet — run /universe/refresh with the outcome client configured.",
          );
        } else {
          setMarketsError(err.message);
        }
        setMarkets([]);
      });
  }, [subcategory]);

  useEffect(() => {
    loadMarkets();
  }, [loadMarkets]);

  return (
    <div className="page">
      <h1 className="page__title">Outcomes</h1>

      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <div className="outcomes-board__header">
            <h2 className="card__title">HIP-4 Markets</h2>
            <button onClick={loadMarkets} className="ghost" title="Refresh">
              ↻
            </button>
          </div>
          <div className="chip-row">
            {SUBCATEGORIES.map((c) => (
              <button
                key={c.key ?? "all"}
                className={`chip ${subcategory === c.key ? "chip--active" : ""}`}
                onClick={() => setSubcategory(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
          {marketsError ? (
            <div className="error small">{marketsError}</div>
          ) : markets.length === 0 ? (
            <p className="muted">No active outcome markets.</p>
          ) : (
            <ul className="market-list">
              {markets.map((m) => (
                <MarketListItem
                  key={m.id}
                  market={m}
                  selected={m.id === selectedId}
                  onClick={() => setSelectedId(m.id)}
                />
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          {selected ? (
            <OutcomeDetail market={selected} />
          ) : (
            <div className="card">
              <p className="muted">Select a market to view its probability curve and pricing-model edge.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function MarketListItem({
  market,
  selected,
  onClick,
}: {
  market: Market;
  selected: boolean;
  onClick: () => void;
}) {
  const resolves = market.resolution_date
    ? new Date(market.resolution_date).toLocaleDateString()
    : null;
  return (
    <li className={`market-list__item ${selected ? "is-selected" : ""}`}>
      <button onClick={onClick}>
        <span className="market-list__sym">{market.symbol}</span>
        <span className="market-list__meta muted small">
          {market.subcategory ?? "—"}
          {resolves ? ` · resolves ${resolves}` : ""}
        </span>
      </button>
    </li>
  );
}

function OutcomeDetail({ market }: { market: Market }) {
  const [ticks, setTicks] = useState<OutcomeTick[]>([]);
  const [tapeError, setTapeError] = useState<string | null>(null);
  const [edge, setEdge] = useState<OutcomeEdge | null>(null);
  const [edgeError, setEdgeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setTapeError(null);
    setEdgeError(null);

    const to = new Date();
    const from = new Date(to.getTime() - DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000);

    outcomes
      .tape(market.id, from.toISOString(), to.toISOString())
      .then((r) => {
        if (!cancelled) setTicks(r.ticks);
      })
      .catch((e) => {
        if (!cancelled) {
          setTicks([]);
          setTapeError((e as Error).message);
        }
      })
      .finally(() => !cancelled && setLoading(false));

    outcomes
      .edge(market.id)
      .then((r) => {
        if (!cancelled) setEdge(r);
      })
      .catch((e) => {
        if (!cancelled) {
          const err = e as ApiError;
          setEdge(null);
          if (err.status === 503) {
            setEdgeError("Pricing model is not wired yet.");
          } else if (err.status === 404) {
            setEdgeError("No edge available (not a price-binary outcome).");
          } else {
            setEdgeError(err.message);
          }
        }
      });

    return () => {
      cancelled = true;
    };
  }, [market.id]);

  const resolves = market.resolution_date
    ? new Date(market.resolution_date)
    : null;
  const daysToResolve = resolves
    ? Math.max(0, Math.ceil((resolves.getTime() - Date.now()) / (24 * 3600 * 1000)))
    : null;

  const lastProb = ticks.length > 0 ? ticks[ticks.length - 1].implied_prob : null;

  return (
    <div className="outcome-detail">
      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">{market.symbol}</h2>
            <div className="muted small">
              {market.id}
              {market.subcategory ? ` · ${market.subcategory}` : ""}
            </div>
          </div>
          <div className="outcome-header__stats">
            {lastProb !== null && (
              <Stat label="Market" value={`${(lastProb * 100).toFixed(1)}%`} />
            )}
            {edge?.theoretical_prob_yes !== null && edge?.theoretical_prob_yes !== undefined && (
              <Stat
                label="Theory"
                value={`${(edge.theoretical_prob_yes * 100).toFixed(1)}%`}
              />
            )}
            {edge?.edge_yes !== null && edge?.edge_yes !== undefined && (
              <Stat
                label="Edge"
                value={`${edge.edge_yes >= 0 ? "+" : ""}${(edge.edge_yes * 100).toFixed(1)}%`}
                tone={edge.edge_yes >= 0 ? "pos" : "neg"}
              />
            )}
            {daysToResolve !== null && (
              <Stat label="Resolves in" value={`${daysToResolve}d`} />
            )}
          </div>
        </div>
      </section>

      <section className="card">
        <h3 className="card__title">Probability curve (last {DEFAULT_LOOKBACK_DAYS} days)</h3>
        {loading ? (
          <p className="muted">Loading tape…</p>
        ) : tapeError ? (
          <div className="error small">{tapeError}</div>
        ) : ticks.length === 0 ? (
          <p className="muted">
            No tape history for this market yet. The outcome tape is populated
            by the HIP-4 data source; seed with a backfill run.
          </p>
        ) : (
          <ProbabilityChart
            ticks={ticks}
            theoretical={edge?.theoretical_prob_yes ?? null}
          />
        )}
      </section>

      <section className="card">
        <h3 className="card__title">Pricing model</h3>
        {edgeError ? (
          <p className="muted">{edgeError}</p>
        ) : edge ? (
          <table className="table">
            <tbody>
              <Row label="Underlying" value={edge.underlying} />
              <Row label="Target" value={edge.target_price?.toLocaleString()} />
              <Row label="Spot" value={edge.spot?.toLocaleString()} />
              <Row label="Time to expiry" value={fmtYears(edge.t_years)} />
              <Row
                label="Volatility"
                value={
                  edge.vol_used !== null && edge.vol_used !== undefined
                    ? `${(edge.vol_used * 100).toFixed(1)}% (${edge.vol_source ?? "—"})`
                    : "—"
                }
              />
              <Row
                label="Theoretical P(Yes)"
                value={fmtProb(edge.theoretical_prob_yes)}
              />
              <Row label="Market Yes" value={fmtProb(edge.market_yes)} />
              <Row
                label="Edge (Yes)"
                value={fmtProb(edge.edge_yes, true)}
                tone={
                  edge.edge_yes === null || edge.edge_yes === undefined
                    ? undefined
                    : edge.edge_yes >= 0
                    ? "pos"
                    : "neg"
                }
              />
              <Row label="Implied vol" value={fmtProb(edge.implied_vol)} />
            </tbody>
          </table>
        ) : (
          <p className="muted">Loading edge…</p>
        )}
      </section>

      <section className="card">
        <h3 className="card__title">Next up</h3>
        <ul className="muted small">
          <li>Live order book + tick stream via <code>/stream/outcomes</code>.</li>
          <li>Deploy <code>outcome_arb</code> as an outcome slot with Kelly sizing from the edge panel.</li>
          <li>News feed filtered by event tags.</li>
        </ul>
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

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | null | undefined;
  tone?: "pos" | "neg";
}) {
  return (
    <tr>
      <td className="muted small">{label}</td>
      <td className={tone ? `tone--${tone}` : ""}>{value ?? "—"}</td>
    </tr>
  );
}

function fmtProb(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = signed && v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function fmtYears(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v < 1 / 365) return "<1 day";
  if (v < 1 / 12) return `${(v * 365).toFixed(1)} days`;
  if (v < 1) return `${(v * 12).toFixed(1)} months`;
  return `${v.toFixed(2)} yr`;
}
