// Mirror of the backend Pydantic models.
// Keep in sync with backend/models/*.py.

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface VaultStatus {
  unlocked: boolean;
  wallet_address: string | null;
}

export interface Market {
  id: string;
  kind: "perp" | "outcome";
  symbol: string;
  dex: string;
  base: string | null;
  category: string | null;
  subcategory: string | null;
  max_leverage: number | null;
  sz_decimals: number | null;
  tick_size: number | null;
  min_size: number | null;
  resolution_date: string | null;
  bounds: Record<string, unknown> | null;
  active: boolean;
  first_seen: string | null;
  last_seen: string | null;
  tags: string[];
}

export interface SlotState {
  last_tick_at: string | null;
  last_signal: string | null;
  last_decision_action: string | null;
  current_position: "LONG" | "SHORT" | null;
  entry_price: number | null;
  position_size_usd: number | null;
  open_order_ids: string[];
}

export interface Slot {
  id: string;
  kind: "perp" | "outcome";
  symbol: string;
  strategy: string;
  size_usd: number;
  interval: string | null;
  strategy_params: Record<string, unknown>;
  leverage: number | null;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  enabled: boolean;
  shadow_enabled: boolean;
  trailing_sl: boolean;
  mtf_enabled: boolean;
  regime_filter: boolean;
  atr_stops: boolean;
  loss_cooldown: boolean;
  volume_confirm: boolean;
  rsi_guard: boolean;
  rsi_guard_low: number;
  rsi_guard_high: number;
  ml_model_id: string | null;
  state: SlotState | null;
}

export interface SlotCreateBody {
  kind?: "perp" | "outcome";
  symbol: string;
  strategy: string;
  size_usd: number;
  interval?: string | null;
  strategy_params?: Record<string, unknown>;
  leverage?: number | null;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  enabled?: boolean;
}

export interface CandlesResponse {
  symbol: string;
  interval: string;
  bar_count: number;
  source_breakdown: Record<string, number>;
  bars: Array<{
    timestamp: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    trades: number | null;
    source: string | null;
  }>;
}

export interface CatalogEntry {
  symbol: string;
  interval: string;
  earliest: string | null;
  latest: string | null;
  bar_count: number;
  source_count: number;
}

export interface CatalogResponse {
  entries: CatalogEntry[];
}

export interface KillSwitchStatus {
  active: boolean;
  last_activated: string | null;
}

export interface KillSwitchReport {
  orders_cancelled: Record<string, unknown>[];
  positions_closed: Record<string, unknown>[];
  slots_disabled: number;
  errors: Record<string, string>[];
}

export type StreamEvent = {
  ts: string;
  type: string;
} & Record<string, unknown>;
