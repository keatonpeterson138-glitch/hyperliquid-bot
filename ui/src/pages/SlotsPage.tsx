import { useCallback, useEffect, useState } from "react";

import { markets as marketsApi, slots as slotsApi, type PresetSlot } from "../api/endpoints";
import { SymbolCombobox } from "../components/SymbolCombobox";
import type { Slot } from "../api/types";

const STOCK_SYMBOLS = ["AAPL","MSFT","GOOGL","AMZN","META","TSLA","NVDA","AMD","INTC","NFLX","COIN","MSTR","HOOD","PLTR","TSM","SPY","QQQ","DIA","IWM","GLD","SLV","USO"];
const HIP3_PERPS = ["xyz:SP500","xyz:XYZ100","cash:GOLD","cash:SILVER","cash:OIL","cash:CORN","cash:WHEAT"];
const FRED_SERIES = ["DFF","DGS10","DGS2","T10Y2Y","DFII10","T10YIE","T5YIFR","CPIAUCSL","CPILFESL","UNRATE","PAYEMS","ICSA","GDPC1","INDPRO","UMCSENT","VIXCLS","DTWEXBGS","WALCL","M2SL","RRPONTSYD"];
const STRATEGY_OPTIONS = [
  { value: "ema_crossover",      label: "EMA Crossover" },
  { value: "rsi_mean_reversion", label: "RSI Mean Reversion" },
  { value: "breakout",           label: "Breakout" },
  { value: "connors_rsi2",       label: "Connors RSI(2)" },
  { value: "bb_fade",            label: "Bollinger Band Fade" },
  { value: "keltner_reversion",  label: "Keltner Reversion" },
  { value: "williams_mean_rev",  label: "Williams %R Mean-Rev" },
  { value: "gap_fill",           label: "Gap Fill" },
];

export function SlotsPage() {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [presets, setPresets] = useState<PresetSlot[]>([]);
  const [presetBusy, setPresetBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const refresh = useCallback(
    () => slotsApi.list().then(setSlots).catch(() => undefined),
    [],
  );

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    slotsApi.presets().then(setPresets).catch(() => undefined);
  }, []);

  const addFromPreset = async (presetId: string) => {
    setPresetBusy(presetId);
    try {
      await slotsApi.instantiatePreset(presetId);
      await refresh();
    } finally {
      setPresetBusy(null);
    }
  };

  const handleStart = async (id: string) => {
    await slotsApi.start(id);
    refresh();
  };
  const handleStop = async (id: string) => {
    await slotsApi.stop(id);
    refresh();
  };
  const handleDelete = async (id: string) => {
    if (!confirm("Delete this slot?")) return;
    await slotsApi.delete(id);
    refresh();
  };
  const handleTick = async (id: string) => {
    const result = await slotsApi.tick(id);
    alert(
      `Tick result:\n` +
        `action: ${result.action}\n` +
        `reason: ${result.reason}\n` +
        (result.rejection ? `rejection: ${result.rejection}\n` : ""),
    );
    refresh();
  };

  return (
    <div className="page">
      <h1 className="page__title">Slots</h1>

      <section className="toolbar">
        <button onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "+ New slot"}
        </button>
        <button onClick={async () => { await slotsApi.stopAll(); refresh(); }}>
          Stop all
        </button>
        <span className="muted">{slots.length} slot(s)</span>
      </section>

      {showCreate ? (
        <NewSlotForm
          onCreated={() => {
            setShowCreate(false);
            refresh();
          }}
        />
      ) : null}

      {presets.length > 0 && (
        <section className="card">
          <h2 className="card__title">Backtested presets ({presets.length})</h2>
          <p className="muted small">
            Click "Add" to create a disabled slot from this preset. Numbers come
            from <code>scripts/run_preset_bench.py</code> — see <code>internal_docs/trading_presets.md</code>.
          </p>
          <div className="preset-grid">
            {presets.map((p) => (
              <div key={p.preset_id} className="preset-card">
                <div className="preset-card__head">
                  <strong>{p.name}</strong>
                  <span className="badge badge--ok">{(p.win_rate * 100).toFixed(1)}% WR</span>
                </div>
                <div className="preset-card__metrics">
                  <span>Sharpe <b>{p.sharpe.toFixed(2)}</b></span>
                  <span>Return <b>{p.total_return_pct.toFixed(2)}%</b></span>
                  <span>{p.trade_count} trades</span>
                  <span>{p.backtest_window_years}y window</span>
                </div>
                <p className="preset-card__desc muted small">{p.description}</p>
                <button
                  onClick={() => addFromPreset(p.preset_id)}
                  disabled={presetBusy === p.preset_id}
                >
                  {presetBusy === p.preset_id ? "Adding…" : "+ Add slot"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {slots.map((s) => (
        <section key={s.id} className="card slot-card">
          <div className="slot-card__head">
            <strong>{s.symbol}</strong>
            <span className="badge">{s.strategy}</span>
            <span className="badge">{s.interval}</span>
            <span className="badge">${s.size_usd}</span>
            <span className="badge">{s.leverage}× lev</span>
            <span className={"badge " + (s.enabled ? "badge--ok" : "badge--off")}>
              {s.enabled ? "ENABLED" : "DISABLED"}
            </span>
            {s.shadow_enabled ? <span className="badge">shadow</span> : null}
            {s.state?.current_position ? (
              <span className="badge badge--pos">{s.state.current_position}</span>
            ) : null}
          </div>
          <div className="slot-card__actions">
            {s.enabled ? (
              <button onClick={() => handleStop(s.id)}>Stop</button>
            ) : (
              <button onClick={() => handleStart(s.id)}>Start</button>
            )}
            <button onClick={() => handleTick(s.id)}>Run tick</button>
            <button onClick={() => handleDelete(s.id)}>Delete</button>
          </div>
          {s.state?.last_tick_at ? (
            <div className="muted small">
              Last tick: {s.state.last_tick_at} · last action:{" "}
              {s.state.last_decision_action ?? "—"}
            </div>
          ) : null}
        </section>
      ))}

      {slots.length === 0 ? (
        <p className="muted">No slots yet. Create one above.</p>
      ) : null}
    </div>
  );
}

function NewSlotForm({ onCreated }: { onCreated: () => void }) {
  const [symbol, setSymbol] = useState("BTC");
  const [strategy, setStrategy] = useState("ema_crossover");
  const [interval, setInterval] = useState("1h");
  const [sizeUsd, setSizeUsd] = useState(100);
  const [leverage, setLeverage] = useState(3);
  const [stopLoss, setStopLoss] = useState(2);
  const [takeProfit, setTakeProfit] = useState(4);
  const [busy, setBusy] = useState(false);
  const [symbolCatalog, setSymbolCatalog] = useState<string[]>([]);

  // Hyperliquid universe (live) + curated stocks/HIP-3/FRED so the combobox
  // can search across every chartable / tradable symbol.
  useEffect(() => {
    marketsApi.meta().then((r) => {
      const raw = r.raw as { universe?: Array<{ name?: string }> };
      const hl = (raw.universe ?? []).map((u) => u.name).filter((n): n is string => !!n);
      const seen = new Set<string>();
      const out: string[] = [];
      for (const s of [...hl, ...STOCK_SYMBOLS, ...HIP3_PERPS, ...FRED_SERIES]) {
        if (!seen.has(s)) { seen.add(s); out.push(s); }
      }
      setSymbolCatalog(out);
    }).catch(() => setSymbolCatalog([...STOCK_SYMBOLS, ...HIP3_PERPS, ...FRED_SERIES]));
  }, []);

  const submit = async () => {
    setBusy(true);
    try {
      await slotsApi.create({
        symbol,
        strategy,
        interval,
        size_usd: sizeUsd,
        leverage,
        stop_loss_pct: stopLoss,
        take_profit_pct: takeProfit,
        enabled: false,
      });
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2 className="card__title">New slot</h2>
      <div className="form-grid">
        <label className="field">
          <span>Symbol</span>
          <SymbolCombobox
            value={symbol}
            onChange={(s) => setSymbol(s)}
            options={symbolCatalog}
            placeholder="Type to search…"
          />
        </label>
        <label className="field">
          <span>Strategy</span>
          <SymbolCombobox
            value={strategy}
            onChange={(s) => setStrategy(s)}
            options={STRATEGY_OPTIONS}
            placeholder="Pick a strategy"
            allowFreeText={false}
          />
        </label>
        <label className="field">
          <span>Interval</span>
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="30m">30m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
            <option value="1w">1w</option>
          </select>
        </label>
        <label className="field">
          <span>Size USD</span>
          <input
            type="number"
            value={sizeUsd}
            onChange={(e) => setSizeUsd(Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span>Leverage</span>
          <input
            type="number"
            value={leverage}
            onChange={(e) => setLeverage(Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span>Stop loss %</span>
          <input
            type="number"
            step="0.1"
            value={stopLoss}
            onChange={(e) => setStopLoss(Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span>Take profit %</span>
          <input
            type="number"
            step="0.1"
            value={takeProfit}
            onChange={(e) => setTakeProfit(Number(e.target.value))}
          />
        </label>
      </div>
      <button onClick={submit} disabled={busy}>
        {busy ? "Creating…" : "Create"}
      </button>
    </section>
  );
}
