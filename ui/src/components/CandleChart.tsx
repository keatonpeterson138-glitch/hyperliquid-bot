// Lightweight-charts wrapper — renders the main series (candle/line/area/bar),
// optional volume histogram, optional EMA overlays (12/26/50/200), optional
// RSI subpane, optional log-scale, and optional compare-mode overlays
// (other symbols normalized to 100 at first bar).
//
// Exposes priceToPixel / pixelToPrice converters via onCoordsChange so the
// MarkupLayer overlay positions drawings in sync with the main series.

import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  PriceScaleMode,
  createChart,
  type AreaData,
  type BarData,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import type { CandlesResponse } from "../api/types";
import { computeEMA, computeRSI, rebaseToHundred } from "../lib/indicators";
import type { ChartType, IndicatorState } from "../lib/workspaceStorage";

export type PriceToPixel = (price: number) => number;
export type PixelToPrice = (y: number) => number;

export interface ChartCoords {
  priceToPixel: PriceToPixel;
  pixelToPrice: PixelToPrice;
  width: number;
  height: number;
}

export interface OverlaySeries {
  symbol: string;
  data: CandlesResponse | null;
  color: string;
}

export interface CandleChartProps {
  data: CandlesResponse | null;
  height?: number;
  chartType?: ChartType;
  indicators?: IndicatorState;
  overlays?: OverlaySeries[];
  onCoordsChange?: (coords: ChartCoords | null) => void;
}

const CHART_COLORS = {
  up: "#3fb950",
  down: "#f85149",
  upFill: "#3fb95060",
  downFill: "#f8514960",
  text: "#e6edf3",
  grid: "#30363d",
  bg: "#0d1117",
  ema12: "#58a6ff",
  ema26: "#d2a8ff",
  ema50: "#f2cc60",
  ema200: "#ff7b72",
  rsi: "#bc8cff",
  line: "#58a6ff",
  area: "#58a6ff",
  overlay: ["#79c0ff", "#ff7b72", "#d2a8ff", "#ffa657", "#7ee787", "#ffab70", "#a5d6ff", "#ff9492"],
};

const DEFAULT_INDICATORS: IndicatorState = {
  ema12: false, ema26: false, ema50: false, ema200: false,
  rsi: false, volume: true, logScale: false,
};

const EMA_CONFIGS: Array<{ key: keyof IndicatorState; period: number; color: string }> = [
  { key: "ema12",  period: 12,  color: CHART_COLORS.ema12 },
  { key: "ema26",  period: 26,  color: CHART_COLORS.ema26 },
  { key: "ema50",  period: 50,  color: CHART_COLORS.ema50 },
  { key: "ema200", period: 200, color: CHART_COLORS.ema200 },
];

// Lightweight-charts Time — epoch seconds as a branded type.
const toTime = (iso: string): Time =>
  (Math.floor(new Date(iso).getTime() / 1000) as unknown) as Time;

export function CandleChart({
  data,
  height = 480,
  chartType = "candle",
  indicators = DEFAULT_INDICATORS,
  overlays = [],
  onCoordsChange,
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const emaSeriesRef = useRef<Partial<Record<keyof IndicatorState, ISeriesApi<"Line">>>>({});
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const coordsCbRef = useRef<typeof onCoordsChange>(onCoordsChange);
  coordsCbRef.current = onCoordsChange;

  // Rebuild the chart when layout/config changes (chart type, enabled
  // EMAs, RSI pane, log scale, volume, overlay count). The data effect
  // below then feeds series.
  //
  // We depend on the *count* of overlays rather than the array identity
  // so re-fetching an overlay's data doesn't tear down the chart.
  const overlayCount = overlays.length;
  const enabledEmaKeys = useMemo(
    () => EMA_CONFIGS.filter((c) => indicators[c.key]).map((c) => c.key).join(","),
    [indicators],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { color: CHART_COLORS.bg },
        textColor: CHART_COLORS.text,
      },
      grid: {
        vertLines: { color: CHART_COLORS.grid },
        horzLines: { color: CHART_COLORS.grid },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: CHART_COLORS.grid,
        barSpacing: 2,
        minBarSpacing: 0.5,
        rightOffset: 6,
      },
      rightPriceScale: {
        borderColor: CHART_COLORS.grid,
        mode: indicators.logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
      },
      crosshair: { mode: 1 },
    });

    // ── main series: one of candle / line / area / bar ──────────
    let mainSeries: ISeriesApi<SeriesType>;
    if (chartType === "line") {
      mainSeries = chart.addSeries(LineSeries, {
        color: CHART_COLORS.line, lineWidth: 2,
      });
    } else if (chartType === "area") {
      mainSeries = chart.addSeries(AreaSeries, {
        lineColor: CHART_COLORS.area, topColor: CHART_COLORS.area + "60", bottomColor: CHART_COLORS.area + "08",
      });
    } else if (chartType === "bar") {
      mainSeries = chart.addSeries(BarSeries, {
        upColor: CHART_COLORS.up, downColor: CHART_COLORS.down, openVisible: true,
      });
    } else {
      mainSeries = chart.addSeries(CandlestickSeries, {
        upColor: CHART_COLORS.up,
        downColor: CHART_COLORS.down,
        borderVisible: false,
        wickUpColor: CHART_COLORS.up,
        wickDownColor: CHART_COLORS.down,
      });
    }
    mainSeriesRef.current = mainSeries;

    // ── volume histogram on its own scale (pinned bottom 20%) ───
    if (indicators.volume) {
      const volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeriesRef.current = volume;
    } else {
      volumeSeriesRef.current = null;
    }

    // ── EMA overlays on the price axis ──────────────────────────
    emaSeriesRef.current = {};
    for (const cfg of EMA_CONFIGS) {
      if (!indicators[cfg.key]) continue;
      const line = chart.addSeries(LineSeries, {
        color: cfg.color, lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      });
      emaSeriesRef.current[cfg.key] = line;
    }

    // ── compare overlays — each symbol rebased to 100 ───────────
    overlaySeriesRef.current = new Map();
    overlays.forEach((o, idx) => {
      const color = o.color || CHART_COLORS.overlay[idx % CHART_COLORS.overlay.length];
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceScaleId: "overlay",
        lastValueVisible: false,
      }, 0);
      overlaySeriesRef.current.set(o.symbol, line);
    });
    if (overlays.length > 0) {
      chart.priceScale("overlay").applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.25 },
      });
    }

    // ── RSI pane below the price chart ──────────────────────────
    if (indicators.rsi) {
      const rsiLine = chart.addSeries(LineSeries, {
        color: CHART_COLORS.rsi, lineWidth: 1,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        lastValueVisible: false,
      }, 1);
      // Hints at the chart to give the RSI pane ~25% of the height.
      // lightweight-charts does pane sizing internally; options on the
      // pane are limited — we set the price range explicitly so the
      // axis stays 0-100.
      chart.panes()[1]?.setHeight(Math.max(80, Math.floor(height * 0.25)));
      rsiSeriesRef.current = rsiLine;
    } else {
      rsiSeriesRef.current = null;
    }

    chartRef.current = chart;

    const emitCoords = () => {
      const cb = coordsCbRef.current;
      if (!cb || !container || !mainSeriesRef.current) return;
      const series = mainSeriesRef.current;
      cb({
        priceToPixel: (p: number) => {
          const c = series.priceToCoordinate(p);
          return c ?? Number.NaN;
        },
        pixelToPrice: (y: number) => {
          const v = series.coordinateToPrice(y);
          return (v as number | null) ?? Number.NaN;
        },
        width: container.clientWidth,
        height,
      });
    };

    const resize = () => {
      if (!container) return;
      chart.applyOptions({ width: container.clientWidth, height });
      emitCoords();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    chart.timeScale().subscribeVisibleTimeRangeChange(emitCoords);
    emitCoords();

    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(emitCoords);
      coordsCbRef.current?.(null);
      chart.remove();
      mainSeriesRef.current = null;
      volumeSeriesRef.current = null;
      emaSeriesRef.current = {};
      rsiSeriesRef.current = null;
      overlaySeriesRef.current.clear();
    };
  }, [
    height,
    chartType,
    enabledEmaKeys,
    indicators.rsi,
    indicators.volume,
    indicators.logScale,
    overlayCount,
  ]);

  // Push main + indicators data into series whenever the prop changes.
  useEffect(() => {
    if (!data || !mainSeriesRef.current) return;
    const main = mainSeriesRef.current;

    if (chartType === "line") {
      const line: LineData[] = data.bars.map((b) => ({ time: toTime(b.timestamp), value: b.close }));
      (main as ISeriesApi<"Line">).setData(line);
    } else if (chartType === "area") {
      const area: AreaData[] = data.bars.map((b) => ({ time: toTime(b.timestamp), value: b.close }));
      (main as ISeriesApi<"Area">).setData(area);
    } else if (chartType === "bar") {
      const bars: BarData[] = data.bars.map((b) => ({
        time: toTime(b.timestamp), open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      (main as ISeriesApi<"Bar">).setData(bars);
    } else {
      const candles: CandlestickData[] = data.bars.map((b) => ({
        time: toTime(b.timestamp), open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      (main as ISeriesApi<"Candlestick">).setData(candles);
    }

    if (volumeSeriesRef.current) {
      const vol: HistogramData[] = data.bars.map((b) => ({
        time: toTime(b.timestamp),
        value: b.volume,
        color: b.close >= b.open ? CHART_COLORS.upFill : CHART_COLORS.downFill,
      }));
      volumeSeriesRef.current.setData(vol);
    }

    // EMAs — recompute per enabled series.
    const closes = data.bars.map((b) => b.close);
    const times = data.bars.map((b) => toTime(b.timestamp));
    for (const cfg of EMA_CONFIGS) {
      const series = emaSeriesRef.current[cfg.key];
      if (!series) continue;
      const ema = computeEMA(closes, cfg.period);
      const lineData: LineData[] = [];
      for (let i = 0; i < ema.length; i++) {
        const v = ema[i];
        if (v === null) continue;
        lineData.push({ time: times[i], value: v });
      }
      series.setData(lineData);
    }

    // RSI — 14-period.
    if (rsiSeriesRef.current) {
      const rsi = computeRSI(closes, 14);
      const rsiData: LineData[] = [];
      for (let i = 0; i < rsi.length; i++) {
        const v = rsi[i];
        if (v === null) continue;
        rsiData.push({ time: times[i], value: v });
      }
      rsiSeriesRef.current.setData(rsiData);
    }

    chartRef.current?.timeScale().fitContent();
  }, [data, chartType]);

  // Push overlay data (rebased to 100) per overlay symbol.
  useEffect(() => {
    for (const o of overlays) {
      const series = overlaySeriesRef.current.get(o.symbol);
      if (!series || !o.data) continue;
      const closes = o.data.bars.map((b) => b.close);
      const times = o.data.bars.map((b) => toTime(b.timestamp));
      const rebased = rebaseToHundred(closes);
      const lineData: LineData[] = [];
      for (let i = 0; i < rebased.length; i++) {
        const v = rebased[i];
        if (v === null) continue;
        lineData.push({ time: times[i], value: v });
      }
      series.setData(lineData);
    }
  }, [overlays]);

  return <div ref={containerRef} className="chart-container" style={{ position: "relative" }} />;
}
