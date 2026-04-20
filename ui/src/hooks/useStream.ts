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

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        retryDelay = 500;
        setStatus("open");
      };
      ws.onmessage = (msg) => {
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
        setStatus("closed");
        if (cancelled) return;
        reconnectTimer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 10_000);
      };
      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);

  return { events, status };
}
