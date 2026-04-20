// Training Lab - list trained models, train a new one, promote to a
// slot. The `ml:<model_id>` strategy-factory registration makes trained
// models first-class strategies.

import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";

interface ModelRecord {
  id: string;
  family: string;
  version: string;
  path: string;
  features: string[];
  label: string;
  metrics: Record<string, number>;
  config: Record<string, unknown>;
  promoted_slot_id: string | null;
  created_at: string | null;
}

const FAMILIES = ["logreg", "xgb_cls"];
const FEATURE_SETS = ["core_v1"];
const LABELERS = ["direction", "forward_return", "triple_barrier", "vol_adjusted_return"];

export function ModelsPage() {
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [selected, setSelected] = useState<ModelRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.get<ModelRecord[]>("/models").then(setModels).catch(() => setModels([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="page">
      <h1 className="page__title">Training Lab</h1>

      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <div className="outcomes-board__header">
            <h2 className="card__title">Models</h2>
            <button onClick={refresh}>↻</button>
          </div>
          {models.length === 0 ? (
            <p className="muted">No models trained yet.</p>
          ) : (
            <ul className="market-list">
              {models.map((m) => (
                <li
                  key={m.id}
                  className={`market-list__item ${selected?.id === m.id ? "is-selected" : ""}`}
                >
                  <button onClick={() => setSelected(m)}>
                    <span className="market-list__sym">{m.family} · {m.id.slice(0, 12)}</span>
                    <span className="market-list__meta muted small">
                      {(m.config.symbol as string) ?? "?"} ·{" "}
                      {fmt(m.metrics.oos_acc)} acc · {m.promoted_slot_id ? "promoted" : "candidate"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          <TrainForm
            onTrained={() => refresh()}
            onError={(e) => setError(e)}
          />
          {error && <div className="card error small">{error}</div>}
          {selected && <ModelDetail model={selected} onPromoted={refresh} />}
        </section>
      </div>
    </div>
  );
}

function TrainForm({
  onTrained,
  onError,
}: {
  onTrained: () => void;
  onError: (msg: string | null) => void;
}) {
  const [family, setFamily] = useState("logreg");
  const [featureSet, setFeatureSet] = useState("core_v1");
  const [labeler, setLabeler] = useState("direction");
  const [symbol, setSymbol] = useState("BTC");
  const [interval, setInterval] = useState("1h");
  const [fromTs, setFromTs] = useState(() =>
    new Date(Date.now() - 365 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [toTs, setToTs] = useState(() => new Date().toISOString().slice(0, 10));
  const [nSplits, setNSplits] = useState(5);
  const [embargo, setEmbargo] = useState(10);
  const [training, setTraining] = useState(false);

  const train = async () => {
    setTraining(true);
    onError(null);
    try {
      await api.post<ModelRecord>("/models/train", {
        family,
        feature_set: featureSet,
        labeler,
        symbol,
        interval,
        from_ts: `${fromTs}T00:00:00Z`,
        to_ts: `${toTs}T23:59:59Z`,
        n_splits: nSplits,
        embargo_bars: embargo,
      });
      onTrained();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setTraining(false);
    }
  };

  return (
    <section className="card">
      <h2 className="card__title">Train a new model</h2>
      <div className="chart-toolbar">
        <Field label="Family">
          <select value={family} onChange={(e) => setFamily(e.target.value)}>
            {FAMILIES.map((f) => <option key={f}>{f}</option>)}
          </select>
        </Field>
        <Field label="Feature set">
          <select value={featureSet} onChange={(e) => setFeatureSet(e.target.value)}>
            {FEATURE_SETS.map((f) => <option key={f}>{f}</option>)}
          </select>
        </Field>
        <Field label="Labeler">
          <select value={labeler} onChange={(e) => setLabeler(e.target.value)}>
            {LABELERS.map((l) => <option key={l}>{l}</option>)}
          </select>
        </Field>
        <Field label="Symbol"><input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></Field>
        <Field label="Interval"><input value={interval} onChange={(e) => setInterval(e.target.value)} /></Field>
      </div>
      <div className="chart-toolbar">
        <Field label="From"><input type="date" value={fromTs} onChange={(e) => setFromTs(e.target.value)} /></Field>
        <Field label="To"><input type="date" value={toTs} onChange={(e) => setToTs(e.target.value)} /></Field>
        <Field label="CV splits"><input type="number" value={nSplits} onChange={(e) => setNSplits(Number(e.target.value))} /></Field>
        <Field label="Embargo bars"><input type="number" value={embargo} onChange={(e) => setEmbargo(Number(e.target.value))} /></Field>
        <button onClick={train} disabled={training}>{training ? "Training…" : "Train"}</button>
      </div>
      <p className="muted small">
        Uses purged k-fold + embargo cross-validation (Prado AFML ch. 7).
        Training runs synchronously; XGBoost on 1 year of hourly data
        takes ~10-30 seconds; logreg is near-instant.
      </p>
    </section>
  );
}

function ModelDetail({
  model,
  onPromoted,
}: {
  model: ModelRecord;
  onPromoted: () => void;
}) {
  const [slotId, setSlotId] = useState("");
  const [busy, setBusy] = useState(false);

  const promote = async () => {
    setBusy(true);
    try {
      await api.post(`/models/${model.id}/promote`, { slot_id: slotId || null });
      onPromoted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="outcome-header">
        <div>
          <h2 className="card__title">{model.family} · {model.id}</h2>
          <div className="muted small">
            {model.label} · {(model.config.symbol as string) ?? "?"}/{(model.config.interval as string) ?? "?"}
          </div>
        </div>
        <div className="outcome-header__stats">
          <Stat label="OOS acc" value={fmt(model.metrics.oos_acc)} />
          <Stat label="OOS F1" value={fmt(model.metrics.oos_f1)} />
          <Stat label="OOS AUC" value={fmt(model.metrics.oos_auc)} />
          <Stat label="LogLoss" value={fmt(model.metrics.oos_logloss)} />
        </div>
      </div>

      <h3 className="card__title">Features ({model.features.length})</h3>
      <p className="muted small">{model.features.join(", ")}</p>

      <h3 className="card__title">Config</h3>
      <pre style={{
        background: "var(--bg)", border: "1px solid var(--border)",
        borderRadius: 4, padding: 10, fontSize: 12, maxHeight: 200, overflow: "auto",
      }}>
        {JSON.stringify(model.config, null, 2)}
      </pre>

      <div className="chart-toolbar">
        <Field label="Promote to slot id (blank = un-promote)">
          <input value={slotId} onChange={(e) => setSlotId(e.target.value)} />
        </Field>
        <button onClick={promote} disabled={busy}>
          {busy ? "Saving…" : model.promoted_slot_id ? "Change promotion" : "Promote"}
        </button>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className="stat-inline__value">{value}</div>
    </div>
  );
}
function fmt(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(4);
}
