// Subscribes to the backend /stream WebSocket and keeps a rolling
// ring-buffer of events. Auto-reconnects with exponential backoff.
//
// React 19 StrictMode double-invokes effects in dev — the first cleanup
// runs before the socket has finished handshaking, which would otherwise
// flood the console with "WebSocket is closed before the connection is
// established". We handle that with a cancel flag + readyState check.

import { useEffect, useRef, useState } from "react";

import { BACKEND_URL } from "../api/client";
import type { StreamEvent } from "../api/types";

const WS_URL = BACKEND_URL.replace(/^http/, "ws") + "/stream";
const RING_SIZE = 200;

type StreamStatus = "connecting" | "open" | "closed";

export function useStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryDelay = 500;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let currentWs: WebSocket | null = null;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(WS_URL);
      currentWs = ws;
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        if (cancelled) {
          // Unmounted mid-handshake (typically StrictMode); close cleanly now.
          ws.close();
          return;
        }
        retryDelay = 500;
        setStatus("open");
      };
      ws.onmessage = (msg) => {
        if (cancelled) return;
        try {
          const event = JSON.parse(msg.data) as StreamEvent;
          setEvents((prev) => {
            const next = [...prev, event];
            if (next.length > RING_SIZE) next.splice(0, next.length - RING_SIZE);
            return next;
          });
        } catch {
          /* malformed — ignore */
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        reconnectTimer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 10_000);
      };
      // Don't call ws.close() here — onclose will fire on its own and we'd
      // double-log. Just swallow the error event.
      ws.onerror = () => {};
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const ws = currentWs;
      if (!ws) return;
      // CONNECTING sockets will close themselves via the cancelled flag in
      // onopen; calling close() on them is what produces the "closed before
      // connection established" warning. Only close if already open/closing.
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CLOSING
      ) {
        ws.close();
      }
    };
  }, []);

  return { events, status };
}
