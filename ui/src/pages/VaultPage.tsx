import { useEffect, useState } from "react";

import { vault } from "../api/endpoints";
import type { VaultStatus } from "../api/types";

export function VaultPage() {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [wallet, setWallet] = useState("");
  const [privKey, setPrivKey] = useState("");
  const [unlockWallet, setUnlockWallet] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    vault
      .status()
      .then(setStatus)
      .catch((e) => setError((e as Error).message));

  useEffect(() => {
    refresh();
  }, []);

  const handleStore = async () => {
    setError(null);
    setBusy(true);
    try {
      await vault.store(wallet, privKey);
      setPrivKey("");
      alert("Stored. Now unlock to use it.");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleUnlock = async () => {
    setError(null);
    setBusy(true);
    try {
      await vault.unlock(unlockWallet || undefined);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleLock = async () => {
    await vault.lock();
    refresh();
  };

  return (
    <div className="page">
      <h1 className="page__title">Key Vault</h1>

      <section className="card">
        <h2 className="card__title">Status</h2>
        {status ? (
          <pre className="code">{JSON.stringify(status, null, 2)}</pre>
        ) : (
          <p>Loading…</p>
        )}
        {status?.unlocked ? (
          <button onClick={handleLock} disabled={busy}>
            Lock
          </button>
        ) : null}
      </section>

      <section className="card">
        <h2 className="card__title">Store key (first run)</h2>
        <p className="muted">
          Saves to your OS keychain. Never written to disk in plaintext.
        </p>
        <label className="field">
          <span>Wallet address</span>
          <input
            value={wallet}
            onChange={(e) => setWallet(e.target.value)}
            placeholder="0x…"
          />
        </label>
        <label className="field">
          <span>Private key (hex, no 0x)</span>
          <input
            type="password"
            value={privKey}
            onChange={(e) => setPrivKey(e.target.value)}
          />
        </label>
        <button onClick={handleStore} disabled={busy || !wallet || !privKey}>
          Store
        </button>
      </section>

      <section className="card">
        <h2 className="card__title">Unlock for trading</h2>
        <label className="field">
          <span>Wallet (blank = use most recent)</span>
          <input
            value={unlockWallet}
            onChange={(e) => setUnlockWallet(e.target.value)}
            placeholder="0x…"
          />
        </label>
        <button onClick={handleUnlock} disabled={busy}>
          Unlock
        </button>
      </section>

      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
