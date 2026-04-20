# Phase 1 — Data Platform: Implementation Plan

**Goal:** Pull, store, and query historical + live OHLCV + outcome tapes for the full Hyperliquid universe, stitched from multiple sources for maximum depth. Every later phase reads through this layer.

**Scope:** 2 weeks at 1 FTE. ~10 commits, each independently shippable.

**Prerequisites:** Phase 0 complete (✓). `backend/` + `ui/` scaffolded (✓). Tests + CI live (✓).

**Companion docs:** `OVERHAUL_PLAN.md §6` (data platform overview), `Design.md §7` (current contract).

---

## 1. Target End State

After Phase 1, the following must work:

- `python -m backend.tools.backfill --symbol BTC --interval 1h --depth max` → stitches 2015+ history from Coinbase + Binance + Hyperliquid into Parquet.
- `python -m backend.tools.backfill --symbol xyz:TSLA --interval 1h --from 2025-10-01` → HIP-3 via Hyperliquid + equity history via yfinance.
- `uvicorn backend.main:app` then `GET /candles?symbol=BTC&interval=1h&from=2024-01-01&to=2024-12-31` → 8,784 bars from DuckDB view.
- Tauri shell + backend: `ws://.../stream/candles?symbol=BTC&interval=1h` pushes each bar close in real time.
- `GET /catalog` lists every symbol/interval combo present in the lake with earliest/latest timestamps.
- HIP-4 outcome markets have their own tape: `GET /outcomes/{id}/tape?from=&to=`.

All this without touching `bot.py` or `dashboard.py` (they keep working in legacy mode).

---

## 2. Storage Layout (reference)

```
data/
├── parquet/
│   ├── ohlcv/
│   │   └── symbol=<s>/interval=<i>/year=<y>/part-000.parquet
│   └── outcomes/
│       └── market_id=<id>/year=<y>/part-000.parquet
├── duckdb/
│   └── catalog.db       # views over parquet/ohlcv and parquet/outcomes
└── app.db               # sqlite (markets + tags; lands in Phase 2)
```

Partition key rationale:
- `symbol` first → typical query scope ("all BTC 1h"). Prune to one dir.
- `interval` second → pick one timeframe per query.
- `year` third → historical scans bounded.

OHLCV schema (pyarrow):
```python
pa.schema([
    ("timestamp",   pa.timestamp("ms", tz="UTC")),
    ("open",        pa.float64()),
    ("high",        pa.float64()),
    ("low",         pa.float64()),
    ("close",       pa.float64()),
    ("volume",      pa.float64()),
    ("trades",      pa.int64()),      # null for sources that don't expose
    ("source",      pa.string()),     # 'hyperliquid' | 'binance' | 'coinbase' | 'yfinance' | 'cryptocompare'
    ("ingested_at", pa.timestamp("ms", tz="UTC")),
])
```

Outcome tape schema:
```python
pa.schema([
    ("timestamp",    pa.timestamp("ms", tz="UTC")),
    ("price",        pa.float64()),          # [0, 1]
    ("volume",       pa.float64()),
    ("implied_prob", pa.float64()),          # same as price for pure binaries
    ("best_bid",     pa.float64()),
    ("best_ask",     pa.float64()),
    ("event_id",     pa.string()),
    ("source",       pa.string()),
    ("ingested_at",  pa.timestamp("ms", tz="UTC")),
])
```

Dedupe key: `(symbol, interval, timestamp, source)`. Last-write-wins per ingestion.

---

## 3. Commit Plan (ordered)

Each bullet is one reviewable commit. Dependencies flow top-down.

### P1.1 — `DataSource` protocol + `HyperliquidSource` adapter

**Files created:**
- `backend/services/sources/__init__.py`
- `backend/services/sources/base.py` — `DataSource` Protocol, `CandleFrame` dataclass, `CANDLE_COLUMNS` canonical column list.
- `backend/services/sources/hyperliquid_source.py` — wraps `core/market_data.MarketData` to implement `DataSource`.
- `tests/unit/backend/sources/__init__.py`
- `tests/unit/backend/sources/test_hyperliquid_source.py`

**Interfaces exposed:**
```python
class DataSource(Protocol):
    name: str
    def supports(self, symbol: str, interval: str) -> bool: ...
    def earliest_available(self, symbol: str, interval: str) -> datetime | None: ...
    def fetch_candles(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> CandleFrame: ...

@dataclass(frozen=True)
class CandleFrame:
    symbol: str
    interval: str
    source: str
    bars: pd.DataFrame          # canonical columns, UTC timestamp index
    fetched_at: datetime
```

**Test coverage:**
- Fetches a small range with mocked `hyperliquid.info.Info.candles_snapshot`.
- `supports()` returns True for native perp symbols and `dex:symbol` formats.
- Columns match `CANDLE_COLUMNS` on a blank range.
- `ingested_at` populated.

**Risks:** Hyperliquid Info API is rate-limited — add a simple retry wrapper with 1s/2s/4s backoff.

---

### P1.2 — Source adapters for historical crypto (Binance, Coinbase)

**Files created:**
- `backend/services/sources/binance_source.py` — REST klines (`/api/v3/klines`), public endpoint, paginated 1000-bar chunks.
- `backend/services/sources/coinbase_source.py` — `/api/v3/brokerage/market/products/{product}/candles` for spot history back to 2015.
- `tests/unit/backend/sources/test_binance_source.py`
- `tests/unit/backend/sources/test_coinbase_source.py`

**Test coverage:**
- `respx` or `httpx.MockTransport` fake-serves one paginated response; adapter walks pagination, assembles frame.
- `earliest_available` returns sensible dates (2017-08 for BTC on Binance, 2015-07 for BTC on Coinbase).
- `supports("xyz:TSLA", "1h")` returns False (crypto-only).

**Risks:** Coinbase API authentication — public candles endpoint requires no auth; confirm in docs.

---

### P1.3 — Source adapter for equities / commodities (yfinance)

**Files created:**
- `backend/services/sources/yfinance_source.py` — wraps `yfinance.download()` for SPY, QQQ, NVDA, TSLA, GC=F, CL=F, etc.
- `tests/unit/backend/sources/test_yfinance_source.py`

**Mapping:**
```python
HIP3_TO_YFINANCE = {
    "xyz:NVDA": "NVDA",
    "xyz:TSLA": "TSLA",
    "xyz:AAPL": "AAPL",
    ...
    "xyz:SP500": "SPY",           # proxy
    "xyz:XYZ100": "QQQ",          # proxy
    "cash:GOLD": "GC=F",
    "cash:SILVER": "SI=F",
    "cash:OIL": "CL=F",
    "cash:CORN": "ZC=F",
    "cash:WHEAT": "ZW=F",
}
```

**Test coverage:**
- Mocked `yfinance.download` returns a small DataFrame; adapter normalises to `CANDLE_COLUMNS`.
- Symbol mapping is applied correctly.
- `supports("BTC", "1h")` returns False (no crypto).

**Risks:** yfinance is fragile (Yahoo API changes). Mark tests `@pytest.mark.network` so they can be skipped on flaky runs. Consider CryptoCompare as backup in a later commit.

---

### P1.4 — `SourceRouter` with stitching + cross-validation

**Files created:**
- `backend/services/source_router.py` — `SourceRouter.plan(symbol, interval, start, end) -> list[SourceSlice]`. Returns source-slice tuples covering the range, preferring primary then stitching older history from fallbacks.
- `backend/services/source_router.py::cross_validate(symbol, interval, start, end) -> ValidationResult` — pulls from two sources in parallel, compares close-price divergence on overlap.
- `tests/unit/backend/services/test_source_router.py`

**Data flow:**
```
plan("BTC", "1h", 2015-01-01, 2026-01-01):
  primary = HyperliquidSource
  hyperliquid.earliest_available("BTC", "1h")  →  2024-05-01
  fallbacks = [BinanceSource, CoinbaseSource]
  # First: fill earliest back via fallbacks in order
  binance.earliest_available("BTC", "1h")       →  2017-08-17
  coinbase.earliest_available("BTC", "1h")      →  2015-07-20
  →  [
       SourceSlice(coinbase, 2015-07-20 → 2017-08-17),
       SourceSlice(binance,  2017-08-17 → 2024-05-01),
       SourceSlice(hyperliquid, 2024-05-01 → now),
     ]
```

**Test coverage:**
- Full stitch across all three sources.
- Single-source fallback when primary covers the whole range.
- Overlap handling: sources that overlap → later source wins the duplicated range.
- `cross_validate` returns zero divergence on identical mocked data, non-zero otherwise.

---

### P1.5 — Parquet writer + reader with Hive partitioning

**Files created:**
- `backend/db/paths.py` — `ohlcv_partition_path(symbol, interval, year) -> Path`, `outcome_partition_path(market_id, year)`.
- `backend/db/parquet_writer.py` — `append_ohlcv(frame: CandleFrame)` writes rows to the correct partition, dedupe-aware.
- `backend/db/parquet_reader.py` — `read_ohlcv(symbol, interval, start, end) -> pd.DataFrame`.
- `backend/db/schemas.py` — pyarrow schemas for OHLCV and outcomes.
- `tests/unit/backend/db/test_parquet_io.py`

**Data flow:**
```
append_ohlcv(frame):
  for year, year_slice in groupby(frame.bars, by='timestamp.year'):
    path = ohlcv_partition_path(symbol, interval, year)
    existing = read_parquet(path) if path.exists() else empty()
    combined = dedupe(existing + year_slice, key=(timestamp, source))
    write_parquet(path, combined, schema=OHLCV_SCHEMA, compression='zstd')
```

**Test coverage:**
- Round-trip: write → read identical.
- Append: second write adds new rows, does not overwrite.
- Dedupe: writing an overlapping range with same `(ts, source)` doesn't duplicate.
- Year boundary: bars spanning Dec 31 → Jan 1 land in two partitions.
- Schema enforcement: unexpected columns dropped; missing columns filled null.

**Risks:** atomic writes — use temp file + rename to avoid partial-write reads.

---

### P1.6 — DuckDB catalog + query layer

**Files created:**
- `backend/db/duckdb_catalog.py` — `open_catalog() -> duckdb.DuckDBPyConnection`, creates views `ohlcv`, `outcomes` over the Parquet tree.
- `backend/db/query.py` — `query_candles(symbol, interval, start, end) -> pd.DataFrame` uses DuckDB partition pruning.
- `tests/unit/backend/db/test_duckdb_catalog.py`

**Views:**
```sql
CREATE OR REPLACE VIEW ohlcv AS
  SELECT *, symbol, interval, year  -- hive_partitioning exposes these as columns
  FROM read_parquet('data/parquet/ohlcv/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW outcomes AS
  SELECT *, market_id, year
  FROM read_parquet('data/parquet/outcomes/**/*.parquet', hive_partitioning=true);
```

**Test coverage:**
- Query a known range with seeded parquet files, assert row count + column order.
- Partition pruning: query scoped to one year only touches that year's partitions (verify via `EXPLAIN`).
- Empty-lake query returns empty DataFrame, not an error.

---

### P1.7 — Backfill CLI

**Files created:**
- `backend/tools/__init__.py`
- `backend/tools/backfill.py` — `python -m backend.tools.backfill` with click or argparse.
- `tests/unit/backend/tools/test_backfill.py`

**CLI surface:**
```
python -m backend.tools.backfill \
    --symbol BTC \
    --interval 1h \
    --from 2015-01-01 \
    --to 2026-04-20 \
    [--depth max|target] \
    [--source auto|hyperliquid|binance|...] \
    [--cross-validate binance]
```

**Flow:**
```
plan = SourceRouter.plan(symbol, interval, start, end)
for slice in plan:
    progress_bar.update(slice.source, slice.start, slice.end)
    frame = slice.source.fetch_candles(symbol, interval, slice.start, slice.end)
    append_ohlcv(frame)
summary_table()
```

**Test coverage:**
- CLI args parse cleanly with argparse.
- `--depth max` uses `earliest_available()` across all sources.
- Progress output goes to stderr, machine-readable summary to stdout.
- Idempotent: running twice produces identical parquet state.
- Non-zero exit on source failures by default; `--allow-partial` overrides.

---

### P1.8 — Incremental updater service

**Files created:**
- `backend/services/data_updater.py` — `DataUpdater(symbol, interval)` periodically appends latest bars.
- `backend/services/scheduler.py` — minimal `PeriodicScheduler` wrapper over `asyncio`.
- `tests/unit/backend/services/test_data_updater.py`

**Flow:**
```
DataUpdater.tick(symbol, interval):
  latest_stored = parquet_reader.latest_timestamp(symbol, interval)
  latest_exchange = HyperliquidSource.latest_bar_close(symbol, interval)
  if latest_exchange > latest_stored:
      frame = HyperliquidSource.fetch_candles(
          symbol, interval, latest_stored + one_bar, latest_exchange
      )
      append_ohlcv(frame)
      stream_hub.emit('candle_close', frame.bars.iloc[-1])
```

**Test coverage:**
- No-op when nothing new.
- Appends exactly the new bars.
- Emits `candle_close` event per new bar.
- Handles restart gap (stored 1h ago, now multiple bars missing — fills them).

---

### P1.9 — REST API for candles + catalog + backfill jobs

**Files created:**
- `backend/api/candles.py` — routers.
- `backend/models/candles.py` — Pydantic response models.
- `backend/services/backfill_jobs.py` — async job runner + registry.
- `tests/unit/backend/api/test_candles.py`

**Endpoints:**
```
GET  /candles?symbol=&interval=&from=&to=&source=
  → { bars: [[ts, o, h, l, c, v], ...], source_breakdown, cache_hit }

GET  /catalog
  → [{ symbol, intervals: [...], earliest, latest, source_counts, bar_count }, ...]

POST /backfill
  body: { symbol, interval, start, end, depth?, source? }
  → { job_id }

WS   /stream/backfill/{job_id}
  → { type: 'progress', pct, slice_info }
  → { type: 'complete', total_bars, duration_s }
  → { type: 'error', message }

WS   /stream/candles?symbol=&interval=
  → { type: 'candle_close', bar: {...} }
```

**Test coverage:**
- Full HTTP round-trip via `TestClient`.
- WS connect + receive-bar happy path with a fake stream source.
- `GET /catalog` after seeding 3 symbols → 3 rows with correct metadata.

---

### P1.10 — HIP-4 outcome tape (minimal)

**Files created:**
- `backend/services/sources/outcome_source.py` — wraps `core/outcome_client.OutcomeClient.fetch_tape`.
- `backend/db/outcome_writer.py` — writes outcome tick-rows to `data/parquet/outcomes/market_id=<id>/...`.
- `backend/api/outcomes.py` — `GET /outcomes/{id}/tape`, WS `/stream/outcomes?market_id=`.
- `tests/unit/backend/db/test_outcome_writer.py`
- `tests/unit/backend/api/test_outcomes.py`

**Deferred to Phase 6:**
- Outcome-market board UI.
- Pricing-model edge computation endpoint.
- Category taxonomy (pol/sport/macro).

This commit just establishes the storage format and basic REST so Phase 6 has a tape to render.

---

## 4. Dependencies Added in Phase 1

```
# requirements.txt additions
duckdb>=1.1.0
pyarrow>=18.0.0
httpx>=0.27.0                # already present for tests
respx>=0.21.0                # HTTP mocking, dev
yfinance>=0.2.49             # equity + commodity adapter
ccxt>=4.4.0                  # optional — faster to maintain than bespoke binance/coinbase clients; evaluate in P1.2
```

Decision point at P1.2: **bespoke adapters** (full control, no extra dep, more code) vs **ccxt** (dozens of exchanges for free, less code, adds a dep). Default: bespoke for Binance + Coinbase because we only need historical candles and error handling is cleaner inline. Revisit if we need > 3 crypto exchanges.

---

## 5. Data Flow Diagrams

### 5.1 Backfill (one-shot)

```
user ── CLI ──▶ backfill.main()
                    │
                    ▼
                SourceRouter.plan(...)
                    │
         ┌──────────┴──────────┬──────────────┐
         ▼                     ▼              ▼
   CoinbaseSource        BinanceSource  HyperliquidSource
      .fetch(slice)       .fetch(slice)  .fetch(slice)
         │                     │              │
         └──────────┬──────────┴──────────────┘
                    ▼
               CandleFrame
                    │
                    ▼
           parquet_writer.append_ohlcv()
                    │
                    ▼
     data/parquet/ohlcv/symbol=BTC/interval=1h/year=Y/
```

### 5.2 Live candle stream

```
Hyperliquid WS ──▶ DataUpdater.on_bar_close
                         │
                         ├─▶ parquet_writer.append_ohlcv(bar)
                         │
                         └─▶ stream_hub.emit('candle_close', bar)
                                    │
                                    ▼
                       ws_subscribers for (symbol, interval)
                                    │
                                    ▼
                         UI chart lightweight-charts.update(bar)
```

### 5.3 Query

```
UI ── GET /candles?symbol=BTC&interval=1h&from=&to= ──▶ /candles router
                                                              │
                                                              ▼
                                               query_candles(...) (DuckDB)
                                                              │
                                                              ▼
                                       SELECT * FROM ohlcv WHERE symbol=? AND interval=?
                                       AND timestamp BETWEEN ? AND ?
                                       (partition pruning → one year dir)
                                                              │
                                                              ▼
                                                      pd.DataFrame → JSON bars
                                                              │
                                                              ▼
                                                         UI render
```

---

## 6. Testing Strategy

- **Unit:** every adapter, writer, reader, router, service — mocked HTTP where applicable, real parquet on a tmp_path fixture.
- **Golden frames:** a fixture directory `tests/fixtures/candles/` with deterministic small OHLCV CSVs. Each source adapter's tests assert round-trip against these.
- **Integration:** one `@pytest.mark.integration` test per source that hits the real endpoint with tiny range (only run locally or on-demand in CI, not on every push).
- **No network in CI:** default pytest run skips `@pytest.mark.network` and `@pytest.mark.integration`. CI adds `-m "not network and not integration"`.

---

## 7. Risks & Decision Points

| # | Risk | Mitigation |
|---|---|---|
| R1 | Hyperliquid Info API rate limits | Exponential retry wrapper; never more than N concurrent source fetches (configurable, default 4). |
| R2 | yfinance instability | Mark as optional; CryptoCompare as fallback in a future commit. Tests skip on network failure. |
| R3 | Parquet partial writes on crash | Atomic write via `tmp + rename`. |
| R4 | DuckDB memory on full-universe scan | Stream results via arrow instead of collecting to pandas for large queries. Add `limit` + cursor support to `/candles`. |
| R5 | Disk space on 1m bars for all crypto | `1m` is opt-in per symbol via `backfill --interval 1m --symbol BTC` — not pulled by default. |
| R6 | Equity-perp live tape vs equity underlying divergence | Store both under distinct symbols: `xyz:TSLA` (HL tape) and `TSLA` (yfinance underlying). `cross_validate` flags divergence > threshold. |
| R7 | HIP-4 tape volume explosion | Per-market partitioning (`market_id=<id>`) keeps per-query scan small. Monitor during Phase 6. |

**Open decision:** Store equity underlying (`TSLA`) separately or stitch into `xyz:TSLA`? Default: **separate**. Rationale: underlying has full history, HL tape is derived. Keep sources distinct so lineage is clear.

---

## 8. Success Criteria

End of Phase 1, all true:

1. `python -m backend.tools.backfill --symbol BTC --interval 1h --from 2015-01-01` pulls ~96,000 bars across 3 sources, writes to Parquet, completes < 10 minutes on home broadband.
2. `GET /catalog` lists every backfilled symbol/interval with earliest/latest/bar_count.
3. `GET /candles?symbol=BTC&interval=1h&from=2020-01-01&to=2020-12-31` returns 8,784 bars in < 500ms (DuckDB partition pruning).
4. WS `/stream/candles?symbol=BTC&interval=1h` emits a bar within 3 s of each real bar close.
5. 90% unit-test coverage on `backend/db/` and `backend/services/sources/`.
6. `data/` is gitignored; no commits touch it.
7. CI stays green — no network required in default test run.

---

## 9. Time Estimate

| Commit | Scope | Days |
|---|---|---|
| P1.1 HyperliquidSource | Protocol + primary adapter | 1.0 |
| P1.2 Binance + Coinbase | Paginated REST + tests | 1.5 |
| P1.3 yfinance | Adapter + HIP-3 mapping | 1.0 |
| P1.4 SourceRouter | Planning + cross-validate | 1.0 |
| P1.5 Parquet I/O | Writer + reader + dedupe | 1.5 |
| P1.6 DuckDB catalog | Views + query helper | 0.5 |
| P1.7 Backfill CLI | argparse + progress | 1.0 |
| P1.8 DataUpdater | Incremental + scheduler | 1.0 |
| P1.9 REST API | /candles /catalog + WS | 1.0 |
| P1.10 HIP-4 tape | Source + writer + API | 0.5 |
| **Total** | | **10 days ≈ 2 weeks** |

---

## 10. Out of Scope (deferred to later phases)

- **Feature store** (`data/parquet/features/`) — Phase 10 (ML).
- **Analog search indices** — Phase 9.
- **Outcome-market UI + pricing-model edge panel** — Phase 6.
- **Live equity tickers for HIP-3 underlying** — optional add-on if Polygon subscription materialises.
- **CoW / versioned datasets** — not needed v1.
