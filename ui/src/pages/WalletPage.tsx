// Wallet sidebar tab — connects to Hyperliquid for LIVE positions +
// fill history via /wallet/positions + /wallet/fills. The address the
// app uses is persisted to settings so the endpoint doesn't need it
// passed every call.

import { useCallback, useEffect, useState } from "react";

import { wallet as walletApi } from "../api/endpoints";
import type {
  Fill,
  LivePositionsResponse,
  Order,
  WalletSummary,
} from "../api/endpoints";

export function WalletPage() {
  const [summary, setSummary] = useState<WalletSummary | null>(null);
  const [positions, setPositions] = useState<LivePositionsResponse | null>(null);
  const [fills, setFills] = useState<Fill[]>([]);
  const [activity, setActivity] = useState<Order[]>([]);
  const [addrInput, setAddrInput] = useState("");
  const [savedAddr, setSavedAddr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshLive = useCallback(() => {
    walletApi.positions()
      .then((r) => { setPositions(r); setSavedAddr(r.wallet_address); setError(null); })
      .catch((e) => setError((e as Error).message));
    walletApi.fills(undefined, 100)
      .then(setFills).catch(() => setFills([]));
  }, []);

  const refreshLocal = useCallback(() => {
    walletApi.summary().then(setSummary).catch(() => undefined);
    walletApi.activity(25).then(setActivity).catch(() => setActivity([]));
  }, []);

  useEffect(() => {
    refreshLocal();
    refreshLive();
    const id = setInterval(() => { refreshLocal(); refreshLive(); }, 10_000);
    return () => clearInterval(id);
  }, [refreshLocal, refreshLive]);

  const saveAddress = async () => {
    const v = addrInput.trim();
    if (!v) return;
    try {
      await walletApi.setAddress(v);
      setAddrInput("");
      refreshLive();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const addressIsMissing = error?.includes("no wallet_address");

  return (
    <div className="page">
      <h1 className="page__title">Wallet</h1>

      {/* Address setup banner — only shown when none is persisted */}
      {addressIsMissing && (
        <section className="card">
          <h2 className="card__title">Connect your Hyperliquid wallet</h2>
          <p className="muted small">
            Paste your master Hyperliquid wallet address below. It's saved locally
            in settings and is all we need to read your positions + trade history
            via Hyperliquid's public Info API. Trading itself (placing orders)
            requires an additional step — see the Vault page for MetaMask + agent
            wallet setup.
          </p>
          <div className="form-row">
            <input
              type="text"
              value={addrInput}
              onChange={(e) => setAddrInput(e.target.value)}
              placeholder="0x..."
              style={{ width: 460, fontFamily: "ui-monospace, monospace" }}
            />
            <button onClick={saveAddress} disabled={!addrInput.trim()}>Save</button>
          </div>
        </section>
      )}

      {!addressIsMissing && savedAddr && (
        <section className="card wallet__addr-strip">
          <span className="muted small">Tracking</span>
          <code>{savedAddr}</code>
          <button
            className="btn--subtle"
            onClick={() => { setAddrInput(savedAddr ?? ""); setSavedAddr(null); setError("no wallet_address"); }}
            style={{ marginLeft: "auto" }}
          >
            Change
          </button>
        </section>
      )}

      {error && !addressIsMissing && <div className="banner banner--error">{error}</div>}

      {/* Live HL snapshot — account value, margin, unrealized */}
      {positions && (
        <section className="card">
          <div className="outcome-header">
            <div>
              <h2 className="card__title">Live Hyperliquid account</h2>
            </div>
            <div className="outcome-header__stats">
              <Stat label="Account value" value={fmt(positions.account_value_usd)} />
              <Stat label="Notional" value={fmt(positions.total_notional_usd)} />
              <Stat label="Margin used" value={fmt(positions.total_margin_used_usd)} />
              <Stat label="Withdrawable" value={fmt(positions.withdrawable_usd)} />
              <Stat
                label="Unrealized P&L"
                value={fmtSigned(positions.unrealised_pnl_usd)}
                tone={toneFor(positions.unrealised_pnl_usd)}
              />
            </div>
          </div>
        </section>
      )}

      {/* Active positions table */}
      {positions && (
        <section className="card">
          <h2 className="card__title">
            Active positions ({positions.positions.length})
          </h2>
          {positions.positions.length === 0 ? (
            <p className="muted">No open positions.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Size</th>
                  <th>Notional</th>
                  <th>Entry</th>
                  <th>Mark</th>
                  <th>Liq</th>
                  <th>Lev</th>
                  <th>Unrealized</th>
                </tr>
              </thead>
              <tbody>
                {positions.positions.map((p) => (
                  <tr key={`${p.symbol}-${p.side}`}>
                    <td><b>{p.symbol}</b></td>
                    <td>
                      <span className={`badge ${p.side === "long" ? "badge--pos" : "badge--neg"}`}>
                        {p.side.toUpperCase()}
                      </span>
                    </td>
                    <td>{p.size.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
                    <td>${fmt(p.size_usd)}</td>
                    <td>{fmt(p.entry_price)}</td>
                    <td>{fmt(p.mark_price)}</td>
                    <td className="muted">{fmt(p.liquidation_price)}</td>
                    <td className="muted">{p.leverage ? `${p.leverage}×` : "—"}</td>
                    <td className={toneClass(p.unrealised_pnl_usd)}>
                      {fmtSigned(p.unrealised_pnl_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {/* Live fill history */}
      <section className="card">
        <h2 className="card__title">
          Trade history ({fills.length} most recent)
        </h2>
        {fills.length === 0 ? (
          <p className="muted">No fills yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Size</th>
                <th>Price</th>
                <th>Closed P&L</th>
                <th>Fee</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {fills.map((f) => (
                <tr key={`${f.oid}-${f.timestamp}`}>
                  <td className="muted small">{new Date(f.timestamp).toLocaleString()}</td>
                  <td><b>{f.symbol}</b></td>
                  <td>
                    <span className={`badge ${f.side === "long" ? "badge--pos" : "badge--neg"}`}>
                      {f.side.toUpperCase()}
                    </span>
                  </td>
                  <td>{f.sz.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
                  <td>{fmt(f.px)}</td>
                  <td className={toneClass(f.closed_pnl_usd)}>
                    {f.closed_pnl_usd !== null ? fmtSigned(f.closed_pnl_usd) : "—"}
                  </td>
                  <td className="muted">${fmt(f.fee_usd)}</td>
                  <td className="muted small">{f.is_close ? "CLOSE" : "OPEN"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Local order activity (what the bot placed — may differ from HL fills) */}
      {summary && (
        <section className="card">
          <h2 className="card__title">Local orders ({activity.length})</h2>
          {activity.length === 0 ? (
            <p className="muted">No local orders recorded.</p>
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
      )}
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtSigned(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
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
  label, value, tone,
}: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className={`stat-inline__value ${tone ? `tone--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
