// Credentials / API keys for third-party providers.
// Hyperliquid private keys live in the OS keychain via the Vault page —
// this page handles lesser-sensitive data keys (market data providers,
// notification providers, RSS feeds, etc).

import { useCallback, useEffect, useState } from "react";

import { credentials } from "../api/endpoints";
import type { Credential } from "../api/endpoints";

const PROVIDERS = [
  "binance",
  "coinbase",
  "alpha_vantage",
  "polygon",
  "twelve_data",
  "cryptocompare",
  "coingecko",
  "messari",
  "telegram",
  "email",
  "rss",
  "other",
];

export function APIKeysPage() {
  const [items, setItems] = useState<Credential[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    provider: "binance",
    label: "",
    api_key: "",
    api_secret: "",
  });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    credentials.list().then(setItems).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      await credentials.create({
        provider: form.provider,
        label: form.label || undefined,
        api_key: form.api_key || undefined,
        api_secret: form.api_secret || undefined,
      });
      setForm({ provider: "binance", label: "", api_key: "", api_secret: "" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const del = async (id: string) => {
    if (!confirm("Delete this API key?")) return;
    await credentials.delete(id);
    refresh();
  };

  return (
    <div className="page">
      <h1 className="page__title">API Keys</h1>

      <section className="card">
        <h2 className="card__title">Add credential</h2>
        <p className="muted small">
          Store API keys for third-party data + notification providers here.
          <b> Hyperliquid trading keys</b> go through the <a href="/vault">Vault</a> page
          so they land in the OS keychain — never in this table.
        </p>
        <div className="chart-toolbar">
          <label className="field">
            <span>Provider</span>
            <select
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
            >
              {PROVIDERS.map((p) => <option key={p}>{p}</option>)}
            </select>
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>Label (optional)</span>
            <input
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="main read key"
            />
          </label>
        </div>
        <div className="chart-toolbar">
          <label className="field" style={{ flex: 1 }}>
            <span>API key</span>
            <input
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              type="password"
            />
          </label>
          <label className="field" style={{ flex: 1 }}>
            <span>Secret (optional)</span>
            <input
              value={form.api_secret}
              onChange={(e) => setForm({ ...form, api_secret: e.target.value })}
              type="password"
            />
          </label>
          <button onClick={add} disabled={busy || !form.api_key}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
        {error && <div className="error small">{error}</div>}
      </section>

      <section className="card">
        <h2 className="card__title">Stored credentials ({items.length})</h2>
        {items.length === 0 ? (
          <p className="muted">None stored yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Label</th>
                <th>Key (masked)</th>
                <th>Secret</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td><span className="badge">{c.provider}</span></td>
                  <td>{c.label ?? "—"}</td>
                  <td className="muted small">{c.api_key ?? "—"}</td>
                  <td className="muted small">{c.api_secret ?? "—"}</td>
                  <td className="muted small">{c.updated_at?.slice(0, 19).replace("T", " ")}</td>
                  <td><button onClick={() => del(c.id)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
