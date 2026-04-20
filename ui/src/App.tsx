import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { Titlebar } from "./components/Titlebar";
import { AnalogPage } from "./pages/AnalogPage";
import { APIKeysPage } from "./pages/APIKeysPage";
import { AuditPage } from "./pages/AuditPage";
import { BacktestPage } from "./pages/BacktestPage";
import { ChartsPage } from "./pages/Charts";
import { Dashboard } from "./pages/Dashboard";
import { DataLabPage } from "./pages/DataLabPage";
import { ModelsPage } from "./pages/ModelsPage";
import { NotesPage } from "./pages/NotesPage";
import { OutcomesPage } from "./pages/Outcomes";
import { ResearchPage } from "./pages/ResearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SlotsPage } from "./pages/SlotsPage";
import { UniversePage } from "./pages/Universe";
import { VaultPage } from "./pages/VaultPage";
import { WalletPage } from "./pages/WalletPage";

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
              <Route path="/wallet" element={<WalletPage />} />
              <Route path="/charts" element={<ChartsPage />} />
              <Route path="/data" element={<DataLabPage />} />
              <Route path="/slots" element={<SlotsPage />} />
              <Route path="/universe" element={<UniversePage />} />
              <Route path="/outcomes" element={<OutcomesPage />} />
              <Route path="/research" element={<ResearchPage />} />
              <Route path="/backtest" element={<BacktestPage />} />
              <Route path="/analog" element={<AnalogPage />} />
              <Route path="/models" element={<ModelsPage />} />
              <Route path="/notes" element={<NotesPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/vault" element={<VaultPage />} />
              <Route path="/apikeys" element={<APIKeysPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  );
}
