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

export const killswitch = {
  status: () => api.get<KillSwitchStatus>("/killswitch/status"),
  activate: () =>
    api.post<KillSwitchReport>("/killswitch/activate", { confirmation: "KILL" }),
  reset: () => api.post<void>("/killswitch/reset", { confirmation: "RESUME" }),
};
