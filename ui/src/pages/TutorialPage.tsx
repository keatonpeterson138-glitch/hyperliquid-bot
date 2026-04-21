// In-app tutorial — written for someone who's never used the app before.
// Pure markdown-ish JSX; no dependencies. Update sections as features land.

export function TutorialPage() {
  return (
    <div className="page tutorial">
      <h1 className="page__title">Tutorial</h1>
      <p className="muted">
        Everything you need to go from "just installed" to "running a backtested
        bot on Hyperliquid". Each section is independent — skip ahead if you
        already know the basics.
      </p>

      <Section title="1 · First launch" anchor="first-launch">
        <p>
          When you launch the app, the Python backend (the "sidecar") starts in
          the background and listens on <code>127.0.0.1:8787</code>. It takes
          5-15 seconds on cold start (it has to extract a bundled Python runtime
          to a temp folder).
        </p>
        <p>
          If anything fails on startup, the file{" "}
          <code>%LOCALAPPDATA%\hyperliquid-bot\logs\boot.log</code> will tell
          you what went wrong. <code>backend.log</code> in the same folder has
          full structured logs.
        </p>
        <Tip>
          The dashboard top-right shows a green dot when the sidecar is up. If
          it's red after 30 seconds, check the boot log.
        </Tip>
      </Section>

      <Section title="2 · API keys" anchor="api-keys">
        <p>
          Sidebar → <b>API Keys</b>. Free providers like FRED + Alpha Vantage
          are pre-loaded if you installed the bundled MSI. To add more:
        </p>
        <ul>
          <li><b>FRED</b> — free at <code>fred.stlouisfed.org</code>. Used by the FRED Explorer.</li>
          <li><b>Alpha Vantage</b> — free tier (25 req/day) at <code>alphavantage.co</code>. Stock data.</li>
          <li><b>CoinGecko</b> — no key needed for free tier; skip unless you have Pro.</li>
          <li><b>CryptoCompare</b> — optional, deeper crypto history.</li>
          <li><b>Plaid</b> — for the Balances tab. Add <code>client_id</code> + <code>secret</code>, set metadata <code>{"{ \"environment\": \"sandbox\" }"}</code>.</li>
          <li><b>E*Trade</b> — register at <code>developer.etrade.com</code>, then OAuth flow on the Balances page.</li>
        </ul>
        <p>
          The <b>Backup & Restore</b> section on the API Keys page exports
          everything to a plain JSON file — keep it safe (it has your raw
          keys), then import it after a reinstall to skip re-entering them.
        </p>
      </Section>

      <Section title="3 · Hyperliquid wallet (perp trading)" anchor="wallet">
        <p>
          Two paths to put trading credentials on the box:
        </p>
        <ol>
          <li>
            <b>MetaMask + Agent Wallet (recommended).</b> Sidebar →{" "}
            <b>Wallet</b> → "Connect MetaMask". Sign one EIP-712 "ApproveAgent"
            message and the app generates a local agent keypair, stores it in
            the OS keychain, and uses it for every order. You retain full
            control — revoke the agent any time from the Vault page.
          </li>
          <li>
            <b>Direct private key (advanced).</b> Sidebar → <b>Vault</b> → enter
            wallet address + private key. Goes straight into the OS keychain;
            never touches a file.
          </li>
        </ol>
        <Tip>
          Until the vault is unlocked, every trading endpoint returns 503. The
          chart workspace, backtesting, research, and Data Lab still work
          fully — they don't need the wallet.
        </Tip>
      </Section>

      <Section title="4 · Charts workspace" anchor="charts">
        <p>
          Sidebar → <b>Charts</b>. Tile up to 8 charts in a grid. Each tile has:
        </p>
        <ul>
          <li><b>Symbol dropdown</b> — every Hyperliquid perp + stocks (TSLA, AAPL, NVDA, ...) + indices (^GSPC, ^VIX) + FRED macro (DGS10, CPIAUCSL, ...) + HIP-3 perps (xyz:SP500, cash:GOLD).</li>
          <li><b>Interval</b> — 1m up to 1M.</li>
          <li><b>Chart type</b> — candle / bar / line / area.</li>
          <li><b>Indicators</b> — EMA 12/26/50/200, RSI(14) subpane, volume, log-scale toggle.</li>
          <li><b>Overlays</b> — add another symbol normalized to 100 to compare performance.</li>
          <li><b>Markups</b> — only on single-tile layout. Click on the chart to draw lines / horizontal levels / Fibonacci. Right-click to convert a markup into an order ticket.</li>
        </ul>
        <p>
          The whole workspace (layout, per-tile config, overlays) persists to{" "}
          <code>localStorage["charts.workspace.v1"]</code>. Switching tabs +
          coming back keeps your setup. Click "Reset workspace" to start fresh.
        </p>
      </Section>

      <Section title="5 · Slots (running bots)" anchor="slots">
        <p>
          A <b>slot</b> is one persistent bot config: strategy + symbol +
          interval + risk params. The trade engine ticks each enabled slot on
          its bar cadence and places orders when the strategy emits a signal.
        </p>
        <p>
          <b>Easiest start:</b> Sidebar → Slots → "Backtested presets".
          Currently four ship out of the box (Keltner + Williams %R on SPY and
          QQQ — all backtested 75%+ WR). Click "Add slot" to instantiate one;
          it'll be created <b>disabled</b>. Click <b>Start</b> when you're
          ready and the wallet is unlocked.
        </p>
        <p>
          <b>Custom slot:</b> click "+ New slot" — pick any symbol /
          strategy / size / leverage / SL / TP. Five strategies ship today:
          {" "}<code>connors_rsi2</code>, <code>bb_fade</code>,{" "}
          <code>keltner_reversion</code>, <code>williams_mean_rev</code>,
          {" "}<code>gap_fill</code>. See{" "}
          <code>internal_docs/trading_presets.md</code> for backtest evidence
          across BTC / ETH / SPY / QQQ / TSLA / GOLD / OIL.
        </p>
        <Tip>
          The big red <b>Kill Switch</b> in the title bar flattens every
          position + cancels every order + disables every slot in one click.
          Use it any time something feels wrong.
        </Tip>
      </Section>

      <Section title="6 · Backtesting" anchor="backtest">
        <p>
          Sidebar → <b>Backtest</b>. Pick a strategy, asset, date range. The
          engine replays bar-by-bar against the local Parquet lake and reports
          trades, win rate, Sharpe, max drawdown.
        </p>
        <p>
          Run a <b>parameter sweep</b> to grid-search a strategy's settings,
          or kick off a <b>Monte Carlo</b> reshuffle of trade order to
          quantify path-dependence risk.
        </p>
      </Section>

      <Section title="7 · Research workbench" anchor="research">
        <p>
          Sidebar → <b>Research</b>. Pre-built studies for:
        </p>
        <ul>
          <li><b>Funding-rate analysis</b> — distribution + persistence.</li>
          <li><b>Volatility regimes</b> — clustering, GARCH-style decomposition.</li>
          <li><b>Cross-asset correlation</b> — rolling correlation matrices.</li>
          <li><b>Analog search</b> — pattern-match the current setup against history.</li>
        </ul>
      </Section>

      <Section title="8 · Models (ML)" anchor="models">
        <p>
          Sidebar → <b>Models</b>. Train ML models with:
        </p>
        <ul>
          <li>Triple-barrier labeling (de Prado AFML ch. 3)</li>
          <li>Purged k-fold + embargo cross-validation (ch. 7)</li>
          <li>Optuna TPE bayesian hyperparameter search</li>
        </ul>
        <p>
          Trained models live in <code>%LOCALAPPDATA%\hyperliquid-bot\data\models\</code>.
          Promote one to a slot via the <b>Promote</b> button — the slot's
          strategy will then use the model's predictions as its signal.
        </p>
      </Section>

      <Section title="9 · Data Lab" anchor="data">
        <p>
          Sidebar → <b>Data Lab</b>. Browse the local Parquet lake — every
          (symbol, interval) tuple, with row counts and date ranges. Use the
          "Load history" panel to backfill specific symbols on demand.
        </p>
        <p>
          The macro seed service auto-backfills S&P, Nasdaq, WTI, Gold,
          Silver, BTC, ETH, SOL on first launch (10-20 years daily, 1-3 years
          hourly), so you don't need to do this for the basics.
        </p>
      </Section>

      <Section title="10 · Live Squawk + News" anchor="news">
        <p>
          Sidebar → <b>Live Squawk</b> for a Telegram channel feed.
          Sidebar → <b>News</b> for an RSS + CryptoPanic poller. Both are
          read-only signal feeds; they don't drive trading directly.
        </p>
      </Section>

      <Section title="11 · Audit + safety" anchor="safety">
        <p>
          Sidebar → <b>Audit</b>. Append-only log of every trade, every config
          change, every key event. Cannot be edited or deleted from the UI.
          Export to CSV for compliance / tax.
        </p>
        <p>
          Settings → <b>Risk</b> tab to set:
        </p>
        <ul>
          <li>Confirmation threshold $ for any trade above N USD</li>
          <li>Confirmation modal for any size change &gt; N%</li>
          <li>Confirmation modal for any leverage above N×</li>
          <li>Aggregate exposure cap across slots</li>
        </ul>
      </Section>

      <Section title="12 · Where stuff lives on disk" anchor="filesystem">
        <p>Everything user-writable is under <code>%LOCALAPPDATA%\hyperliquid-bot\</code>:</p>
        <ul>
          <li><code>data\app.db</code> — SQLite (slots, audit log, credentials, balances, plaid, notes)</li>
          <li><code>data\settings.json</code> — app settings</li>
          <li><code>data\models\</code> — trained ML models</li>
          <li><code>data\parquet\ohlcv\</code> — OHLCV lake (Hive partitioned by symbol / interval / year)</li>
          <li><code>logs\boot.log</code> — sidecar boot trail (last 20 launches)</li>
          <li><code>logs\backend.log</code> — full structured logs (5 MB rotating × 3)</li>
        </ul>
        <Tip>
          To export your full setup, copy the entire folder. To start fresh,
          delete it and relaunch — the macro seed will repopulate the lake.
        </Tip>
      </Section>
    </div>
  );
}

function Section({ title, anchor, children }: { title: string; anchor: string; children: React.ReactNode }) {
  return (
    <section className="card tutorial__section" id={anchor}>
      <h2 className="card__title">{title}</h2>
      {children}
    </section>
  );
}

function Tip({ children }: { children: React.ReactNode }) {
  return (
    <div className="tutorial__tip">
      <strong>Tip:</strong> {children}
    </div>
  );
}
