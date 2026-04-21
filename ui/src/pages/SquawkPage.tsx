// Live Squawk — Telegram channel feed. Backend polls every 60s; this
// page polls /squawk/latest every 15s so the UI stays within ~1 tick of
// freshness without hammering the backend. The backend keeps the last
// 100 posts in memory; this page renders them newest-first.

import { useCallback, useEffect, useRef, useState } from "react";

import { squawk as squawkApi, type SquawkLatestResponse, type SquawkPost } from "../api/endpoints";

const POLL_MS = 15_000;

export function SquawkPage() {
  const [data, setData] = useState<SquawkLatestResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await squawkApi.latest(200);
      setData(r);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    timer.current = window.setInterval(() => { void load(); }, POLL_MS);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [load]);

  const onRefresh = useCallback(async () => {
    setBusy(true);
    try {
      await squawkApi.refresh();
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [load]);

  const posts = data?.posts ?? [];
  const visible = filter.trim()
    ? posts.filter((p) => p.text.toLowerCase().includes(filter.toLowerCase()))
    : posts;

  const status = data?.status;
  const configured = status?.configured ?? false;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Live Squawk</h1>
          <p className="page__subtitle">
            Telegram channel feed — last 200 posts, auto-refresh every 15s.
          </p>
        </div>
        <div className="page__actions">
          <input
            type="search"
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: 200 }}
          />
          <button className="btn" onClick={onRefresh} disabled={busy}>
            {busy ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </header>

      {err && <div className="banner banner--error">{err}</div>}

      {!configured && (
        <div className="banner">
          Squawk isn't configured yet. Add provider <code>telegram</code> in
          {" "}
          <a href="#/apikeys">Sidebar → API Keys</a>
          {" "}
          with your bot token as <code>api_key</code> and the channel username/ID
          in <code>metadata.channel</code> (e.g., <code>{"{ \"channel\": \"@myfeed\" }"}</code>).
        </div>
      )}

      {configured && (
        <div className="squawk__status">
          <span>Channel: <code>{status?.channel || "—"}</code></span>
          <span>Posts: {status?.post_count ?? 0}</span>
          <span>Last polled: {status?.last_polled ? new Date(status.last_polled).toLocaleTimeString() : "never"}</span>
          {status?.last_error && <span className="muted">({status.last_error})</span>}
        </div>
      )}

      <section className="card">
        {visible.length === 0 ? (
          <div className="muted">
            {posts.length === 0 ? "No posts yet." : "No posts match your filter."}
          </div>
        ) : (
          <ul className="squawk__list">
            {visible.map((p) => <SquawkRow key={p.id} post={p} />)}
          </ul>
        )}
      </section>
    </div>
  );
}

function SquawkRow({ post }: { post: SquawkPost }) {
  return (
    <li className="squawk__item">
      <div className="squawk__meta">
        <span className="squawk__channel">{post.channel}</span>
        <time dateTime={post.posted_at}>{new Date(post.posted_at).toLocaleString()}</time>
      </div>
      <div className="squawk__text">{post.text}</div>
      {post.link && (
        <a href={post.link} target="_blank" rel="noopener noreferrer" className="muted">
          open post →
        </a>
      )}
    </li>
  );
}
