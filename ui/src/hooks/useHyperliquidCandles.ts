// Direct WebSocket subscription to Hyperliquid's candle stream.
// Each tick on the current symbol/interval updates the chart instantly
// (no round-trip through our backend — the browser/Tauri webview talks
// straight to api.hyperliquid.xyz/ws).
//
// Protocol (from the Hyperliquid info-endpoint docs):
//   subscribe:   {method:"subscribe",  subscription:{type:"candle",coin:"BTC",interval:"1h"}}
//   unsubscribe: {method:"unsubscribe",subscription:{...}}
//   message:     {channel:"candle", data:{t,T,s,i,o,c,h,l,v,n}}
//
// The hook fires ``onCandle(bar)`` for every update. It's up to the
// consumer to merge into their chart state (keyed by timestamp so a
// partial bar overwrites the in-progress one and a new bar appends).

import { useEffect, useRef, useState } from "react";

export interface HyperliquidCandle {
  timestamp: string;   // ISO — open time of the bar
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades: number | null;
  source: string;      // always 'hyperliquid-ws' for these
}

type Status = "connecting" | "open" | "closed";

interface Options {
  symbol: string;
  interval: string;
  onCandle: (bar: HyperliquidCandle) => void;
  testnet?: boolean;
  enabled?: boolean;
}

const MAINNET_WS = "wss://api.hyperliquid.xyz/ws";
const TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws";
const MAX_RETRY_MS = 30_000;

export function useHyperliquidCandles(opts: Options): { status: Status } {
  const { symbol, interval, onCandle, testnet = false, enabled = true } = opts;
  const [status, setStatus] = useState<Status>("connecting");
  // Keep the latest callback in a ref so reconnects don't depend on it.
  const cbRef = useRef(onCandle);
  cbRef.current = onCandle;

  useEffect(() => {
    if (!enabled) {
      setStatus("closed");
      return;
    }

    let cancelled = false;
    let retryDelay = 500;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (cancelled) return;
      const url = testnet ? TESTNET_WS : MAINNET_WS;
      ws = new WebSocket(url);
      setStatus("connecting");

      ws.onopen = () => {
        if (cancelled) {
          ws?.close();
          return;
        }
        retryDelay = 500;
        setStatus("open");
        ws?.send(JSON.stringify({
          method: "subscribe",
          subscription: { type: "candle", coin: symbol, interval },
        }));
      };

      ws.onmessage = (evt) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(evt.data);
          if (msg?.channel !== "candle" || !msg.data) return;
          const d = msg.data;
          // Ignore messages for other symbols/intervals that might arrive
          // during a subscription change.
          if (d.s !== symbol || d.i !== interval) return;
          cbRef.current({
            timestamp: new Date(Number(d.t)).toISOString(),
            open: Number(d.o),
            high: Number(d.h),
            low: Number(d.l),
            close: Number(d.c),
            volume: Number(d.v),
            trades: typeof d.n === "number" ? d.n : null,
            source: "hyperliquid-ws",
          });
        } catch {
          /* malformed — ignore */
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        reconnectTimer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS);
      };
      ws.onerror = () => {
        /* swallow; onclose will reconnect */
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (!ws) return;
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            method: "unsubscribe",
            subscription: { type: "candle", coin: symbol, interval },
          }));
        }
        if (
          ws.readyState === WebSocket.OPEN ||
          ws.readyState === WebSocket.CLOSING
        ) {
          ws.close();
        }
      } catch {
        /* cleanup best-effort */
      }
    };
  }, [symbol, interval, testnet, enabled]);

  return { status };
}
