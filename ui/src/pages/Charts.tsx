// Placeholder — Phase 4 ships the real lightweight-charts workspace.

export function ChartsPage() {
  return (
    <div className="page">
      <h1 className="page__title">Charts</h1>
      <section className="card">
        <h2 className="card__title">Coming in v0.1 (Phase 4)</h2>
        <p>
          The real chart workspace ships in Phase 4: lightweight-charts price
          pane, indicator subpanes (volume, RSI, MACD, ATR), live streaming via
          WS, replay mode, 1/2/4-chart grid layouts.
        </p>
        <p className="muted">For now, query the data API directly:</p>
        <pre className="code">
          curl "http://127.0.0.1:8787/candles?symbol=BTC&interval=1h&from=2024-01-01"
        </pre>
      </section>
    </div>
  );
}
