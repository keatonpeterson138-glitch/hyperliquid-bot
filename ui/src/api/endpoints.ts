// Typed wrappers for each backend endpoint. Always go through these —
// they centralize request shape + response typing.

import { api } from "./client";
import type {
  CandlesResponse,
  CatalogResponse,
  HealthResponse,
  KillSwitchReport,
  KillSwitchStatus,
  Market,
  OutcomeEdge,
  OutcomeTapeResponse,
  Slot,
  SlotCreateBody,
  VaultStatus,
} from "./types";

export const health = {
  get: () => api.get<HealthResponse>("/health"),
};

export const vault = {
  status: () => api.get<VaultStatus>("/vault/status"),
  store: (wallet_address: string, private_key: string) =>
    api.post<void>("/vault/store", { wallet_address, private_key }),
  unlock: (wallet_address?: string) =>
    api.post<{ unlocked_at: string; wallet_address: string }>(
      "/vault/unlock",
      { wallet_address: wallet_address ?? null },
    ),
  lock: () => api.post<void>("/vault/lock"),
};

export const universe = {
  list: (params: { kind?: string; category?: string; active_only?: boolean } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) q.set(k, String(v));
    }
    const qs = q.toString();
    return api.get<{ markets: Market[] }>(`/universe${qs ? `?${qs}` : ""}`);
  },
  refresh: () => api.post<{
    markets_total: number;
    markets_added: number;
    markets_reactivated: number;
    markets_deactivated: number;
  }>("/universe/refresh"),
  tag: (market_id: string, tag: string) =>
    api.post<void>(`/universe/${market_id}/tag`, { tag }),
  untag: (market_id: string, tag: string) =>
    api.del<void>(`/universe/${market_id}/tag`, { tag }),
};

export const slots = {
  list: () => api.get<Slot[]>("/slots"),
  get: (id: string) => api.get<Slot>(`/slots/${id}`),
  create: (body: SlotCreateBody) => api.post<Slot>("/slots", body),
  update: (id: string, body: Partial<SlotCreateBody>) =>
    api.patch<Slot>(`/slots/${id}`, body),
  delete: (id: string) => api.del<void>(`/slots/${id}`),
  start: (id: string) => api.post<Slot>(`/slots/${id}/start`),
  stop: (id: string) => api.post<Slot>(`/slots/${id}/stop`),
  stopAll: () => api.post<{ slots_stopped: number }>("/slots/stop-all"),
  tick: (id: string) =>
    api.post<{
      slot_id: string;
      action: string;
      reason: string;
      strength: number;
      rejection: string | null;
    }>(`/slots/${id}/tick`),
};

export const candles = {
  get: (symbol: string, interval: string, from: string, to?: string, source?: string) => {
    const q = new URLSearchParams({ symbol, interval, from });
    if (to) q.set("to", to);
    if (source) q.set("source", source);
    return api.get<CandlesResponse>(`/candles?${q.toString()}`);
  },
  catalog: () => api.get<CatalogResponse>("/catalog"),
};

export interface OrderLeg {
  id: number | null;
  leg_type: "entry" | "sl" | "tp";
  exchange_order_id: string | null;
  price: number | null;
  status: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: "long" | "short";
  size_usd: number;
  entry_type: "market" | "limit";
  entry_price: number | null;
  sl_price: number | null;
  tp_price: number | null;
  leverage: number | null;
  status: string;
  slot_id: string | null;
  markup_id: string | null;
  exchange_order_id: string | null;
  fill_price: number | null;
  source: string;
  reject_reason: string | null;
  legs: OrderLeg[];
  created_at: string | null;
  updated_at: string | null;
}

export interface OrderCreateBody {
  symbol: string;
  side: "long" | "short";
  size_usd: number;
  entry_type?: "market" | "limit";
  entry_price?: number | null;
  sl_price?: number | null;
  tp_price?: number | null;
  leverage?: number | null;
  slot_id?: string | null;
  markup_id?: string | null;
  source?: string;
}

export const orders = {
  list: (params: { symbol?: string; slot_id?: string; status?: string; markup_id?: string } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) q.set(k, String(v));
    }
    const qs = q.toString();
    return api.get<Order[]>(`/orders${qs ? `?${qs}` : ""}`);
  },
  create: (body: OrderCreateBody) => api.post<Order>("/orders", body),
  modify: (id: string, body: { sl_price?: number | null; tp_price?: number | null }) =>
    api.patch<Order>(`/orders/${id}`, body),
  cancel: (id: string) => api.del<Order>(`/orders/${id}`),
  fromMarkup: (body: { markup_id: string; size_usd: number; leverage?: number | null; slot_id?: string | null }) =>
    api.post<Order>("/orders/from-markup", body),
};

export const outcomes = {
  list: (params: { subcategory?: string; active_only?: boolean } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) q.set(k, String(v));
    }
    const qs = q.toString();
    return api.get<{ markets: Market[] }>(`/outcomes${qs ? `?${qs}` : ""}`);
  },
  tape: (market_id: string, from: string, to?: string) => {
    const q = new URLSearchParams({ from });
    if (to) q.set("to", to);
    return api.get<OutcomeTapeResponse>(
      `/outcomes/${encodeURIComponent(market_id)}/tape?${q.toString()}`,
    );
  },
  edge: (market_id: string, default_vol?: number) => {
    const q = new URLSearchParams();
    if (default_vol !== undefined) q.set("default_vol", String(default_vol));
    const qs = q.toString();
    return api.get<OutcomeEdge>(
      `/outcomes/${encodeURIComponent(market_id)}/edge${qs ? `?${qs}` : ""}`,
    );
  },
};

export interface WalletPosition {
  symbol: string;
  side: string;
  size_usd: number;
  entry_price: number | null;
  unrealised_pnl_usd: number | null;
}

export interface WalletSummary {
  wallet_address: string | null;
  usdc_balance: number | null;
  total_notional_usd: number;
  unrealised_pnl_usd: number;
  realised_pnl_session_usd: number;
  realised_pnl_all_time_usd: number;
  fees_paid_all_time_usd: number;
  positions: WalletPosition[];
  open_orders: number;
  last_updated: string;
}

export const wallet = {
  summary: (wallet_address?: string) => {
    const q = wallet_address ? `?wallet_address=${encodeURIComponent(wallet_address)}` : "";
    return api.get<WalletSummary>(`/wallet/summary${q}`);
  },
  activity: (limit = 25) => api.get<Order[]>(`/wallet/activity?limit=${limit}`),
};

export interface NoteAttachment {
  id: number | null;
  kind: string;
  path: string;
  meta: Record<string, unknown>;
}

export interface Note {
  id: string;
  title: string;
  body_md: string;
  tags: string[];
  linked_layout_id: string | null;
  linked_backtest_id: string | null;
  attachments: NoteAttachment[];
  created_at: string | null;
  updated_at: string | null;
}

export const notes = {
  list: (tag?: string) => {
    const q = tag ? `?tag=${encodeURIComponent(tag)}` : "";
    return api.get<Note[]>(`/notes${q}`);
  },
  create: (body: { title: string; body_md?: string; tags?: string[] }) =>
    api.post<Note>("/notes", body),
  get: (id: string) => api.get<Note>(`/notes/${id}`),
  update: (id: string, patch: Partial<{ title: string; body_md: string; tags: string[] }>) =>
    api.patch<Note>(`/notes/${id}`, patch),
  delete: (id: string) => api.del<void>(`/notes/${id}`),
  attach: (id: string, body: { path: string; kind?: string; meta?: Record<string, unknown> }) =>
    api.post<NoteAttachment>(`/notes/${id}/attachments`, body),
};

export interface AppSettings {
  testnet: boolean;
  email_enabled: boolean;
  telegram_enabled: boolean;
  desktop_notifications: boolean;
  default_stop_loss_pct: number;
  default_take_profit_pct: number;
  confirm_above_usd: number;
  confirm_modify_pct: number;
  confirm_leverage_above: number;
  aggregate_exposure_cap_usd: number | null;
  data_root: string;
  backfill_throttle_ms: number;
  cross_validate_threshold_pct: number;
  duckdb_cache_mb: number;
  theme: string;
  density: string;
  dev_mode: boolean;
  log_level: string;
  extras: Record<string, unknown>;
}

export const settings = {
  get: () => api.get<AppSettings>("/settings"),
  patch: (patch: Partial<AppSettings>) => api.patch<AppSettings>("/settings", patch),
};

export const killswitch = {
  status: () => api.get<KillSwitchStatus>("/killswitch/status"),
  activate: () =>
    api.post<KillSwitchReport>("/killswitch/activate", { confirmation: "KILL" }),
  reset: () => api.post<void>("/killswitch/reset", { confirmation: "RESUME" }),
};
