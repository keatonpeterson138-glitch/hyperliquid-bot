import { NavLink } from "react-router-dom";

const NAV: Array<{ to: string; label: string; group?: string }> = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/wallet", label: "Wallet" },
  { to: "/charts", label: "Charts" },
  { to: "/outcomes", label: "Outcomes" },
  { to: "/slots", label: "Slots" },
  { to: "/universe", label: "Universe", group: "research" },
  { to: "/research", label: "Research", group: "research" },
  { to: "/backtest", label: "Backtest", group: "research" },
  { to: "/analog", label: "Analog", group: "research" },
  { to: "/models", label: "Models", group: "research" },
  { to: "/notes", label: "Notes", group: "other" },
  { to: "/audit", label: "Audit", group: "other" },
  { to: "/vault", label: "Vault", group: "other" },
  { to: "/settings", label: "Settings", group: "other" },
];

export function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__brand-name">Hyperliquid Bot</span>
        <span className="sidebar__brand-version">v0.2.0</span>
      </div>
      <ul className="sidebar__nav">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                "sidebar__link" + (isActive ? " sidebar__link--active" : "")
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
