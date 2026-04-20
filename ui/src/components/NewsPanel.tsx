// Live headlines from RSS + CryptoPanic feeds, pulled through /news.
// Auto-refreshes every 30s. Color-codes by impact (CRITICAL red,
// HIGH orange, MEDIUM yellow, LOW dim) and by sentiment
// (bullish green, bearish red, neutral muted).

import { useEffect, useState } from "react";

import { news } from "../api/endpoints";
import type { NewsItem } from "../api/endpoints";

const POLL_MS = 30_000;

export function NewsPanel() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [bias, setBias] = useState<string>("neutral");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await news.latest(30, "LOW");
        if (cancelled) return;
        setItems(r.items);
        setBias(r.sentiment_bias);
        setError(null);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    };
    void tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div>
      <div className="chart-toolbar" style={{ justifyContent: "space-between" }}>
        <h2 className="card__title">Live news</h2>
        <span className={`muted small tone--${biasTone(bias)}`}>
          sentiment: {bias}
        </span>
      </div>
      {error && <div className="error small">{error}</div>}
      {items.length === 0 ? (
        <p className="muted">No headlines yet. The news feed warms up over ~60s.</p>
      ) : (
        <ul className="news-list">
          {items.map((item) => (
            <li key={item.uid} className={`news-item impact--${item.impact.toLowerCase()}`}>
              <div className="news-item__head">
                <span className={`badge impact-badge--${item.impact.toLowerCase()}`}>{item.impact}</span>
                <span className={`sentiment--${item.sentiment}`}>{item.sentiment}</span>
                <span className="muted small">· {item.source}</span>
                <span className="muted small">· {item.published.slice(11, 16)}</span>
              </div>
              <a href={item.url} target="_blank" rel="noreferrer" className="news-item__head-link">
                {item.headline}
              </a>
              {item.matched_keywords.length > 0 && (
                <div className="muted small">keywords: {item.matched_keywords.slice(0, 5).join(", ")}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function biasTone(bias: string): "pos" | "neg" | undefined {
  if (bias === "bullish") return "pos";
  if (bias === "bearish") return "neg";
  return undefined;
}
