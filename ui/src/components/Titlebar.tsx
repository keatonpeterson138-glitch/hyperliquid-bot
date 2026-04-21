// Titlebar — app-wide top bar.
//
// Left: backend status dot + menu ribbon (File, Edit, View, Settings, Help).
// Center: kill-switch banner when active.
// Right: kill switch button + notifications bell.
//
// Native Tauri menus land in Phase 13 hardening; this is an in-DOM
// fallback that works identically in dev (Vite-only) and prod (Tauri).

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { health, killswitch as ks } from "../api/endpoints";
import type { KillSwitchStatus } from "../api/types";

interface MenuItem {
  label: string;
  onClick?: () => void;
  shortcut?: string;
  disabled?: boolean;
  separator?: boolean;
}

interface MenuGroup {
  label: string;
  items: MenuItem[];
}

export function Titlebar() {
  const navigate = useNavigate();
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Poll health every 3s — sidecar cold-start is 5-15s, so a single
    // mount-time check almost always lands while it's still warming up
    // and falsely flags "backend down" forever. Periodic poll lets the
    // dot flip back to green the moment the sidecar answers.
    const pollHealth = () =>
      health.get().then(() => setBackendOk(true)).catch(() => setBackendOk(false));
    const pollKs = () => ks.status().then(setKillStatus).catch(() => undefined);

    pollHealth();
    pollKs();
    const id = setInterval(() => { pollHealth(); pollKs(); }, 3_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setOpenMenu(null);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  const handleKill = async () => {
    if (!confirm("FLATTEN ALL POSITIONS AND CANCEL ALL ORDERS?")) return;
    const phrase = prompt("Type KILL to confirm:");
    if (phrase !== "KILL") {
      alert("Confirmation phrase mismatch — aborting.");
      return;
    }
    setBusy(true);
    try {
      const report = await ks.activate();
      alert(
        `Killed.\n` +
          `Orders cancelled: ${report.orders_cancelled.length}\n` +
          `Positions closed: ${report.positions_closed.length}\n` +
          `Slots disabled: ${report.slots_disabled}\n` +
          `Errors: ${report.errors.length}`,
      );
    } catch (e) {
      alert(`Kill switch failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      ks.status().then(setKillStatus).catch(() => undefined);
    }
  };

  const todo = (what: string) => () =>
    alert(`${what} — coming in Phase 13 polish (see internal_docs/PHASE_5p5_TO_12_PLAN.md §4.6)`);

  const groups: MenuGroup[] = [
    {
      label: "File",
      items: [
        { label: "New Layout", shortcut: "Ctrl+N", onClick: todo("New Layout") },
        { label: "Open Layout…", shortcut: "Ctrl+O", onClick: todo("Open Layout") },
        { label: "Save Layout", shortcut: "Ctrl+S", onClick: todo("Save Layout") },
        { label: "", separator: true },
        { label: "Save Chart as PNG…", onClick: todo("Save chart as PNG") },
        { label: "Export Candles CSV…", onClick: todo("Export candles") },
        { label: "Export Backtest CSV…", onClick: todo("Export backtest") },
        { label: "Print Chart…", shortcut: "Ctrl+P", onClick: todo("Print chart") },
        { label: "", separator: true },
        { label: "Exit", onClick: () => window.close() },
      ],
    },
    {
      label: "Edit",
      items: [
        { label: "Undo", shortcut: "Ctrl+Z", onClick: todo("Undo") },
        { label: "Redo", shortcut: "Ctrl+Shift+Z", onClick: todo("Redo") },
        { label: "", separator: true },
        { label: "Find symbol", shortcut: "Ctrl+F", onClick: todo("Find symbol") },
      ],
    },
    {
      label: "View",
      items: [
        { label: "Dashboard", onClick: () => navigate("/dashboard") },
        { label: "Charts", onClick: () => navigate("/charts") },
        { label: "Outcomes", onClick: () => navigate("/outcomes") },
        { label: "", separator: true },
        { label: "Light / Dark theme", onClick: todo("Toggle theme") },
      ],
    },
    {
      label: "Tools",
      items: [
        { label: "Backtest Lab", onClick: () => navigate("/backtest") },
        { label: "Research", onClick: () => navigate("/research") },
        { label: "Analog Search", onClick: () => navigate("/analog") },
        { label: "Training Lab", onClick: () => navigate("/models") },
        { label: "Notes", onClick: () => navigate("/notes") },
      ],
    },
    {
      label: "Settings",
      items: [
        { label: "Settings…", shortcut: "Ctrl+,", onClick: () => navigate("/settings") },
        { label: "Vault", onClick: () => navigate("/vault") },
      ],
    },
    {
      label: "Help",
      items: [
        { label: "Keyboard shortcuts", onClick: todo("Shortcuts") },
        { label: "Documentation", onClick: todo("Docs") },
        { label: "About", onClick: todo("About") },
      ],
    },
  ];

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
        <span className="titlebar__status-text">backend {backendOk === null ? "…" : backendOk ? "ok" : "down"}</span>
        <nav className="titlebar__menubar" ref={menuRef}>
          {groups.map((g) => (
            <div
              key={g.label}
              className={`menu ${openMenu === g.label ? "menu--open" : ""}`}
            >
              <button
                className="menu__trigger"
                onClick={() => setOpenMenu(openMenu === g.label ? null : g.label)}
              >
                {g.label}
              </button>
              {openMenu === g.label && (
                <div className="menu__dropdown">
                  {g.items.map((it, i) =>
                    it.separator ? (
                      <div key={`sep-${i}`} className="menu__sep" />
                    ) : (
                      <button
                        key={it.label}
                        className="menu__item"
                        disabled={it.disabled}
                        onClick={() => {
                          setOpenMenu(null);
                          it.onClick?.();
                        }}
                      >
                        <span>{it.label}</span>
                        {it.shortcut && <span className="menu__shortcut">{it.shortcut}</span>}
                      </button>
                    ),
                  )}
                </div>
              )}
            </div>
          ))}
        </nav>
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
