// Probability curve for a single HIP-4 outcome market.
// Line series bounded [0, 1] (no candles) — probability is the natural
// view for a prediction market, not OHLC.

import {
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { OutcomeTick } from "../api/types";

export interface ProbabilityChartProps {
  ticks: OutcomeTick[];
  theoretical?: number | null;
  height?: number;
}

const COLORS = {
  market: "#58a6ff",
  theory: "#d2a8ff",
  text: "#e6edf3",
  grid: "#30363d",
  bg: "#0d1117",
};

export function ProbabilityChart({
  ticks,
  theoretical,
  height = 360,
}: ProbabilityChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const marketRef = useRef<ISeriesApi<"Line"> | null>(null);
  const theoryRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { color: COLORS.bg },
        textColor: COLORS.text,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: COLORS.grid,
      },
      rightPriceScale: {
        borderColor: COLORS.grid,
        autoScale: false,
      },
    });

    chart.priceScale("right").applyOptions({
      autoScale: false,
    });

    const market = chart.addSeries(LineSeries, {
      color: COLORS.market,
      lineWidth: 2,
      priceFormat: { type: "price", precision: 3, minMove: 0.001 },
      priceLineVisible: true,
    });

    const theory = chart.addSeries(LineSeries, {
      color: COLORS.theory,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceFormat: { type: "price", precision: 3, minMove: 0.001 },
      priceLineVisible: false,
    });

    chartRef.current = chart;
    marketRef.current = market;
    theoryRef.current = theory;

    // Anchor the visible price range to [0, 1] so the probability scale
    // is always readable.
    market.applyOptions({
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 1 },
      }),
    });

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [height]);

  useEffect(() => {
    const market = marketRef.current;
    const theory = theoryRef.current;
    if (!market || !theory) return;

    const points: LineData[] = ticks
      .map((t) => ({
        time: (Math.floor(new Date(t.timestamp).getTime() / 1000) as unknown) as Time,
        value: t.implied_prob,
      }))
      // Dedupe collisions on the same second — lightweight-charts requires
      // strictly increasing time keys.
      .reduce<LineData[]>((acc, cur) => {
        if (acc.length === 0 || acc[acc.length - 1].time !== cur.time) {
          acc.push(cur);
        } else {
          acc[acc.length - 1] = cur;
        }
        return acc;
      }, []);

    market.setData(points);

    if (
      typeof theoretical === "number" &&
      Number.isFinite(theoretical) &&
      points.length > 0
    ) {
      theory.setData([
        { time: points[0].time, value: theoretical },
        { time: points[points.length - 1].time, value: theoretical },
      ]);
    } else {
      theory.setData([]);
    }

    chartRef.current?.timeScale().fitContent();
  }, [ticks, theoretical]);

  return <div ref={containerRef} className="chart-container" />;
}
