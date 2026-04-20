// SVG overlay for chart drawings. Phase 5 scope: horizontal lines (SL/TP
// intent) and long/short position boxes. Drag-to-modify + order arming
// lands in Phase 5.5 once the /orders REST endpoint is ready.

import { useEffect, useState } from "react";

import { api } from "../api/client";

export interface MarkupRow {
  id: string;
  symbol: string;
  interval: string | null;
  tool_id: string;
  payload: Record<string, unknown>;
  style: Record<string, unknown>;
  state: string;
  locked: boolean;
  hidden: boolean;
}

export interface MarkupLayerProps {
  symbol: string;
  interval: string;
  // Pixel-space converters from the chart API.
  priceToPixel: (price: number) => number;
  width: number;
  height: number;
}

export function MarkupLayer({
  symbol,
  interval,
  priceToPixel,
  width,
  height,
}: MarkupLayerProps) {
  const [markups, setMarkups] = useState<MarkupRow[]>([]);
  const [draft, setDraft] = useState<{ tool: string; price?: number } | null>(null);

  const refresh = () =>
    api
      .get<MarkupRow[]>(`/markups?symbol=${symbol}&interval=${interval}`)
      .then(setMarkups)
      .catch(() => undefined);

  useEffect(() => {
    refresh();
  }, [symbol, interval]);

  const addHorizontal = async () => {
    const raw = prompt("Horizontal line at price:");
    if (!raw) return;
    const price = Number(raw);
    if (Number.isNaN(price)) return;
    await api.post("/markups", {
      symbol,
      interval,
      tool_id: "horizontal_line",
      payload: { price },
    });
    refresh();
  };

  const deleteAll = async () => {
    if (!confirm("Delete every drawing on this chart?")) return;
    await Promise.all(markups.map((m) => api.del(`/markups/${m.id}`)));
    refresh();
  };

  return (
    <div className="markup-layer" style={{ width, height }}>
      <div className="markup-toolbar">
        <button onClick={addHorizontal}>+ Horizontal line</button>
        <button onClick={refresh}>Refresh</button>
        <button onClick={deleteAll} disabled={markups.length === 0}>
          Clear all
        </button>
        <span className="muted small">{markups.length} drawing(s)</span>
      </div>
      <svg width={width} height={height} className="markup-svg">
        {markups
          .filter((m) => !m.hidden)
          .map((m) => renderMarkup(m, priceToPixel, width))}
      </svg>
    </div>
  );
}

function renderMarkup(
  m: MarkupRow,
  priceToPixel: (p: number) => number,
  width: number,
) {
  if (m.tool_id === "horizontal_line") {
    const price = Number(m.payload.price);
    if (Number.isNaN(price)) return null;
    const y = priceToPixel(price);
    if (!Number.isFinite(y)) return null;
    return (
      <g key={m.id}>
        <line
          x1={0}
          y1={y}
          x2={width}
          y2={y}
          stroke="#f0b86c"
          strokeWidth={1}
          strokeDasharray="4 4"
        />
        <text x={width - 6} y={y - 4} textAnchor="end" fill="#f0b86c" fontSize="11">
          {price.toFixed(2)}
        </text>
      </g>
    );
  }
  return null;
}
