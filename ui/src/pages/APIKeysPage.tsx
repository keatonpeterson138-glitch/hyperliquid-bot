// Credentials / API keys for third-party providers.
// Hyperliquid private keys live in the OS keychain via the Vault page —
// this page handles lesser-sensitive data keys (market data providers,
// notification providers, RSS feeds, Plaid/E*Trade OAuth etc.).
//
// Export/Import profile lands a plain-JSON blob to disk so the user can
// rehydrate after reinstalling — per the user's ask, local-only, unencrypted,
// will be upgraded later.

import { useCallback, useEffect, useRef, useState } from "react";

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
  "fred",
  "plaid",
  "etrade",
  "other",
];

const PROVIDER_HINTS: Record<string, string> = {
  plaid: 'metadata: {"environment": "sandbox"} or {"environment": "production"}',
  etrade: 'metadata: {"sandbox": true} to use sandbox env',
  telegram: 'metadata: {"channel": "@your_channel"} for the Live Squawk feed',
  alpha_vantage: "Free tier is 25 req/day, last 100 daily bars.",
  fred: "Free tier; add api_key only (no secret).",
  coingecko: "Free tier needs no key; skip this unless you paid for Pro.",
};

export function APIKeysPage() {
  const [items, setItems] = useState<Credential[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [form, setForm] = useState({
    provider: "binance",
    label: "",
    api_key: "",
    api_secret: "",
    metadata: "",  // JSON string — parsed on submit
  });
  const [busy, setBusy] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    credentials.list().then(setItems).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const add = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      let metadata: Record<string, unknown> | undefined;
      if (form.metadata.trim()) {
        try {
          metadata = JSON.parse(form.metadata);
        } catch {
          throw new Error("Metadata must be valid JSON (or leave it empty).");
        }
      }
      await credentials.create({
        provider: form.provider,
        label: form.label || undefined,
        api_key: form.api_key || undefined,
        api_secret: form.api_secret || undefined,
        metadata,
      });
      setForm({ provider: form.provider, label: "", api_key: "", api_secret: "", metadata: "" });
      refresh();
      setInfo("Saved.");
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

  const exportProfile = useCallback(async () => {
    setError(null);
    try {
      const blob = await credentials.exportProfile();
      const json = JSON.stringify(blob, null, 2);
      const file = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(file);
      const a = document.createElement("a");
      a.href = url;
      a.download = `hyperliquid-bot-keys-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setInfo(`Exported ${blob.credentials.length} credential(s).`);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const pickFile = () => fileInputRef.current?.click();

  const importProfile = async (file: File, replace: boolean) => {
    setError(null);
    setInfo(null);
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      const res = await credentials.importProfile(payload, replace);
      setInfo(`Imported — created ${res.created}, updated ${res.updated}, skipped ${res.skipped}.`);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const currentHint = PROVIDER_HINTS[form.provider];

  return (
    <div className="page">
      <h1 className="page__title">API Keys</h1>

      <section className="card">
        <h2 className="card__title">Add credential</h2>
        <p className="muted small">
          Store API keys for third-party data + notification providers here.
          <b> Hyperliquid trading keys</b> go through the <a href="#/vault">Vault</a> page
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
        </div>
        <div className="chart-toolbar">
          <label className="field" style={{ flex: 1 }}>
            <span>Metadata (JSON, optional)</span>
            <input
              value={form.metadata}
              onChange={(e) => setForm({ ...form, metadata: e.target.value })}
              placeholder='{"environment": "sandbox"}'
              style={{ fontFamily: "ui-monospace, monospace" }}
            />
          </label>
          <button onClick={add} disabled={busy || !form.api_key}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
        {currentHint && <div className="muted small">{currentHint}</div>}
        {error && <div className="error small">{error}</div>}
        {info && <div className="muted small">{info}</div>}
      </section>

      <section className="card">
        <div className="card__header">
          <h2 className="card__title">Backup & restore</h2>
          <div className="card__header-actions">
            <button onClick={exportProfile}>Export profile (JSON)</button>
            <button onClick={pickFile}>Import profile…</button>
          </div>
        </div>
        <p className="muted small">
          Export downloads a plain-text JSON of every stored credential (api_key,
          api_secret, metadata). Keep the file safe — anyone with it has all your keys.
          Import hydrates this machine from that file; existing entries with the
          same provider+label are updated in place.
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const replace = confirm(
              "Replace all existing credentials with the imported ones?\n" +
              "OK = wipe + import. Cancel = merge (updates matching entries, keeps the rest).",
            );
            importProfile(f, replace).finally(() => {
              if (fileInputRef.current) fileInputRef.current.value = "";
            });
          }}
        />
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
                <th>Metadata</th>
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
                  <td className="muted small" style={{ fontFamily: "ui-monospace, monospace" }}>
                    {c.metadata && Object.keys(c.metadata).length > 0
                      ? JSON.stringify(c.metadata)
                      : "—"}
                  </td>
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
