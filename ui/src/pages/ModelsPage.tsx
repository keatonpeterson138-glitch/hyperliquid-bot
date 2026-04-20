// Training Lab - trained-model registry + train new + hyperparameter
// tuning (Optuna) + backtest-evaluation + feature importance bars +
// promote-to-slot.

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

const FAMILIES = ["logreg", "xgb_cls", "lgbm_cls", "rf_cls"];
const FEATURE_SETS = ["core_v1", "momentum_v1"];
const LABELERS = ["direction", "forward_return", "triple_barrier", "triple_barrier_atr", "vol_adjusted_return"];

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
                      {(m.config.symbol as string) ?? "?"} · {fmt(m.metrics.oos_acc)} acc
                      {m.metrics.oos_auc ? ` · ${fmt(m.metrics.oos_auc)} AUC` : ""}
                      {m.promoted_slot_id ? " · promoted" : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          <TrainForm onTrained={refresh} onError={setError} />
          <TuneForm onError={setError} />
          {error && <div className="card error small">{error}</div>}
          {selected && <ModelDetail model={selected} onChanged={refresh} />}
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
  const [family, setFamily] = useState("xgb_cls");
  const [featureSet, setFeatureSet] = useState("momentum_v1");
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
        family, feature_set: featureSet, labeler,
        symbol, interval,
        from_ts: `${fromTs}T00:00:00Z`,
        to_ts: `${toTs}T23:59:59Z`,
        n_splits: nSplits, embargo_bars: embargo,
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
        Purged k-fold + embargo CV (Prado AFML ch. 7). momentum_v1 gives
        you 37 features; xgb_cls + triple_barrier_atr is a solid starting
        recipe.
      </p>
    </section>
  );
}

function TuneForm({ onError }: { onError: (msg: string | null) => void }) {
  const [family, setFamily] = useState("xgb_cls");
  const [featureSet, setFeatureSet] = useState("momentum_v1");
  const [labeler, setLabeler] = useState("direction");
  const [symbol, setSymbol] = useState("BTC");
  const [interval, setInterval] = useState("1h");
  const [nTrials, setNTrials] = useState(20);
  const [fromTs, setFromTs] = useState(() =>
    new Date(Date.now() - 365 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [toTs, setToTs] = useState(() => new Date().toISOString().slice(0, 10));
  const [tuning, setTuning] = useState(false);
  const [bestParams, setBestParams] = useState<Record<string, unknown> | null>(null);
  const [bestScore, setBestScore] = useState<number | null>(null);

  const tune = async () => {
    setTuning(true);
    onError(null);
    try {
      const r = await api.post<{ best_params: Record<string, unknown>; best_score: number }>(
        "/models/tune",
        {
          family, feature_set: featureSet, labeler, symbol, interval,
          from_ts: `${fromTs}T00:00:00Z`,
          to_ts: `${toTs}T23:59:59Z`,
          n_trials: nTrials,
          rank_by: "oos_auc",
        },
      );
      setBestParams(r.best_params);
      setBestScore(r.best_score);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setTuning(false);
    }
  };

  return (
    <section className="card">
      <h2 className="card__title">Hyperparameter tune (Optuna)</h2>
      <p className="muted small">
        Bayesian search (TPE) over the family's param space; returns the
        best CV-OOS AUC. Re-train with the winning params separately.
      </p>
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
        <Field label="Trials"><input type="number" value={nTrials} onChange={(e) => setNTrials(Number(e.target.value))} /></Field>
        <button onClick={tune} disabled={tuning}>{tuning ? "Tuning…" : "Tune"}</button>
      </div>
      {bestParams && (
        <div className="muted small">
          <div>Best OOS AUC: {fmt(bestScore)}</div>
          <pre style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 4, padding: 10, fontSize: 12, margin: "4px 0",
          }}>
            {JSON.stringify(bestParams, null, 2)}
          </pre>
          <div>
            To train with these params, copy them into the train form's
            strategy_params (API-only for now) or re-run with the family defaults.
          </div>
        </div>
      )}
    </section>
  );
}

function ModelDetail({
  model,
  onChanged,
}: {
  model: ModelRecord;
  onChanged: () => void;
}) {
  const [slotId, setSlotId] = useState("");
  const [busy, setBusy] = useState(false);
  const [backtestMetrics, setBacktestMetrics] = useState<Record<string, number> | null>(null);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [backtestBusy, setBacktestBusy] = useState(false);
  const [backtestFrom, setBacktestFrom] = useState(() =>
    new Date(Date.now() - 90 * 24 * 3_600_000).toISOString().slice(0, 10),
  );
  const [backtestTo, setBacktestTo] = useState(() => new Date().toISOString().slice(0, 10));

  const promote = async () => {
    setBusy(true);
    try {
      await api.post(`/models/${model.id}/promote`, { slot_id: slotId || null });
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const runBacktest = async () => {
    setBacktestBusy(true);
    setBacktestError(null);
    try {
      const r = await api.post<{ metrics: Record<string, number> }>(
        `/models/${model.id}/backtest`,
        {
          from_ts: `${backtestFrom}T00:00:00Z`,
          to_ts: `${backtestTo}T23:59:59Z`,
          size_usd: 100, leverage: 1,
        },
      );
      setBacktestMetrics(r.metrics);
    } catch (e) {
      setBacktestError((e as Error).message);
    } finally {
      setBacktestBusy(false);
    }
  };

  const importance = (model.config.feature_importance ?? {}) as Record<string, number>;
  const permutation = (model.config.permutation_importance ?? {}) as Record<string, number>;
  const topImportance = Object.entries(importance)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);
  const topPermutation = Object.entries(permutation)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);

  return (
    <>
      <section className="card">
        <div className="outcome-header">
          <div>
            <h2 className="card__title">{model.family} · {model.id}</h2>
            <div className="muted small">
              {model.label} · {(model.config.symbol as string) ?? "?"}/{(model.config.interval as string) ?? "?"}
              {" · "}{(model.config.feature_set as string) ?? "?"}
              {" · "}{model.features.length} features
            </div>
          </div>
          <div className="outcome-header__stats">
            <Stat label="OOS acc" value={fmt(model.metrics.oos_acc)} />
            <Stat label="OOS F1" value={fmt(model.metrics.oos_f1)} />
            <Stat label="OOS AUC" value={fmt(model.metrics.oos_auc)} />
            <Stat label="LogLoss" value={fmt(model.metrics.oos_logloss)} />
          </div>
        </div>
      </section>

      <section className="card">
        <h3 className="card__title">Trading evaluation (backtest the model)</h3>
        <div className="chart-toolbar">
          <Field label="From"><input type="date" value={backtestFrom} onChange={(e) => setBacktestFrom(e.target.value)} /></Field>
          <Field label="To"><input type="date" value={backtestTo} onChange={(e) => setBacktestTo(e.target.value)} /></Field>
          <button onClick={runBacktest} disabled={backtestBusy}>
            {backtestBusy ? "Running…" : "Backtest"}
          </button>
        </div>
        {backtestError && <div className="error small">{backtestError}</div>}
        {backtestMetrics && (
          <div className="outcome-header__stats">
            <Stat label="Return %" value={fmt(backtestMetrics.total_return_pct, 2)} tone={toneFromNumber(backtestMetrics.total_return_pct)} />
            <Stat label="Sharpe" value={fmt(backtestMetrics.sharpe, 2)} />
            <Stat label="Max DD %" value={fmt(backtestMetrics.max_dd_pct, 2)} tone="neg" />
            <Stat label="Win rate" value={fmt(backtestMetrics.win_rate, 3)} />
            <Stat label="Trades" value={String(Math.round(backtestMetrics.trade_count))} />
            <Stat label="Profit factor" value={fmt(backtestMetrics.profit_factor, 2)} />
          </div>
        )}
        <p className="muted small">
          Runs MLStrategy through BacktestEngine on the actual price series.
          Classification accuracy doesn't capture whether the model makes
          money — this does.
        </p>
      </section>

      {topImportance.length > 0 && (
        <section className="card">
          <h3 className="card__title">Feature importance (model-native)</h3>
          <ImportanceBars rows={topImportance} />
        </section>
      )}

      {topPermutation.length > 0 && (
        <section className="card">
          <h3 className="card__title">Permutation importance (accuracy drop on shuffle)</h3>
          <ImportanceBars rows={topPermutation} />
        </section>
      )}

      <section className="card">
        <h3 className="card__title">Promote to slot</h3>
        <div className="chart-toolbar">
          <Field label="Slot ID (blank = un-promote)">
            <input value={slotId} onChange={(e) => setSlotId(e.target.value)} />
          </Field>
          <button onClick={promote} disabled={busy}>
            {busy ? "Saving…" : model.promoted_slot_id ? "Change promotion" : "Promote"}
          </button>
        </div>
      </section>
    </>
  );
}

function ImportanceBars({ rows }: { rows: Array<[string, number]> }) {
  const maxVal = Math.max(...rows.map(([, v]) => v), 1e-9);
  return (
    <div className="importance-bars">
      {rows.map(([name, val]) => (
        <div key={name} className="importance-bar">
          <span className="importance-bar__name">{name}</span>
          <div className="importance-bar__track">
            <div
              className="importance-bar__fill"
              style={{ width: `${(val / maxVal) * 100}%` }}
            />
          </div>
          <span className="importance-bar__val">{val.toFixed(4)}</span>
        </div>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="stat-inline">
      <div className="stat-inline__label">{label}</div>
      <div className={`stat-inline__value ${tone ? `tone--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
function fmt(v: number | null | undefined, dp = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(dp);
}
function toneFromNumber(v: number | null | undefined): "pos" | "neg" | undefined {
  if (v === null || v === undefined || !Number.isFinite(v)) return undefined;
  return v > 0 ? "pos" : v < 0 ? "neg" : undefined;
}
