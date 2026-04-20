import { useEffect, useState } from "react";

import { slots as slotsApi } from "../api/endpoints";
import type { Slot } from "../api/types";

export function SlotsPage() {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [showCreate, setShowCreate] = useState(false);

  const refresh = () => slotsApi.list().then(setSlots).catch(() => undefined);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, []);

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
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label className="field">
          <span>Strategy</span>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="ema_crossover">EMA Crossover</option>
            <option value="rsi_mean_reversion">RSI Mean Reversion</option>
            <option value="breakout">Breakout</option>
          </select>
        </label>
        <label className="field">
          <span>Interval</span>
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
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
