import { useEffect, useState } from "react";

import { health, killswitch as ks } from "../api/endpoints";
import type { KillSwitchStatus } from "../api/types";

export function Titlebar() {
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    health
      .get()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));
    ks.status().then(setKillStatus).catch(() => undefined);
    const id = setInterval(() => {
      ks.status().then(setKillStatus).catch(() => undefined);
    }, 5_000);
    return () => clearInterval(id);
  }, []);

  const handleKill = async () => {
    if (!confirm("FLATTEN ALL POSITIONS AND CANCEL ALL ORDERS?\nType-confirm in next prompt."))
      return;
    const phrase = prompt("Type KILL to confirm:");
    if (phrase !== "KILL") {
      alert("Confirmation phrase mismatch — aborting.");
      return;
    }
    setBusy(true);
    try {
      const report = await ks.activate();
      const msg =
        `Killed.\n` +
        `Orders cancelled: ${report.orders_cancelled.length}\n` +
        `Positions closed: ${report.positions_closed.length}\n` +
        `Slots disabled: ${report.slots_disabled}\n` +
        `Errors: ${report.errors.length}`;
      alert(msg);
    } catch (e) {
      alert(`Kill switch failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      ks.status().then(setKillStatus).catch(() => undefined);
    }
  };

  const killActive = killStatus?.active ?? false;
  const indicatorClass =
    backendOk === null
      ? "titlebar__dot titlebar__dot--unknown"
      : backendOk
        ? "titlebar__dot titlebar__dot--ok"
        : "titlebar__dot titlebar__dot--err";

  return (
    <header className="titlebar">
      <div className="titlebar__left">
        <span className={indicatorClass} />
        <span className="titlebar__status-text">
          backend {backendOk === null ? "…" : backendOk ? "ok" : "down"}
        </span>
      </div>
      <div className="titlebar__center">
        {killActive ? (
          <span className="titlebar__killed">⚠ KILL SWITCH ACTIVE — trading halted</span>
        ) : null}
      </div>
      <div className="titlebar__right">
        <button
          className="titlebar__kill"
          onClick={handleKill}
          disabled={busy}
          title="Flatten all positions and cancel all orders"
        >
          {busy ? "…" : "KILL"}
        </button>
      </div>
    </header>
  );
}
