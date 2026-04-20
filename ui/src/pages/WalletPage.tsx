// Wallet sidebar tab — balance, positions, P&L, recent activity.

import { useCallback, useEffect, useState } from "react";

import { wallet } from "../api/endpoints";
import type { Order, WalletSummary } from "../api/endpoints";

export function WalletPage() {
  const [summary, setSummary] = useState<WalletSummary | null>(null);
  const [activity, setActivity] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    wallet.summary().then(setSummary).catch((e) => setError((e as Error).message));
    wallet.activity(25).then(setActivity).catch(() => setActivity([]));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, [refresh]);

  if (error) {
    return (
      <div className="page">
        <h1 className="page__title">Wallet</h1>
        <div className="card error">{error}</div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="page">
        <h1 className="page__title">Wallet</h1>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <div className="page">
      <h1 className="page__title">Wallet</h1>

      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">Account</h2>
            <div className="muted small">
              {summary.wallet_address ?? "no wallet unlocked"}
            </div>
          </div>
          <div className="outcome-header__stats">
            <Stat label="USDC" value={fmt(summary.usdc_balance)} />
            <Stat label="Notional" value={fmt(summary.total_notional_usd)} />
            <Stat
              label="Unrealised"
              value={fmt(summary.unrealised_pnl_usd)}
              tone={toneFor(summary.unrealised_pnl_usd)}
            />
            <Stat
              label="Realised (today)"
              value={fmt(summary.realised_pnl_session_usd)}
              tone={toneFor(summary.realised_pnl_session_usd)}
            />
            <Stat
              label="Realised (total)"
              value={fmt(summary.realised_pnl_all_time_usd)}
              tone={toneFor(summary.realised_pnl_all_time_usd)}
            />
            <Stat label="Fees paid" value={fmt(summary.fees_paid_all_time_usd)} />
            <Stat label="Open orders" value={String(summary.open_orders)} />
          </div>
        </div>
      </section>

      <section className="card">
        <h2 className="card__title">Positions ({summary.positions.length})</h2>
        {summary.positions.length === 0 ? (
          <p className="muted">No open positions.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Size (USD)</th>
                <th>Entry</th>
                <th>Unrealised P&L</th>
              </tr>
            </thead>
            <tbody>
              {summary.positions.map((p, i) => (
                <tr key={`${p.symbol}-${i}`}>
                  <td>{p.symbol}</td>
                  <td>{p.side}</td>
                  <td>{fmt(p.size_usd)}</td>
                  <td>{fmt(p.entry_price)}</td>
                  <td className={toneClass(p.unrealised_pnl_usd)}>
                    {fmt(p.unrealised_pnl_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2 className="card__title">Recent activity ({activity.length})</h2>
        {activity.length === 0 ? (
          <p className="muted">No recent orders.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Size</th>
                <th>Status</th>
                <th>Fill</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((o) => (
                <tr key={o.id}>
                  <td className="muted small">{o.id.slice(0, 10)}</td>
                  <td>{o.symbol}</td>
                  <td>{o.side}</td>
                  <td>{fmt(o.size_usd)}</td>
                  <td>{o.status}</td>
                  <td>{fmt(o.fill_price)}</td>
                  <td className="muted small">{o.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function toneFor(v: number | null | undefined): "pos" | "neg" | undefined {
  if (v === null || v === undefined || !Number.isFinite(v)) return undefined;
  if (v > 0) return "pos";
  if (v < 0) return "neg";
  return undefined;
}

function toneClass(v: number | null | undefined): string {
  const t = toneFor(v);
  return t ? `tone--${t}` : "";
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
