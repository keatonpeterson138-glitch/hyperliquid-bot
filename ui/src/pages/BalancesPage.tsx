// Per-broker equity ledger. Wires the three connection paths:
//
//   * Plaid (universal) — links any bank/brokerage via Plaid Link, then
//     auto-pulls balances on every /balances/refresh.
//   * E*Trade (direct OAuth 1.0a) — browser-based verifier code flow.
//   * Manual (fallback for every other broker).
//
// The top section aggregates every connected source into a single
// "total equity" number + a card per broker showing the latest snapshot.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePlaidLink } from "react-plaid-link";

import {
  balances as balancesApi,
  credentials as credsApi,
  etrade as etradeApi,
  plaid as plaidApi,
  type BalanceSnapshot,
  type BalanceSummary,
  type Credential,
  type ETradeSession,
  type PlaidAccount,
  type PlaidItem,
} from "../api/endpoints";

const USD = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

const BROKER_LABELS: Record<string, string> = {
  hyperliquid: "Hyperliquid",
  coinbase: "Coinbase",
  kraken: "Kraken",
  robinhood: "Robinhood",
  etrade: "E*Trade",
  fidelity: "Fidelity",
  schwab: "Schwab",
  binance: "Binance",
  ibkr: "Interactive Brokers",
  other: "Other",
};

function prettyBroker(b: string) {
  return BROKER_LABELS[b] || b;
}

export function BalancesPage() {
  const [summary, setSummary] = useState<BalanceSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setSummary(await balancesApi.summary());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const refreshAll = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      await balancesApi.refresh();
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [reload]);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Balances</h1>
          <p className="page__subtitle">End-of-day equity per broker. Plaid + E*Trade auto-pull; rest are manual.</p>
        </div>
        <div className="page__actions">
          <button className="btn" onClick={refreshAll} disabled={busy}>
            {busy ? "Refreshing…" : "Refresh all"}
          </button>
        </div>
      </header>

      {err && <div className="banner banner--error">{err}</div>}

      <section className="card">
        <div className="balances__summary">
          <div className="balances__total">
            <div className="balances__total-label">Total equity</div>
            <div className="balances__total-value">{USD(summary?.total_equity_usd ?? 0)}</div>
          </div>
          <div className="balances__snapshots">
            {!summary || summary.per_broker.length === 0 ? (
              <div className="muted">No snapshots yet. Link Plaid/E*Trade or enter a broker manually below.</div>
            ) : (
              summary.per_broker.map((s) => <BrokerCard key={s.id} snap={s} onChange={reload} />)
            )}
          </div>
        </div>
      </section>

      <PlaidSection onUpdate={reload} />
      <ETradeSection onUpdate={reload} />
      <ManualEntrySection onUpdate={reload} />
    </div>
  );
}

function BrokerCard({ snap, onChange }: { snap: BalanceSnapshot; onChange: () => void | Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="balances__card">
      <div className="balances__card-head">
        <strong>{prettyBroker(snap.broker)}</strong>
        <span className="muted">{snap.source_note}</span>
      </div>
      <div className="balances__card-equity">{USD(snap.equity_usd)}</div>
      <div className="balances__card-meta">
        <span>Cash: {USD(snap.cash_usd)}</span>
        <span>Asof: {new Date(snap.asof).toLocaleString()}</span>
      </div>
      {confirming ? (
        <div className="balances__card-actions">
          <button
            className="btn btn--danger btn--small"
            onClick={async () => {
              if (snap.id !== null) await balancesApi.delete(snap.id);
              await onChange();
            }}
          >
            Delete snapshot
          </button>
          <button className="btn btn--small" onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <div className="balances__card-actions">
          <button className="btn btn--link btn--small" onClick={() => setConfirming(true)}>Remove</button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Plaid
// ─────────────────────────────────────────────────────────────────

function PlaidSection({ onUpdate }: { onUpdate: () => void | Promise<void> }) {
  const [creds, setCreds] = useState<Credential[] | null>(null);
  const [items, setItems] = useState<PlaidItem[]>([]);
  const [accounts, setAccounts] = useState<PlaidAccount[]>([]);
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [c, it, acc] = await Promise.all([
        credsApi.list("plaid"),
        plaidApi.listItems().catch(() => [] as PlaidItem[]),
        plaidApi.listAccounts().catch(() => [] as PlaidAccount[]),
      ]);
      setCreds(c);
      setItems(it);
      setAccounts(acc);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const kickoffLink = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await plaidApi.createLinkToken({});
      setLinkToken(r.link_token);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const onPlaidSuccess = useCallback(async (public_token: string) => {
    try {
      await plaidApi.exchange(public_token);
      setLinkToken(null);
      await reload();
      await onUpdate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [reload, onUpdate]);

  const plaidConfig = useMemo(
    () => ({
      token: linkToken,
      onSuccess: (public_token: string) => { void onPlaidSuccess(public_token); },
      onExit: (error: unknown) => {
        if (error) setErr(String(error));
        setLinkToken(null);
      },
    }),
    [linkToken, onPlaidSuccess],
  );

  const { open, ready } = usePlaidLink(plaidConfig);

  useEffect(() => {
    if (linkToken && ready) open();
  }, [linkToken, ready, open]);

  const sandboxQuick = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      await plaidApi.sandboxQuickLink();
      await reload();
      await onUpdate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [reload, onUpdate]);

  const hasCreds = (creds?.length ?? 0) > 0;
  const sandbox = (creds?.[0]?.metadata as Record<string, unknown> | undefined)?.environment === "sandbox";

  return (
    <section className="card">
      <header className="card__header">
        <div>
          <h2>Plaid</h2>
          <p className="muted">Universal bank/broker link — Fidelity, Robinhood, Chase, etc.</p>
        </div>
        {hasCreds && (
          <div className="card__header-actions">
            <button className="btn" onClick={kickoffLink} disabled={busy || !!linkToken}>
              {linkToken ? "Opening Plaid…" : "Link institution"}
            </button>
            {sandbox && (
              <button className="btn btn--subtle" onClick={sandboxQuick} disabled={busy}>
                Sandbox quick-link
              </button>
            )}
          </div>
        )}
      </header>

      {err && <div className="banner banner--error">{err}</div>}

      {!hasCreds && (
        <div className="banner">
          Plaid isn't configured yet. Add provider <code>plaid</code> in
          {" "}
          <a href="#/apikeys">Sidebar → API Keys</a>
          {" "}
          with your <code>PLAID_CLIENT_ID</code> as api_key, <code>PLAID_SECRET</code> as api_secret,
          and metadata <code>{"{ \"environment\": \"sandbox\" }"}</code> or <code>{"{ \"environment\": \"production\" }"}</code>.
        </div>
      )}

      {items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Institution</th>
                <th>Account</th>
                <th>Type</th>
                <th>Broker label</th>
                <th>Tracked</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td>{a.institution_name || "—"}</td>
                  <td>
                    {a.name || a.official_name}
                    {a.mask ? <span className="muted"> ••••{a.mask}</span> : null}
                  </td>
                  <td>{a.subtype || a.type || "—"}</td>
                  <td>
                    <select
                      value={a.broker_label || "other"}
                      onChange={async (e) => {
                        await plaidApi.updateAccount(a.id, { broker_label: e.target.value });
                        await reload();
                      }}
                    >
                      {Object.keys(BROKER_LABELS).map((k) => (
                        <option key={k} value={k}>{BROKER_LABELS[k]}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={a.tracked}
                      onChange={async (e) => {
                        await plaidApi.updateAccount(a.id, { tracked: e.target.checked });
                        await reload();
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="card__footer">
            {items.map((it) => (
              <button
                key={it.id}
                className="btn btn--link btn--small"
                onClick={async () => {
                  if (!confirm(`Remove ${it.institution_name || "item"}?`)) return;
                  await plaidApi.deleteItem(it.id);
                  await reload();
                  await onUpdate();
                }}
              >
                Remove {it.institution_name || it.plaid_item_id}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// E*Trade
// ─────────────────────────────────────────────────────────────────

function ETradeSection({ onUpdate }: { onUpdate: () => void | Promise<void> }) {
  const [creds, setCreds] = useState<Credential[] | null>(null);
  const [session, setSession] = useState<ETradeSession | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Link flow state
  const linkState = useRef<{ request_token: string; request_token_secret: string } | null>(null);
  const [authorizeUrl, setAuthorizeUrl] = useState<string | null>(null);
  const [verifier, setVerifier] = useState("");

  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        credsApi.list("etrade"),
        etradeApi.session().catch(() => ({ connected: false, sandbox: false, accounts: [], last_refreshed_at: null } as ETradeSession)),
      ]);
      setCreds(c);
      setSession(s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const start = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await etradeApi.linkStart();
      linkState.current = { request_token: r.request_token, request_token_secret: r.request_token_secret };
      setAuthorizeUrl(r.authorize_url);
      try { window.open(r.authorize_url, "_blank", "noopener,noreferrer"); } catch { /* browser blocked */ }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const complete = useCallback(async () => {
    if (!linkState.current || !verifier.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await etradeApi.linkComplete({
        request_token: linkState.current.request_token,
        request_token_secret: linkState.current.request_token_secret,
        verifier: verifier.trim(),
      });
      setAuthorizeUrl(null);
      setVerifier("");
      linkState.current = null;
      await reload();
      await onUpdate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [verifier, reload, onUpdate]);

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      await etradeApi.refresh();
      await reload();
      await onUpdate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [reload, onUpdate]);

  const disconnect = useCallback(async () => {
    if (!confirm("Disconnect E*Trade? Access tokens will be wiped; consumer key/secret stay.")) return;
    setBusy(true);
    try {
      await etradeApi.disconnect();
      await reload();
      await onUpdate();
    } finally {
      setBusy(false);
    }
  }, [reload, onUpdate]);

  const hasCreds = (creds?.length ?? 0) > 0;

  return (
    <section className="card">
      <header className="card__header">
        <div>
          <h2>E*Trade</h2>
          <p className="muted">Official OAuth 1.0a API. Consumer key/secret → browser verify → long-lived access.</p>
        </div>
        <div className="card__header-actions">
          {hasCreds && session?.connected && (
            <>
              <button className="btn" onClick={refresh} disabled={busy}>Refresh balances</button>
              <button className="btn btn--subtle" onClick={disconnect} disabled={busy}>Disconnect</button>
            </>
          )}
          {hasCreds && !session?.connected && (
            <button className="btn" onClick={start} disabled={busy || !!authorizeUrl}>
              {authorizeUrl ? "Waiting for verifier…" : "Start link"}
            </button>
          )}
        </div>
      </header>

      {err && <div className="banner banner--error">{err}</div>}

      {!hasCreds && (
        <div className="banner">
          E*Trade API keys aren't set up. Register an app at <code>developer.etrade.com</code>,
          then add provider <code>etrade</code> in
          {" "}
          <a href="#/apikeys">Sidebar → API Keys</a>
          {" "}
          with api_key=consumer key, api_secret=consumer secret.
          To use sandbox, set metadata <code>{"{ \"sandbox\": true }"}</code>.
        </div>
      )}

      {authorizeUrl && (
        <div className="banner">
          <p>
            A new tab should have opened to E*Trade's authorize page. If it didn't,{" "}
            <a href={authorizeUrl} target="_blank" rel="noopener noreferrer">click here</a>.
            Sign in, confirm, copy the 5-char verifier code, and paste it below.
          </p>
          <div className="form-row">
            <input
              type="text"
              maxLength={10}
              value={verifier}
              onChange={(e) => setVerifier(e.target.value)}
              placeholder="Verifier code"
              style={{ width: 160, fontFamily: "ui-monospace, monospace", letterSpacing: 2 }}
            />
            <button className="btn" onClick={complete} disabled={busy || !verifier.trim()}>
              {busy ? "Finishing…" : "Finish link"}
            </button>
          </div>
        </div>
      )}

      {session?.connected && session.accounts.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Type</th>
                <th>ID</th>
                <th>Tracked</th>
              </tr>
            </thead>
            <tbody>
              {session.accounts.map((a) => (
                <tr key={a.accountIdKey}>
                  <td>{a.accountDesc}</td>
                  <td>{a.accountType}</td>
                  <td className="muted">{a.accountId}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={a.tracked}
                      onChange={async (e) => {
                        await etradeApi.setTracked(a.accountIdKey, e.target.checked);
                        await reload();
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {session.last_refreshed_at && (
            <div className="muted">Last refreshed {new Date(session.last_refreshed_at).toLocaleString()}</div>
          )}
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// Manual entry
// ─────────────────────────────────────────────────────────────────

function ManualEntrySection({ onUpdate }: { onUpdate: () => void | Promise<void> }) {
  const [broker, setBroker] = useState<string>("fidelity");
  const [equity, setEquity] = useState<string>("");
  const [cash, setCash] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [supported, setSupported] = useState<string[]>([]);

  useEffect(() => {
    balancesApi.supported().then(setSupported).catch(() => {});
  }, []);

  const submit = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const equity_usd = parseFloat(equity);
      if (!isFinite(equity_usd)) throw new Error("Equity must be a number");
      const cash_usd = cash.trim() ? parseFloat(cash) : undefined;
      await balancesApi.create({
        broker,
        equity_usd,
        cash_usd: cash_usd ?? undefined,
        source_note: note || "manual",
      });
      setEquity("");
      setCash("");
      setNote("");
      await onUpdate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [broker, equity, cash, note, onUpdate]);

  return (
    <section className="card">
      <header className="card__header">
        <div>
          <h2>Manual entry</h2>
          <p className="muted">For brokers without a retail API, or as a quick override.</p>
        </div>
      </header>

      {err && <div className="banner banner--error">{err}</div>}

      <div className="form-row">
        <label>
          Broker
          <select value={broker} onChange={(e) => setBroker(e.target.value)}>
            {(supported.length ? supported : Object.keys(BROKER_LABELS)).map((b) => (
              <option key={b} value={b}>{prettyBroker(b)}</option>
            ))}
          </select>
        </label>
        <label>
          Equity (USD)
          <input type="number" step="0.01" value={equity} onChange={(e) => setEquity(e.target.value)} placeholder="12500.00" />
        </label>
        <label>
          Cash (optional)
          <input type="number" step="0.01" value={cash} onChange={(e) => setCash(e.target.value)} placeholder="200.00" />
        </label>
        <label>
          Note
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="manual" />
        </label>
        <button className="btn" onClick={submit} disabled={busy || !equity.trim()}>
          {busy ? "Saving…" : "Record snapshot"}
        </button>
      </div>
    </section>
  );
}
