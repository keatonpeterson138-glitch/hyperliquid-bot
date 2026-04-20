// Lightweight-charts wrapper — takes data, draws candles + volume,
// updates on bar close. Resize-aware.

import {
  CandlestickSeries,
  HistogramSeries,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { CandlesResponse } from "../api/types";

export interface CandleChartProps {
  data: CandlesResponse | null;
  height?: number;
}

const CHART_COLORS = {
  up: "#3fb950",
  down: "#f85149",
  upFill: "#3fb95060",
  downFill: "#f8514960",
  text: "#e6edf3",
  grid: "#30363d",
  bg: "#0d1117",
};

export function CandleChart({ data, height = 480 }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // One-time chart construction + resize wiring.
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
      },
      rightPriceScale: { borderColor: CHART_COLORS.grid },
      crosshair: { mode: 1 }, // magnet to nearest data point
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: CHART_COLORS.up,
      downColor: CHART_COLORS.down,
      borderVisible: false,
      wickUpColor: CHART_COLORS.up,
      wickDownColor: CHART_COLORS.down,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    const resize = () => {
      if (!container) return;
      chart.applyOptions({ width: container.clientWidth, height });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [height]);

  // Push data into series whenever the prop changes.
  useEffect(() => {
    if (!data || !candleRef.current || !volumeRef.current) return;
    const candles: CandlestickData[] = data.bars.map((b) => ({
      time: (Math.floor(new Date(b.timestamp).getTime() / 1000) as unknown) as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    const volumes: HistogramData[] = data.bars.map((b) => ({
      time: (Math.floor(new Date(b.timestamp).getTime() / 1000) as unknown) as Time,
      value: b.volume,
      color: b.close >= b.open ? CHART_COLORS.upFill : CHART_COLORS.downFill,
    }));
    candleRef.current.setData(candles);
    volumeRef.current.setData(volumes);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={containerRef} className="chart-container" />;
}
