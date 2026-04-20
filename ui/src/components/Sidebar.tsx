import { NavLink } from "react-router-dom";

const NAV: Array<{ to: string; label: string }> = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/charts", label: "Charts" },
  { to: "/slots", label: "Slots" },
  { to: "/universe", label: "Universe" },
  { to: "/outcomes", label: "Outcomes" },
  { to: "/audit", label: "Audit" },
  { to: "/vault", label: "Vault" },
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
