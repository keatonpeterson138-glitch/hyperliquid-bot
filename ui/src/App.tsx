import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { Titlebar } from "./components/Titlebar";
import { AuditPage } from "./pages/AuditPage";
import { ChartsPage } from "./pages/Charts";
import { Dashboard } from "./pages/Dashboard";
import { OutcomesPage } from "./pages/Outcomes";
import { SlotsPage } from "./pages/SlotsPage";
import { UniversePage } from "./pages/Universe";
import { VaultPage } from "./pages/VaultPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <div className="app-main">
          <Titlebar />
          <div className="app-content">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/charts" element={<ChartsPage />} />
              <Route path="/slots" element={<SlotsPage />} />
              <Route path="/universe" element={<UniversePage />} />
              <Route path="/outcomes" element={<OutcomesPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/vault" element={<VaultPage />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  );
}
