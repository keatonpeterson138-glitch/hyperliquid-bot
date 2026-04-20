// Placeholder — Phase 6 ships the HIP-4 outcome workspace.

export function OutcomesPage() {
  return (
    <div className="page">
      <h1 className="page__title">Outcomes</h1>
      <section className="card">
        <h2 className="card__title">Coming in v0.3 (Phase 6)</h2>
        <p>
          The HIP-4 prediction-market workspace: outcome board grouped by
          category (crypto, politics, sports, macro), per-market detail view
          with probability curve and pricing-model edge, OutcomeSlot deployment.
        </p>
        <p className="muted">
          The tape API is already live: <code>GET /outcomes/{`{market_id}`}/tape</code>.
        </p>
      </section>
    </div>
  );
}
