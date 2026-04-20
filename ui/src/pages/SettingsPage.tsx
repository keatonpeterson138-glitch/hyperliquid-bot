// Settings — tabbed pane: Exchange / Wallets / Notifications / Risk / Data / Appearance / Advanced.
// Private keys are NEVER entered here — they go through the Vault wizard
// so they land in the OS keychain without ever touching plain-text state.

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { settings, vault as vaultApi } from "../api/endpoints";
import type { AppSettings } from "../api/endpoints";

const TABS = [
  { key: "exchange", label: "Exchange" },
  { key: "wallets", label: "Wallets" },
  { key: "notifications", label: "Notifications" },
  { key: "risk", label: "Risk" },
  { key: "data", label: "Data" },
  { key: "appearance", label: "Appearance" },
  { key: "advanced", label: "Advanced" },
] as const;

type TabKey = (typeof TABS)[number]["key"];


export function SettingsPage() {
  const [tab, setTab] = useState<TabKey>("exchange");
  const [settingsState, setSettings] = useState<AppSettings | null>(null);
  const [pending, setPending] = useState<Partial<AppSettings>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    settings.get().then(setSettings).catch((e) => setError((e as Error).message));
  }, []);

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setPending((p) => ({ ...p, [key]: value }));
  };

  function effective<K extends keyof AppSettings>(key: K): AppSettings[K] | undefined {
    return (
      key in pending ? (pending as AppSettings)[key] : settingsState?.[key]
    ) as AppSettings[K] | undefined;
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await settings.patch(pending);
      setSettings(result);
      setPending({});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!settingsState) {
    return (
      <div className="page">
        <h1 className="page__title">Settings</h1>
        {error ? <div className="error">{error}</div> : <p className="muted">Loading…</p>}
      </div>
    );
  }

  return (
    <div className="page">
      <h1 className="page__title">Settings</h1>
      <div className="chip-row">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`chip ${tab === t.key ? "chip--active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section className="card">
        {tab === "exchange" && <ExchangeTab get={effective} set={set} />}
        {tab === "wallets" && <WalletsTab />}
        {tab === "notifications" && <NotificationsTab get={effective} set={set} />}
        {tab === "risk" && <RiskTab get={effective} set={set} />}
        {tab === "data" && <DataTab get={effective} set={set} />}
        {tab === "appearance" && <AppearanceTab get={effective} set={set} />}
        {tab === "advanced" && <AdvancedTab get={effective} set={set} />}
      </section>

      <div className="chart-toolbar">
        <button onClick={save} disabled={saving || Object.keys(pending).length === 0}>
          {saving ? "saving…" : "Save changes"}
        </button>
        <button onClick={() => setPending({})} disabled={Object.keys(pending).length === 0}>
          Revert
        </button>
        {error && <span className="error small">{error}</span>}
      </div>
    </div>
  );
}

interface TabProps {
  get: <K extends keyof AppSettings>(key: K) => AppSettings[K] | undefined;
  set: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void;
}

function ExchangeTab({ get, set }: TabProps) {
  return (
    <div className="settings-grid">
      <Row label="Network">
        <select
          value={get("testnet") ? "testnet" : "mainnet"}
          onChange={(e) => set("testnet", e.target.value === "testnet")}
        >
          <option value="testnet">Testnet</option>
          <option value="mainnet">Mainnet</option>
        </select>
      </Row>
      <p className="muted small">
        API keys are stored in your OS keychain via the <a href="/vault">Vault</a> wizard.
        This page never touches plaintext secrets.
      </p>
    </div>
  );
}

function WalletsTab() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<{ unlocked: boolean; wallet_address: string | null } | null>(
    null,
  );
  useEffect(() => {
    vaultApi.status().then(setStatus).catch(() => setStatus(null));
  }, []);
  return (
    <div className="settings-grid">
      <Row label="Primary wallet">
        <span className="muted">{status?.wallet_address ?? "not unlocked"}</span>
      </Row>
      <Row label="Vault">
        <button onClick={() => navigate("/vault")}>Open vault manager</button>
      </Row>
      <p className="muted small">
        Add a wallet by opening the vault, pasting your private key, and confirming the derived
        address. Keys are encrypted and stored in the OS keychain — never in this repo, never in
        <code>data/</code>, and never sent over the network.
      </p>
    </div>
  );
}

function NotificationsTab({ get, set }: TabProps) {
  return (
    <div className="settings-grid">
      <Row label="Desktop notifications">
        <Checkbox checked={!!get("desktop_notifications")} onChange={(v) => set("desktop_notifications", v)} />
      </Row>
      <Row label="Email">
        <Checkbox checked={!!get("email_enabled")} onChange={(v) => set("email_enabled", v)} />
      </Row>
      <Row label="Telegram">
        <Checkbox checked={!!get("telegram_enabled")} onChange={(v) => set("telegram_enabled", v)} />
      </Row>
      <p className="muted small">
        SMTP and Telegram bot credentials will live in the vault once the Phase 13 notification-delivery service lands.
      </p>
    </div>
  );
}

function RiskTab({ get, set }: TabProps) {
  const cap = get("aggregate_exposure_cap_usd");
  return (
    <div className="settings-grid">
      <Row label="Default stop-loss (%)">
        <input
          type="number" step="0.01"
          value={asStr(get("default_stop_loss_pct"))}
          onChange={(e) => set("default_stop_loss_pct", Number(e.target.value))}
        />
      </Row>
      <Row label="Default take-profit (%)">
        <input
          type="number" step="0.01"
          value={asStr(get("default_take_profit_pct"))}
          onChange={(e) => set("default_take_profit_pct", Number(e.target.value))}
        />
      </Row>
      <Row label="Confirm above (USD)">
        <input
          type="number" step="50"
          value={asStr(get("confirm_above_usd"))}
          onChange={(e) => set("confirm_above_usd", Number(e.target.value))}
        />
      </Row>
      <Row label="Confirm modify (%)">
        <input
          type="number" step="0.01"
          value={asStr(get("confirm_modify_pct"))}
          onChange={(e) => set("confirm_modify_pct", Number(e.target.value))}
        />
      </Row>
      <Row label="Confirm leverage above">
        <input
          type="number" step="1"
          value={asStr(get("confirm_leverage_above"))}
          onChange={(e) => set("confirm_leverage_above", Number(e.target.value))}
        />
      </Row>
      <Row label="Aggregate exposure cap (USD)">
        <input
          type="number" step="100"
          value={cap === null || cap === undefined ? "" : asStr(cap)}
          placeholder="unlimited"
          onChange={(e) => set("aggregate_exposure_cap_usd", e.target.value === "" ? null : Number(e.target.value))}
        />
      </Row>
    </div>
  );
}

function DataTab({ get, set }: TabProps) {
  return (
    <div className="settings-grid">
      <Row label="Data root">
        <input
          value={asStr(get("data_root"))}
          onChange={(e) => set("data_root", e.target.value)}
        />
      </Row>
      <Row label="Backfill throttle (ms)">
        <input
          type="number"
          value={asStr(get("backfill_throttle_ms"))}
          onChange={(e) => set("backfill_throttle_ms", Number(e.target.value))}
        />
      </Row>
      <Row label="Cross-validate threshold (%)">
        <input
          type="number" step="0.01"
          value={asStr(get("cross_validate_threshold_pct"))}
          onChange={(e) => set("cross_validate_threshold_pct", Number(e.target.value))}
        />
      </Row>
      <Row label="DuckDB cache (MB)">
        <input
          type="number"
          value={asStr(get("duckdb_cache_mb"))}
          onChange={(e) => set("duckdb_cache_mb", Number(e.target.value))}
        />
      </Row>
    </div>
  );
}

function AppearanceTab({ get, set }: TabProps) {
  return (
    <div className="settings-grid">
      <Row label="Theme">
        <select value={asStr(get("theme"))} onChange={(e) => set("theme", e.target.value)}>
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
      </Row>
      <Row label="Density">
        <select value={asStr(get("density"))} onChange={(e) => set("density", e.target.value)}>
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>
      </Row>
    </div>
  );
}

function AdvancedTab({ get, set }: TabProps) {
  return (
    <div className="settings-grid">
      <Row label="Developer mode">
        <Checkbox checked={!!get("dev_mode")} onChange={(v) => set("dev_mode", v)} />
      </Row>
      <Row label="Log level">
        <select value={asStr(get("log_level"))} onChange={(e) => set("log_level", e.target.value)}>
          {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
      </Row>
      <p className="muted small">
        Open <code>data/logs/backend.log</code> for the rotating backend log file.
      </p>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="settings-row">
      <label className="settings-row__label">{label}</label>
      <div className="settings-row__control">{children}</div>
    </div>
  );
}

function Checkbox({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />;
}

function asStr(v: unknown): string {
  if (v === null || v === undefined) return "";
  return String(v);
}
