// SVG overlay for chart drawings. Phase 5.5 — drag SL/TP to modify live
// orders (debounced 250ms); "Arm" a draft long/short position box to
// place a bracket order via /orders/from-markup.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { orders } from "../api/endpoints";

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
  order_id?: string | null;
}

export type PriceToPixel = (price: number) => number;

export interface MarkupLayerProps {
  symbol: string;
  interval: string;
  priceToPixel: PriceToPixel | null;
  pixelToPrice?: ((y: number) => number) | null;
  width: number;
  height: number;
}

const COLORS = {
  generic: "#f0b86c",
  entry: "#58a6ff",
  sl: "#f85149",
  tp: "#3fb950",
  fill: "#d2a8ff",
  muted: "#6e7681",
};

const TOOL_LABELS: Record<string, string> = {
  horizontal_line: "Horizontal",
  long_position: "Long",
  short_position: "Short",
  fill_marker: "Fill",
};

const MODIFY_DEBOUNCE_MS = 250;

type DragHandle =
  | { kind: "horizontal"; markupId: string }
  | { kind: "position_leg"; markupId: string; leg: "entry" | "sl" | "tp" };

export function MarkupLayer({
  symbol,
  interval,
  priceToPixel,
  pixelToPrice,
  width,
  height,
}: MarkupLayerProps) {
  const [markups, setMarkups] = useState<MarkupRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<DragHandle | null>(null);
  const [dragPrice, setDragPrice] = useState<number | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const refresh = useCallback(() => {
    setBusy(true);
    api
      .get<MarkupRow[]>(`/markups?symbol=${symbol}&interval=${interval}`)
      .then(setMarkups)
      .catch(() => setMarkups([]))
      .finally(() => setBusy(false));
  }, [symbol, interval]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── creators ────────────────────────────────────────────────────────
  const createHorizontal = async () => {
    const raw = prompt("Horizontal line at price:");
    if (!raw) return;
    const price = Number(raw);
    if (!Number.isFinite(price)) return;
    await api.post("/markups", { symbol, interval, tool_id: "horizontal_line", payload: { price } });
    refresh();
  };

  const createPosition = async (side: "long" | "short") => {
    const entry = Number(prompt("Entry price:"));
    if (!Number.isFinite(entry)) return;
    const sl = Number(prompt(`Stop-loss price (${side === "long" ? "below" : "above"} entry):`));
    if (!Number.isFinite(sl)) return;
    const tp = Number(prompt(`Take-profit price (${side === "long" ? "above" : "below"} entry):`));
    if (!Number.isFinite(tp)) return;
    await api.post("/markups", {
      symbol,
      interval,
      tool_id: side === "long" ? "long_position" : "short_position",
      payload: { entry, sl, tp },
    });
    refresh();
  };

  // ── arm: promote a draft position to a live order ──────────────────
  const armPosition = async (m: MarkupRow) => {
    if (m.tool_id !== "long_position" && m.tool_id !== "short_position") return;
    const raw = prompt("Size in USD:", "100");
    if (!raw) return;
    const size_usd = Number(raw);
    if (!Number.isFinite(size_usd) || size_usd <= 0) return;
    const levRaw = prompt("Leverage:", "5");
    const leverage = levRaw ? Number(levRaw) : null;
    if (!confirm(
      `Arm ${m.tool_id.replace("_", " ")} on ${m.symbol} for $${size_usd}${leverage ? ` @ ${leverage}x` : ""}?\n\n` +
      `Entry: ${m.payload.entry}\nSL: ${m.payload.sl}\nTP: ${m.payload.tp}`
    )) return;
    try {
      await orders.fromMarkup({ markup_id: m.id, size_usd, leverage });
      refresh();
    } catch (e) {
      alert(`Order failed: ${(e as Error).message}`);
    }
  };

  // ── drag handlers ───────────────────────────────────────────────────
  const scheduleModify = useCallback(
    (m: MarkupRow, leg: "entry" | "sl" | "tp", newPrice: number) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        // Persist the drag result to the markup.
        const newPayload = { ...m.payload, [leg]: newPrice };
        await api.patch(`/markups/${m.id}`, { payload: newPayload });
        // If this markup is wired to a working order, modify it too.
        if (m.order_id && (leg === "sl" || leg === "tp")) {
          try {
            await orders.modify(m.order_id, leg === "sl" ? { sl_price: newPrice } : { tp_price: newPrice });
          } catch (e) {
            alert(`Modify failed: ${(e as Error).message}`);
          }
        }
        refresh();
      }, MODIFY_DEBOUNCE_MS);
    },
    [refresh],
  );

  useEffect(() => {
    if (!drag || !pixelToPrice || !svgRef.current) return;

    const handleMove = (evt: PointerEvent) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const y = evt.clientY - rect.top;
      const price = pixelToPrice(y);
      if (Number.isFinite(price)) setDragPrice(price);
    };
    const handleUp = () => {
      if (dragPrice !== null) {
        const m = markups.find((x) => x.id === drag.markupId);
        if (m) {
          const leg = drag.kind === "position_leg" ? drag.leg : ("price" as "price");
          if (leg === "price") {
            // horizontal line: the key inside payload is "price"
            const newPayload = { ...m.payload, price: dragPrice };
            api.patch(`/markups/${m.id}`, { payload: newPayload }).then(refresh);
          } else {
            scheduleModify(m, leg, dragPrice);
          }
        }
      }
      setDrag(null);
      setDragPrice(null);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [drag, dragPrice, markups, pixelToPrice, refresh, scheduleModify]);

  const deleteOne = async (id: string) => {
    const m = markups.find((x) => x.id === id);
    if (m?.order_id) {
      if (!confirm("This markup is linked to a live order — cancel the order first?")) return;
      try { await orders.cancel(m.order_id); } catch { /* already gone? keep deleting */ }
    }
    await api.del(`/markups/${id}`);
    refresh();
  };

  const deleteAll = async () => {
    if (!confirm(`Delete all ${markups.length} drawing(s) on this chart?`)) return;
    await Promise.all(markups.map((m) => api.del(`/markups/${m.id}`)));
    refresh();
  };

  const visible = markups.filter((m) => !m.hidden);

  return (
    <div className="markup-layer">
      <div className="markup-toolbar">
        <button onClick={createHorizontal}>+ Horizontal</button>
        <button onClick={() => createPosition("long")}>+ Long</button>
        <button onClick={() => createPosition("short")}>+ Short</button>
        <button onClick={refresh} disabled={busy} title="Refresh">↻</button>
        <button onClick={deleteAll} disabled={markups.length === 0}>Clear all</button>
        <span className="muted small">{markups.length} drawing(s)</span>
      </div>

      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="markup-svg"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          pointerEvents: drag ? "auto" : "none",
        }}
      >
        {priceToPixel &&
          visible.map((m) =>
            renderMarkup(m, priceToPixel, width, {
              dragActive: drag?.markupId === m.id,
              dragLeg: drag && drag.kind === "position_leg" ? drag.leg : null,
              dragPrice,
              draggable: !!pixelToPrice && !m.locked,
              onHandleDown: (leg) => {
                if (m.tool_id === "horizontal_line") {
                  setDrag({ kind: "horizontal", markupId: m.id });
                } else {
                  setDrag({ kind: "position_leg", markupId: m.id, leg });
                }
              },
            }),
          )}
      </svg>

      {markups.length > 0 && (
        <div className="markup-list">
          {markups.map((m) => (
            <MarkupRowItem
              key={m.id}
              m={m}
              onDelete={() => deleteOne(m.id)}
              onArm={
                (m.tool_id === "long_position" || m.tool_id === "short_position") &&
                m.state === "draft"
                  ? () => armPosition(m)
                  : undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MarkupRowItem({
  m,
  onDelete,
  onArm,
}: {
  m: MarkupRow;
  onDelete: () => void;
  onArm?: () => void;
}) {
  const label = TOOL_LABELS[m.tool_id] ?? m.tool_id;
  const summary = summarizePayload(m);
  return (
    <div className="markup-row">
      <span className={`badge badge--${m.state}`}>{m.state}</span>
      <span className="markup-row__tool">{label}</span>
      <span className="markup-row__summary">{summary}</span>
      {m.order_id && <span className="muted small" title={m.order_id}>⚑</span>}
      {m.locked && <span className="muted small">🔒</span>}
      {m.hidden && <span className="muted small">hidden</span>}
      {onArm && <button onClick={onArm} title="Arm as live order">Arm</button>}
      <button onClick={onDelete} disabled={m.locked}>✕</button>
    </div>
  );
}

function summarizePayload(m: MarkupRow): string {
  const p = m.payload as Record<string, unknown>;
  const pf = (k: string) => {
    const v = p[k];
    return typeof v === "number" ? v.toFixed(2) : "—";
  };
  if (m.tool_id === "horizontal_line") return `@ ${pf("price")}`;
  if (m.tool_id === "long_position" || m.tool_id === "short_position") {
    return `entry ${pf("entry")} · sl ${pf("sl")} · tp ${pf("tp")}`;
  }
  if (m.tool_id === "fill_marker") {
    const side = (p.side as string | undefined) ?? "";
    return `${side.toUpperCase()} @ ${pf("price")}`;
  }
  return "";
}

interface RenderOpts {
  dragActive: boolean;
  dragLeg: "entry" | "sl" | "tp" | null;
  dragPrice: number | null;
  draggable: boolean;
  onHandleDown: (leg: "entry" | "sl" | "tp") => void;
}

function renderMarkup(
  m: MarkupRow,
  priceToPixel: PriceToPixel,
  width: number,
  opts: RenderOpts,
): React.ReactNode {
  if (m.tool_id === "horizontal_line") {
    return renderHorizontal(m, priceToPixel, width, opts);
  }
  if (m.tool_id === "long_position") {
    return renderPositionTriplet(m, priceToPixel, width, "long", opts);
  }
  if (m.tool_id === "short_position") {
    return renderPositionTriplet(m, priceToPixel, width, "short", opts);
  }
  if (m.tool_id === "fill_marker") {
    return renderFillMarker(m, priceToPixel, width);
  }
  return null;
}

function renderHorizontal(
  m: MarkupRow,
  priceToPixel: PriceToPixel,
  width: number,
  opts: RenderOpts,
) {
  const price = Number(m.payload.price);
  if (!Number.isFinite(price)) return null;
  const y =
    opts.dragActive && opts.dragPrice !== null
      ? priceToPixel(opts.dragPrice)
      : priceToPixel(price);
  if (!Number.isFinite(y)) return null;
  const color = COLORS.generic;
  const dash = m.state === "pending" ? "6 3" : "4 4";
  return (
    <g key={m.id}>
      <line x1={0} y1={y} x2={width} y2={y} stroke={color} strokeWidth={1} strokeDasharray={dash} />
      <text x={width - 6} y={y - 4} textAnchor="end" fill={color} fontSize="11">
        {(opts.dragActive && opts.dragPrice !== null ? opts.dragPrice : price).toFixed(2)}
      </text>
      {opts.draggable && (
        <rect
          x={0}
          y={y - 4}
          width={width}
          height={8}
          fill="transparent"
          style={{ cursor: "ns-resize", pointerEvents: "auto" }}
          onPointerDown={(e) => {
            e.stopPropagation();
            opts.onHandleDown("sl"); // horizontal doesn't have leg; ignored
          }}
        />
      )}
    </g>
  );
}

function renderPositionTriplet(
  m: MarkupRow,
  priceToPixel: PriceToPixel,
  width: number,
  side: "long" | "short",
  opts: RenderOpts,
) {
  const entryOrig = Number(m.payload.entry);
  const slOrig = Number(m.payload.sl);
  const tpOrig = Number(m.payload.tp);
  if (![entryOrig, slOrig, tpOrig].every(Number.isFinite)) return null;

  const entry = opts.dragActive && opts.dragLeg === "entry" && opts.dragPrice !== null ? opts.dragPrice : entryOrig;
  const sl = opts.dragActive && opts.dragLeg === "sl" && opts.dragPrice !== null ? opts.dragPrice : slOrig;
  const tp = opts.dragActive && opts.dragLeg === "tp" && opts.dragPrice !== null ? opts.dragPrice : tpOrig;

  const yEntry = priceToPixel(entry);
  const ySl = priceToPixel(sl);
  const yTp = priceToPixel(tp);
  if (![yEntry, ySl, yTp].every(Number.isFinite)) return null;

  return (
    <g key={m.id}>
      <rect
        x={0}
        y={Math.min(yEntry, ySl)}
        width={width}
        height={Math.abs(yEntry - ySl)}
        fill={COLORS.sl}
        fillOpacity={0.08}
      />
      <rect
        x={0}
        y={Math.min(yEntry, yTp)}
        width={width}
        height={Math.abs(yEntry - yTp)}
        fill={COLORS.tp}
        fillOpacity={0.08}
      />
      <DraggableLeg
        y={yEntry}
        width={width}
        color={COLORS.entry}
        label={`${side.toUpperCase()} ${entry.toFixed(2)}`}
        onDown={opts.draggable ? () => opts.onHandleDown("entry") : undefined}
      />
      <DraggableLeg
        y={ySl}
        width={width}
        color={COLORS.sl}
        label={`SL ${sl.toFixed(2)}`}
        dash="3 3"
        onDown={opts.draggable ? () => opts.onHandleDown("sl") : undefined}
      />
      <DraggableLeg
        y={yTp}
        width={width}
        color={COLORS.tp}
        label={`TP ${tp.toFixed(2)}`}
        dash="3 3"
        onDown={opts.draggable ? () => opts.onHandleDown("tp") : undefined}
      />
    </g>
  );
}

function DraggableLeg({
  y,
  width,
  color,
  label,
  dash,
  onDown,
}: {
  y: number;
  width: number;
  color: string;
  label: string;
  dash?: string;
  onDown?: () => void;
}) {
  return (
    <>
      <line x1={0} y1={y} x2={width} y2={y} stroke={color} strokeWidth={1} strokeDasharray={dash} />
      <text x={width - 6} y={y - 4} textAnchor="end" fill={color} fontSize="11">{label}</text>
      {onDown && (
        <rect
          x={0}
          y={y - 4}
          width={width}
          height={8}
          fill="transparent"
          style={{ cursor: "ns-resize", pointerEvents: "auto" }}
          onPointerDown={(e) => {
            e.stopPropagation();
            onDown();
          }}
        />
      )}
    </>
  );
}

function renderFillMarker(m: MarkupRow, priceToPixel: PriceToPixel, width: number) {
  const price = Number(m.payload.price);
  if (!Number.isFinite(price)) return null;
  const y = priceToPixel(price);
  if (!Number.isFinite(y)) return null;
  const side = String(m.payload.side ?? "").toLowerCase();
  const tip = width - 4;
  const base = tip - 8;
  const pts =
    side === "sell"
      ? `${tip},${y} ${base},${y - 4} ${base},${y + 6}`
      : `${tip},${y} ${base},${y + 4} ${base},${y - 6}`;
  return (
    <g key={m.id}>
      <polygon points={pts} fill={COLORS.fill} opacity={0.85} />
    </g>
  );
}
